# 多模态模型评测平台 — 给开发者（和 Claude Code）的上手说明

内部使用的、带图形界面的**多模态模型评测平台**，团队 10 几个人用。被测模型全都是别人给的 HTTP 接口（OpenAI 兼容或 Anthropic 兼容），本平台没有 GPU。README.md 是面向使用者的文档（功能、格式、配置、已知限制），这份文档讲“怎么改这个项目、有哪些坑”。

## 已经定下来的决定（别推翻，除非用户重新决定）

- **混合方案**：评测引擎用开源的 **EvalScope**（跑评测、评分），平台自己做 Web 界面、任务管理、结果展示、复核、对比、报告。引擎通过 `EngineAdapter` 接口接入，不要在平台代码里写死 EvalScope 的细节。
- **前端必须用 Vue**（Vue 3 + TypeScript + Ant Design Vue 4），不要用 React。
- **登录和权限暂时不做**（用户明确说的）。所以没有账号体系，费用上限的“确认”只是防手滑，不是安全边界。别顺手加登录。
- **费用上限默认不限制**，是可选功能。
- 裁判模型由用户自己配置，评测数据可以发给它的服务商。自有评测集是小规模、非敏感数据。
- 界面文字、报错信息、文档都用**中文**。

## 目录

```
backend/app/
  main.py               应用入口，注册路由，托管前端（frontend/dist）
  config.py             环境变量配置（见 README 的配置表）
  db.py                 SQLAlchemy 引擎；ensure_columns() 做“只加列”的迁移
  models.py             数据库表
  schemas.py            请求/响应模型
  worker.py             后台 Worker（见下）
  routers/              models datasets runs compare schemes settings workers
  services/             budget composite dataset_validation catalog model_check
                        report rescoring tool_check tsv_import
  engines/              base.py（接口） evalscope_adapter.py evalscope_results.py evalscope_task.py
backend/tests/          pytest；引擎用 fake_engine.py + tests/fixtures 里记录下来的真实 EvalScope 输出
frontend/src/           views/（8 个页面） components/ api.ts router.ts theme.ts style.css format.ts
e2e/                    Playwright 浏览器测试（真实页面 + 接口 + 灌好的数据，不调用模型）
```

## 常用命令

```bash
cd backend && source .venv/bin/activate
uvicorn app.main:app --reload --port 8000   # API（改代码自动重载）
python -m app.worker                        # Worker：改了代码要手动重启，它不会自动重载
pytest                                      # 后端测试，不需要网络和真实模型
cd frontend && npm run dev                  # http://localhost:5173，/api 代理到 8000
cd frontend && npm run build                # 含 vue-tsc 类型检查；e2e 需要先 build
python -m pytest e2e                        # 浏览器测试；沙箱里用 CHROMIUM_PATH 指定 Chromium
```
提交前至少跑后端测试和 `npm run build`；改了界面再跑 e2e。**测试失败就不要提交**，别用 `;` 把测试和 `git commit` 串在一起（我们踩过：测试失败了提交照样推上去了）。

## 核心设计

**评分分三层，引擎得分永远不改**（services/rescoring.py）：
1. 引擎的判定：`SampleResult.is_correct` / `score`。
2. 平台自己的复核：`auto_correct`——`True` 表示宽松匹配把引擎判错的升成对（如 `6.8%` 对 `6.8`），`False` 表示引擎判对但工具调用参数不符（services/tool_check.py）。`None` 表示没意见。
3. 人工：`review_correct`，优先于一切。
`final_correct` = 人工 > 平台复核 > 引擎，筛选和对比用 `coalesce(final_correct, is_correct)`（旧数据里 `final_correct` 可能是 NULL）。
**复核后得分**（`adjusted_scores`）只在引擎主指标是“逐题得分的平均”时才给（先校验，不是假设；也自动识别 OVERALL 是总体平均还是子集平均）。F1/BLEU 这类不给，也不要猜。
自有**工具调用**评测集：引擎主指标 F1 只衡量“该不该调用”，所以平台另算“通过率”（`ensure_pass_rate`）作为主指标，引擎的 F1 降为次要指标。
用了裁判模型的任务不做宽松匹配。

**综合得分**（services/composite.py，`ScoreScheme` 表，界面“评分方案”页）：方案 = 评测集名称 + 相对权重，权重由用户在界面里配，自动换算成 100%。规则：模型缺方案里任何一个评测集的已完成结果就不给分；取各评测集主指标（有复核时用复核后得分）；只支持百分比类指标；同一模型同一评测集取最新一次已完成的任务；方案按评测集**名称**匹配、不绑版本。
**报告**（services/report.py）：任务详情和对比页导出单文件 HTML（图片内嵌、无外部依赖、内容已转义）。

**Worker**（worker.py）：任何数量的 Worker/槽位共用一个队列。
- 领任务是一条原子 UPDATE；同一个模型默认同时只跑 1 个任务（`ModelEndpoint.max_parallel_runs`）。
- 每个槽位定时心跳（`Worker` 表）；心跳丢失的任务会被别的 Worker 重新排队，并**从已答完的样本继续**（EvalScope `use_cache`，已答的题不重复调用也不重复计费）。
- 服务商 429/5xx/超时/连接重置 → 自动重试（退避，`AUTO_RETRY_MAX`）；评测中长时间没有新回答 → 看门狗终止并重试（`STALL_TIMEOUT_SEC`，下载阶段不算）。
- SIGTERM 会把手上的任务放回队列。丢了任务所有权的 Worker 会停手且不写结果。
- 费用上限：提交时估算超限需确认；运行中增量扫描 predictions 文件统计用量，超限就杀引擎。已知的小误差：停止瞬间在途的请求（≤并发数）服务商已计费但没记录。

**数据库**：SQLite（WAL）为主，`DATABASE_URL` 可换 PostgreSQL（**没测过**）。迁移只支持**新增可空列**（`db.ensure_columns()`），新表靠 `create_all`；改列类型、加 NOT NULL 列要自己写迁移。

**密钥**：模型 API key 用 Fernet 加密入库（`secret.key`，丢了就解不开），接口永远不返回 key，只通过子进程环境变量传给引擎，错误信息和日志会 redact。报告、日志、截图里**不能出现 key 和接口地址**。

## 约定

- 测试用记录下来的真实 EvalScope 输出（`tests/fixtures/`）和 `FakeAdapter`，不调用任何模型。新功能要补后端测试；有界面的补 e2e。
- 修 bug 先写能复现的测试，并确认它在修复前**会失败**（我们有一个“并列最优高亮”的测试，一开始没复现浮点误差，是个假测试）。
- 测试之间共用磁盘目录会互相污染：`conftest.py` 的 `fresh_db` 每个测试开始时清空 runs/ 和 datasets/，因为 id 每次都从 1 开始。
- 前端用 Ant Design Vue 按需引入（unplugin-vue-components），主题在 `theme.ts` 和 `style.css`，支持深色模式。TypeScript 固定在 5.x（vue-tsc 不兼容 TS 7）。Ant 的按钮文字会渲染成“保 存”（带空格），Playwright 选择器用正则 `保\s*存`。
- 模板里避免 `act(() => api.x())` 这类写法（vue-tsc 会报 `.value` 错），把处理函数放进 script。
- 不要擅自创建 Pull Request；提交说明写清楚做了什么、为什么。

## 踩过的坑

- **别用 `pkill -f "某个词"`**：会把当前这条 bash 命令自己也杀掉（退出码 144）。要杀进程就按 /proc 里的 argv 精确匹配，并排除 bash/sh。
- EvalScope 的 `use_cache` 是在原目录续跑；预测文件是边答边写的，最后一行可能写了一半，扫描时要忽略。
- EvalScope 的“Anthropic 适配”完全不支持视频/音频；OpenAI 适配支持 `video_url` / `input_audio`，格式仅 mp4/mpeg/mov/avi 和 wav/mp3。
- EvalScope 默认每个请求重试 5 次、间隔 10 秒，之后整个任务失败；平台在它之上再做一层自动续跑。
- 内置基准第一次跑要从 modelscope 下载数据集，可能很慢甚至超时（MMMU 有 30 个子集），数据集下载阶段是正常的慢，不是卡死。
- 内置基准里 CharXiv 的得分完全由裁判模型给出，不配裁判会直接报错（平台提交时已拦截，`needs_judge`）。
- 有的网关会给每次请求附加固定内容（实测一个网关 4.1k 输入 token，另一个只有 0.3k），影响 token 和费用，连通测试会提示。
- 重启服务时，之前卡住的任务会被重新排队并占满 Worker 槽位；对着已经不响应的网关的任务要手动取消。

## 验证过什么、没验证过什么

- **真实网关上验证过**：两种协议（OpenAI / Anthropic）的接入和连通测试；自有的看图选择题（zip 带图）、工具调用、开放问答（裁判模型）；内置的 ChartQA、DocVQA、MMBench、AI2D、OCRBench、MMStar、SEED-Bench-2-Plus、RealWorldQA、ToolBench-Static、CharXiv、InfoVQA（每个只跑几题，页面上标“已跑通”）；多模型并行、超限停止后续跑不重复计费；宽松匹配；工具调用参数检查。
- **只用本地模拟验证过**：服务商持续 503/429 时的自动续跑、Worker 被 kill -9 后接手、SIGTERM 优雅退出、TSV 导入。
- **没验证过**：VQAv2 和 MMMU（数据集下载太慢）、视频/音频（没做）、Docker 部署和 `--scale worker`（环境里没有 Docker 服务）、GitHub Actions（没触发过）、PostgreSQL、全量跑公开基准、其他服务商的 OpenAI 兼容接口、Windows/macOS。

## 还没做的

主要缺口：登录和权限（用户说先不做）、视频和音频（用户说先不做）、VQAv2/MMMU 补验证、Docker 和 CI 在真实环境里验证。设计文档在 Claude Docs 里（不在仓库），“实现状态”一节没同步后面的功能。

## 凭据

真实网关的地址和 key **绝对不要写进仓库、文档、截图、日志或提交说明**。在本机用时在“模型管理”里手动填，或放在仓库之外的文件里。
