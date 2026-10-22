import json
import re
import urllib.request


def api(page, path):
    return json.load(urllib.request.urlopen(page.base + "/api/v1" + path))


def test_run_list_shows_engine_and_reviewed_scores_and_the_missing_worker_hint(page):
    page.goto(f"{page.base}/runs")
    page.wait_for_selector(".ant-table-row")
    row = page.locator(".ant-table-row:has-text('model-a')").inner_text()
    assert "14.3%" in row and "复核后 71.4%" in row  # engine score kept, reviewed score next to it
    assert "没有 Worker 在线" in page.locator(".page").inner_text()  # a run is queued and nobody would pick it up


def test_run_detail_samples_are_tagged_and_filterable(page):
    page.goto(f"{page.base}/runs/1")
    page.wait_for_selector(".hero")
    assert "复核后 71.4%" in page.locator(".hero").inner_text()
    page.get_by_role("tab", name=re.compile("样本")).click()
    page.wait_for_selector(".verdict")
    assert page.get_by_text("宽松匹配通过").count() == 4
    page.get_by_text("有改判", exact=True).click()
    page.wait_for_timeout(600)
    assert page.locator(".verdict").count() == 4


def test_manual_review_overrides_and_recomputes_the_score(page):
    page.goto(f"{page.base}/runs/1")
    page.get_by_role("tab", name=re.compile("样本")).click()
    page.wait_for_selector(".verdict")
    first = page.locator(".verdict").nth(0)  # "6.8" answered "6.8%": lenient pass, a person disagrees
    first.get_by_role("button", name=re.compile(r"判\s*错")).click()
    page.wait_for_timeout(600)
    assert "答错" in first.inner_text() and "人工确认" in first.inner_text()
    assert api(page, "/runs/1")["adjusted"]["display"] == "57.1%"  # 4 of 7
    first.get_by_role("button", name=re.compile(r"判\s*错")).click()  # clicking again clears it
    page.wait_for_timeout(600)
    assert api(page, "/runs/1")["adjusted"]["display"] == "71.4%"


def test_compare_page_and_report_link(page):
    page.goto(f"{page.base}/compare?runs=1,2")
    page.wait_for_selector(".qrow")
    body = page.locator(".page").inner_text()
    assert "复核后得分" in body and "model-a" in body and "model-b" in body
    link = page.get_by_role("link", name=re.compile("导出报告"))
    assert "/api/v1/compare/report?run_ids=1,2" in link.get_attribute("href")
    html = urllib.request.urlopen(page.base + link.get_attribute("href").split("&download")[0]).read().decode()
    assert "模型对比报告" in html and "<script" not in html


def test_run_report_opens_as_a_page(page):
    page.goto(f"{page.base}/api/v1/runs/1/report")
    assert "model-a × 图表问答-演示" in page.content() and "答错的题" in page.content()
    assert "复核后" in page.locator(".hero").inner_text()


def test_model_form_saves_parallel_runs(page):
    page.goto(f"{page.base}/models")
    page.wait_for_selector("text=model-a")
    page.get_by_role("button", name=re.compile(r"编\s*辑")).first.click()
    page.wait_for_selector("text=同时评测的任务数")
    page.locator(".ant-drawer input[placeholder='1']").fill("3")
    page.get_by_role("button", name=re.compile(r"保\s*存")).click()
    page.wait_for_timeout(1200)
    assert [m for m in api(page, "/models") if m["name"] == "model-a"][0]["max_parallel_runs"] == 3


def test_spending_limit_warns_before_an_expensive_submit_and_nothing_is_created_on_cancel(page):
    before = api(page, "/runs?page_size=50")["total"]
    page.goto(f"{page.base}/settings")
    page.wait_for_selector("text=上限设置")
    page.get_by_label("单次评测 · token 上限").fill("100")
    page.get_by_role("button", name=re.compile(r"保\s*存")).click()
    page.wait_for_selector("text=已保存")
    try:
        page.goto(f"{page.base}/runs/new")
        page.wait_for_selector(".pick")
        page.locator(".pick", has_text="model-b").click()
        page.locator(".pick", has_text="图表问答-演示").click()
        page.wait_for_selector("text=合计约")
        page.get_by_role("button", name=re.compile("开始评测")).click()
        page.wait_for_selector(".ant-modal-confirm")
        assert "预计会超出费用上限" in page.locator(".ant-modal-confirm").inner_text()
        page.get_by_role("button", name=re.compile(r"取\s*消")).click()
        page.wait_for_timeout(600)
        assert api(page, "/runs?page_size=50")["total"] == before
    finally:  # leave the shared data as it was
        req = urllib.request.Request(page.base + "/api/v1/settings/budget", data=b"{}", method="PUT", headers={"content-type": "application/json"})
        urllib.request.urlopen(req)


def test_dark_theme_toggle_is_remembered(page):
    page.goto(f"{page.base}/runs")
    page.wait_for_selector(".ant-table-row")
    page.click("button:has(.anticon-bulb)")
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"
    page.reload()
    page.wait_for_selector(".ant-table-row")
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"
