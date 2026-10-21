# 多模态模型评测平台

内部使用的多模态大模型评测平台：在网页上接入别人提供的模型 HTTP 接口（OpenAI / Anthropic 格式），选评测集，一键发起评测，查看得分、延迟 / token 和逐条样本。评测引擎复用开源的 [EvalScope](https://github.com/modelscope/evalscope)，平台自己负责任务管理、结果存储和界面。

设计依据见《多模态模型评测平台设计文档》；这个仓库实现的是它的第一期（MVP）。

## 结构

```
backend/    FastAPI + SQLAlchemy；app/worker.py 是后台 Worker；app/engines/ 是引擎适配器
frontend/   Vue 3 + TypeScript + Element Plus + ECharts
```

```
浏览器 ──REST──> API ──写任务──> 数据库(SQLite/PostgreSQL) <──取任务── Worker ──子进程──> EvalScope ──> 被测模型接口
                                                                 └─ 解析输出，写入统一的 metric / sample 表
```

平台只通过 `EngineAdapter`（`backend/app/engines/base.py`）和引擎打交道，换引擎不需要改 API、表结构和前端。

## 运行

需要 Python 3.10+ 和 Node 20+。

```bash
# 后端
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

uvicorn app.main:app --port 8000          # API
python -m app.worker                      # Worker（另开一个终端；评测任务由它执行）

# 前端
cd frontend
npm install
npm run build                             # 构建后由后端直接托管：http://localhost:8000
npm run dev                               # 或开发模式：http://localhost:5173（代理 /api 到 8000）
```

数据（数据库、加密密钥、上传的评测集、每次评测的输出）都在 `APP_DATA_DIR`（默认 `backend/data/`，已在 `.gitignore` 里）。

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_DATA_DIR` | `backend/data` | 数据目录 |
| `DATABASE_URL` | `sqlite:///<数据目录>/app.db` | 换 PostgreSQL 时填 SQLAlchemy 连接串 |
| `APP_SECRET_KEY` | 自动生成到 `<数据目录>/secret.key`（权限 600） | 加密模型 API key 的 Fernet 密钥 |
| `MAX_UPLOAD_MB` | 100 | 评测集上传大小上限 |
| `RUN_TIMEOUT_SEC` | 21600 | 单个评测任务的运行时间上限 |

## 测试

```bash
cd backend && pytest        # 不需要网络和真实模型：引擎用记录下来的真实 EvalScope 输出代替
cd frontend && npm run build   # 含 vue-tsc 类型检查
```

## 安全

- 模型 key 用 Fernet 加密后存库；任何接口都不返回 key，页面只显示后四位。
- key 只通过环境变量传给 EvalScope 子进程，不写进配置文件、日志和结果目录；错误信息和日志在展示前会替换掉 key。
- 上传的 zip 会检查路径穿越和解压后大小；样本图片接口只会读取该任务自己的目录。
- 连通测试会提醒接口地址是 HTTP（明文传输）。

## 当前没做 / 已知限制

- **没有登录和权限**：谁能访问就能看到所有模型和结果。设计里一期是“简单账号”，还没实现，部署前要放在内网或加一层认证。
- **重试是从头开始**：设计目标是“已完成的样本不重复调用”，目前还没做。
- **进度只有阶段和百分比**：来自解析引擎日志里的进度条，非流式调用没有 TTFT。
- **Worker 一次只跑一个任务**，且只支持单个 Worker（启动时会把遗留的“运行中”任务重新排队）。
- **裁判模型只支持 OpenAI 格式的接口**；视频 / 音频输入和“图片 + 工具调用”的组合没有验证过。
- 内置基准里只有 `chartqa`、`docvqa`、`mm_bench` 在本平台实际跑通过（页面上标“已跑通”），其余来自 EvalScope 的官方列表。
- 没有提供 Docker 配置。
