# AGENT.md — Personal RAG 开发规范

> 面向在此仓库中工作的 AI 代理与开发者。架构总览见 [CLAUDE.md](CLAUDE.md)，当前分支状态与交接信息见 [HANDOFF.md](HANDOFF.md)。本文件只定义**规范**，不重复上述两份文档的内容。

## 1. 分支与文档约定

- 当前活跃分支 `feature/agent`（多 Agent 自适应路由）；`master` 为经典 RAG 流水线。
- 完成功能改动后，**必须更新 `HANDOFF.md`** 的改动摘要与关键文件表。
- 提交信息遵循仓库既有风格：`type(scope): 中文描述`（如 `feat(agent): ...`、`fix(visualization): ...`）。

## 2. 开发命令

```bash
# 后端
cd backend
python run.py                      # 启动 http://localhost:8000
python run.py --reload             # 热重载开发
python -m unittest discover -s tests -v   # 后端全部测试（pytest 亦可）

# 前端
cd frontend
npm run dev                        # Vite 开发服务器
npm run build                      # 生产构建：tsc -b && vite build（必须通过）
npm run lint                       # oxlint
```

- 后端无 ruff/black/mypy 配置，风格靠本文件约定手工保持。改完代码至少保证 `python -c "import app.main"` 通过。
- 首次在新环境跑测试前：`pip install -r requirements-dev.txt`（含 pytest、pytest-asyncio）。

## 3. 后端编码规范

### 模块与注释
- 每个模块以 `# Personal RAG - <模块名>` 头注释 + 中文 docstring 开头。新增服务可用英文 docstring，但代码注释、日志、错误消息**一律用中文**。
- 段落用 `# ── Section ──` 分隔符组织。

### 命名
- 函数/方法：`snake_case`；类：`PascalCase`；常量：`UPPER_SNAKE`（如 `STREAM_CHARACTER_DELAY_SECONDS`）。
- 私有 helper：模块内下划线前缀（`_running_pause_event`）。
- 全局单例：小写下划线（`vector_store`、`task_manager`、`chat_run_manager`）。
- API 对外 JSON 字段：`snake_case`。

### 类型注解
- **必须全量**：所有函数参数与返回值写类型注解（含 `-> None`）。
- 新代码用 `X | None` 联合语法，**不要新增 `Optional[...]`**（旧代码中的 `Optional` 属历史遗留）。
- ORM 模型用 SQLAlchemy 2.0 风格：`Mapped[...]` + `mapped_column`。
- 泛型集合用内置：`dict[str, ...]` / `list[...]`。

### 分层约定
- **服务层**：有状态的服务封装为类 + 文件底部模块级单例（参照 `services/task_manager.py` 的 `TaskManager`、`services/chat_execution.py` 的 `ChatRunManager`）。状态不放在裸模块级 dict。
- **API 层保持薄**：handler 只做请求解析 + 调 service + 返回，不承载业务编排。通过 `Depends(get_db)` 注入 DB session。
- **import 惯例**：重子模块（`app.agent.*`、`app.services.*` 的运行时模块）在函数体内懒加载，避免应用启动时急切导入造成循环依赖（参照 `services/chat_execution.py` 的 `agent_event_generator`）。纯类型/配置可在模块顶部 import。
- **SSE 协议**：聊天流式走 sse-starlette，事件类型固定为 `token` / `citation` / `done` / `error`，外加 Agent 扩展事件（`tool_call` / `tool_result` / `route_selected` / `context_compressed` 等）。**不得改动现有事件名与 payload 结构**，前端依赖它们。

### 健壮性要求
- 不硬截断文本：长上下文走 `services/context_compression.py` 分层压缩；压缩失败显式报错，不静默丢内容。
- 本地模式（`mode == "local"`）必须禁用网络工具，作为硬安全边界。
- 路由决策必须持久化完整 provenance（打分、来源、置信度、分类器开销），写入 `agent_runs` 对应字段。
- 引用编号（`[N]`）是用户可见的精确契约：绝不臆造、猜测、复用或重编号。

## 4. 前端编码规范

- 组件按 domain 分组目录：`components/chat/`、`documents/`、`citations/`、`settings/`、`layout/`、`notes/`。
- 三层职责分离：`api/`（网络层，axios + SSE）→ `services/`（业务编排，如 `chatExecution.ts`）→ `store/`（Zustand 状态）。组件不直接发网络请求。
- 类型定义放 `types/*.ts`，跨组件共享的接口必须在 types 中声明。
- 代码注释用中文。组件命名 PascalCase，事件回调命名 `onXxx`。
- 构建必须过 `npm run build`（`tsc -b`）与 `npm run lint`（oxlint）。

## 5. 测试要求

- 测试目录 `backend/tests/` 已存在，风格为 pytest + pytest-asyncio（少数 unittest.TestCase，新增用 pytest）。
- **新增或修改的业务逻辑必须补/更新测试**，重点模块：`agent/routing.py`（启发式打分与阈值）、`services/retriever.py`（RRF 融合）、`agent/supervisor.py`（worker 状态合并与引用重映射）、`services/context_compression.py`、`services/citation.py`。
- 测试运行：`cd backend && python -m unittest discover -s tests -v`。
- 目前无 `pytest.ini` / `conftest.py`，如需全局 fixture 再补，不必强行引入。

## 6. AI 代理工作守则

1. **改前先读**：任何修改前先 Read 目标文件全文，确认与描述一致。
2. **不重复造轮子**：检索是否已有单例/工具/模式可复用（`task_manager`、`event_bus`、`web_fetcher`、`context_compressor` 等）。
3. **行为保持**：重构必须行为等价；拆分大文件时同步更新所有 import 方（用 `grep` 确认，如 `tests/test_run_recovery.py` 曾直接引用 `api/chat.py` 内部符号）。
4. **保持薄 API + 厚 service**：不要在 handler 里写编排逻辑。
5. **环境注意**：venv 依赖需 `requirements-dev.txt` 完整安装；若 `import app.main` 或测试因缺失依赖失败，先修环境再改代码。
6. **提交前**：跑全量测试 + `import app.main` + 前端 `npm run build`，并更新 HANDOFF.md。

## 7. 已知工作区注意事项

- `backend/app/api/chat.py` 的执行编排在 `backend/app/services/chat_execution.py`；取消/暂停/恢复的状态在 `ChatRunManager` 单例中。引用这些状态从 service 导入，**不要**重新在 api 层维护裸 dict。
- `backend/tests/test_run_recovery.py` 通过 `chat_run_manager.cancellation_flags` / `pause_flags` 注入测试事件，改动该 manager 时需同步测试。
