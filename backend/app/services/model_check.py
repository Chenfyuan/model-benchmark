"""Connectivity test for a model endpoint.

Beyond "does it answer", it checks the things that silently ruin multimodal evaluations:
  - image: the model must actually *see* an image (a random code is drawn into it; the model must read it back);
  - tools: the endpoint must return a structured tool call;
and it warns about plain HTTP and about a large per-request token baseline.
"""
from __future__ import annotations

import base64
import io
import random
import time
from typing import Any

import httpx
from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]
BASELINE_TOKEN_WARN = 1500

WEATHER_TOOL = {
    "name": "get_weather",
    "description": "Get current weather for a city",
    "schema": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
}


def openai_base(url: str) -> str:
    url = url.rstrip("/")
    return url if url.endswith("/v1") else url + "/v1"


def anthropic_base(url: str) -> str:
    url = url.rstrip("/")
    return url[: -len("/v1")] if url.endswith("/v1") else url


def _code_image(code: str) -> str:
    img = Image.new("RGB", (480, 160), (255, 214, 10))
    font = None
    for path in FONT_CANDIDATES:
        try:
            font = ImageFont.truetype(path, 52)
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default(size=52)
    ImageDraw.Draw(img).text((24, 48), code, fill=(15, 15, 15), font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


class _Client:
    """Minimal protocol-aware chat client (text, image, tools)."""

    def __init__(self, protocol: str, base_url: str, api_key: str, model: str, http: httpx.Client,
                 extra_headers: dict[str, str] | None = None):
        self.protocol, self.model, self.http = protocol, model, http
        if protocol == "openai":
            self.url = openai_base(base_url) + "/chat/completions"
            self.headers = {"Authorization": f"Bearer {api_key}"}
        else:
            self.url = anthropic_base(base_url) + "/v1/messages"
            self.headers = {"Authorization": f"Bearer {api_key}", "x-api-key": api_key, "anthropic-version": "2023-06-01"}
        self.headers = {**(extra_headers or {}), **self.headers}

    def chat(self, text: str, image_b64: str | None = None, tool: dict | None = None) -> dict[str, Any]:
        if self.protocol == "openai":
            content: Any = text
            if image_b64:
                content = [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                    {"type": "text", "text": text},
                ]
            body: dict[str, Any] = {"model": self.model, "max_tokens": 200, "messages": [{"role": "user", "content": content}]}
            if tool:
                body["tools"] = [{"type": "function", "function": {
                    "name": tool["name"], "description": tool["description"], "parameters": tool["schema"]}}]
        else:
            content = text
            if image_b64:
                content = [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_b64}},
                    {"type": "text", "text": text},
                ]
            body = {"model": self.model, "max_tokens": 200, "messages": [{"role": "user", "content": content}]}
            if tool:
                body["tools"] = [{"name": tool["name"], "description": tool["description"], "input_schema": tool["schema"]}]

        t0 = time.time()
        resp = self.http.post(self.url, headers=self.headers, json=body)
        latency_ms = int((time.time() - t0) * 1000)
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        if self.protocol == "openai":
            if not data.get("choices"):
                # Some gateways answer errors (bad key, no quota) with HTTP 200 and a bare {"code","message"} body.
                raise RuntimeError(f"接口返回了错误而不是模型回答: {resp.text[:200]}")
            choice = data["choices"][0]
            msg = choice.get("message") or {}
            return {
                "text": msg.get("content") or "",
                "tool_called": bool(msg.get("tool_calls")),
                "input_tokens": (data.get("usage") or {}).get("prompt_tokens"),
                "latency_ms": latency_ms,
            }
        blocks = data.get("content") or []
        return {
            "text": "".join(b.get("text", "") for b in blocks if b.get("type") == "text"),
            "tool_called": any(b.get("type") == "tool_use" for b in blocks),
            "input_tokens": (data.get("usage") or {}).get("input_tokens"),
            "latency_ms": latency_ms,
        }


def check_model(protocol: str, base_url: str, api_key: str, model: str, timeout: float = 60.0,
                extra_headers: dict[str, str] | None = None) -> dict[str, Any]:
    warnings: list[str] = []
    checks: dict[str, dict[str, Any]] = {}
    if base_url.lower().startswith("http://"):
        warnings.append("接口地址是 HTTP 而不是 HTTPS：key 和评测数据在网络上是明文传输。")

    code = f"CODE-{random.randint(100, 999)}"
    image = _code_image(code)
    with httpx.Client(timeout=timeout) as http:
        client = _Client(protocol, base_url, api_key, model, http, extra_headers)

        def run(name: str, fn):
            try:
                checks[name] = fn()
            except Exception as e:  # noqa: BLE001  (report any failure to the user, with the key scrubbed)
                msg = str(e).replace(api_key, "***") if api_key else str(e)
                checks[name] = {"ok": False, "detail": f"{type(e).__name__}: {msg}"[:300]}

        def text_check():
            r = client.chat("Reply with the single word: pong")
            return {"ok": bool(r["text"].strip()), "detail": r["text"].strip()[:60],
                    "latency_ms": r["latency_ms"], "input_tokens": r["input_tokens"]}

        def image_check():
            r = client.chat("What text is written in this image? Answer with only the text.", image_b64=image)
            ok = code in r["text"]
            return {"ok": ok, "latency_ms": r["latency_ms"],
                    "detail": "模型读出了图中的随机码" if ok else f"没有读出图中的内容，回答是：{r['text'].strip()[:80]}"}

        def tools_check():
            r = client.chat("What's the weather in Paris?", tool=WEATHER_TOOL)
            return {"ok": r["tool_called"], "latency_ms": r["latency_ms"],
                    "detail": "返回了结构化工具调用" if r["tool_called"] else "没有返回工具调用"}

        run("text", text_check)
        if checks["text"]["ok"]:
            run("image", image_check)
            run("tools", tools_check)
        else:
            checks["image"] = {"ok": False, "detail": "文本调用未通过，已跳过"}
            checks["tools"] = {"ok": False, "detail": "文本调用未通过，已跳过"}

    baseline = checks["text"].get("input_tokens")
    if baseline and baseline > BASELINE_TOKEN_WARN:
        warnings.append(
            f"一次只有几个字的请求，接口就报告了约 {baseline} 个输入 token。"
            "很可能是网关给每次请求加了固定内容；这会让费用和 token 统计偏高，"
            "如果是隐藏的系统提示，还可能影响模型行为，评测的就不是“裸模型”。"
        )
    return {
        "ok": checks["text"]["ok"] and checks["image"]["ok"],
        "checks": checks,
        "warnings": warnings,
        "baseline_input_tokens": baseline,
    }
