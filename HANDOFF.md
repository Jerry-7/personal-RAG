# Personal RAG — 对话交接文档

> 最后更新: 2026-08-17
> 当前分支: `feature/agent`

## 项目概览

个人 RAG 系统，三栏布局：左侧文档管理 | 中间对话区 | 右侧引用面板。  
后端 FastAPI + SQLite + FAISS，前端 React + TypeScript + Zustand。

## 当前分支状态

| 分支 | 说明 |
|------|------|
| `master` | 经典 RAG 流水线（固定检索→生成） |
| `feature/agent` | **当前** — 多 Agent、三级自适应路由、目标运行时与状态可视化 |

## 当前 Agent 架构

- **三级路由**：`fast / standard / expert`，支持手动指定和自动复杂度评分。
- **Agent 主导路由**：每条 `auto` 请求先由 fast 模型语义分类（复杂度评分 + 置信度 + 语义原因码），硬编码关键词打分器仅作**快通道**（极短/高置信 fast 请求跳过模型）与**失败兜底**。`agent_routing_mode` 可切回旧混合（`adaptive`）或纯启发式（`heuristic`）。
- **多 Agent 编排**：expert 路由进入 Supervisor，模型规划本地检索、网页研究等并行 worker，最后由 synthesizer 汇总。
- **持久化目标树**：每个 root、primary Agent、worker 和 synthesizer 都记录 GoalNode、状态、重试、依赖、模型与工具预算。
- **完整工具能力**：Agent 等级不再屏蔽工具；`local` 模式仍作为安全边界禁用网络工具。
- **Prompt 软频控**：各 Profile 配置总工具调用建议和单工具重复建议，只观测超建议行为，不做等级硬拒绝。
- **上下文压缩**：长上下文由压缩 Agent 分层处理，保护 URL、引用号和业务标识；压缩失败显式终止，不做文本硬截断。
- **目标语义提取**：网页证据按研究目标由提取 Agent 语义抽取 + 压缩，替代字符边界硬切；本地展示片段改为整句截断（`clip_to_sentence`），任何文本不再从半句/单词中间切断。
- **运行可视化**：前端展示路由来源与置信度、目标树、并行分支、工具调用、重试、压缩指标、工具频控和历史运行分析。

## 关键路由策略

| 等级 | 主 Profile | 路径 | 总工具建议 | 单工具重复建议 |
|------|------------|------|------------|----------------|
| fast | `fast_general` | direct | 2 | 1 |
| standard | `standard_research` | tool_agent | 5 | 3 |
| expert | `expert_supervisor` | supervisor | 10 | 5 |

网页模式最低进入 standard；expert Supervisor 的最大分支数和深度由版本化路由策略约束。所有自动决策会持久化评分、原因、来源、置信度和分类器开销。

## 最近改动摘要

### 1. Agent 架构升级 (`44337d9`)
- 从 master cherry-pick 的 ReAct Agent 核心代码
- 新增: `agent/tools.py`, `agent/builtin_tools.py`, `agent/loop.py`
- Provider 层新增 `chat_with_tools()` 方法（Ollama/OpenAI/Anthropic）
- `config.py` 新增 `agent_enabled=True`, `agent_max_iterations=5`
- 前端新增 `tool_call`/`tool_result`/`max_iterations` SSE 事件

### 2. 异步文档上传 + SSE 进度 (`4811c35`)
- 上传立即返回（不再阻塞等索引）
- 后台 `asyncio.create_task` + `Semaphore(10)` 并发控制
- 新增: `event_bus.py`, `task_manager.py`, `indexing_worker.py`
- 前端实时进度卡片（上传区下方）+ 自动 SSE 重连

### 3. PaddleOCR 3.x 兼容 (`4b19b6e`)
- `show_log` 参数已移除 → 用 `logging.setLevel()`
- `use_angle_cls` → `use_textline_orientation`
- `ocr(cls=True)` 参数已移除
- 返回值从 tuple list → `OCRResult` dict (`rec_texts`)

### 4. Bug 修复
- **FAISS 维度不匹配**: `vector_store.py` 从硬编码 768 → 自动检测
- **输入框消失**: `ChatContainer` 始终渲染，不再条件切换
- **Agent 截断**: 不再重复调用 LLM，直接用 `chat_with_tools` 结果
- **tool_calls 格式**: `arguments` 传 dict 不传 string
- **SettingsModal 空白下拉**: `[].map()` truthy bug → `.length > 0` 判断
- **`.env` 模型配反**: `OLLAMA_LLM_MODEL` 和 `OLLAMA_EMBEDDING_MODEL` 值互换
- **DB settings 表配反**: 同上，数据库存储优先级高于 `.env`

### 5. 拆分聊天执行编排 (`02e3908`)
- `backend/app/api/chat.py` 从 768 行压到 269 行，只保留 HTTP 请求解析与响应包装
- 执行编排迁至新模块 `backend/app/services/chat_execution.py`（`agent_event_generator` + `ChatRunManager` 单例）
- 取消/暂停/恢复状态统一由 `ChatRunManager` 管理，不再在 API 层维护裸 dict

### 6. Agent 主导路由 (当前工作区)
- 路由主导权从硬编码关键词打分（`ComplexityRouter`）交给路由 Agent
- `adaptive_routing.py` 重构为 Agent-first：模型优先分类，启发式降级为快通道 + 失败兜底
- 新增 `agent_routing_mode = model | adaptive | heuristic`（默认 `model`），`adaptive` 完整保留旧混合行为
- 新增快通道开关 `agent_routing_fast_path_enabled` / `max_chars` / `confidence`（默认 20 字符、置信 ≥0.85）
- `enabled=False` 或 `heuristic` 模式时零模型调用；web 模式硬约束（≥standard）与手动 tier 覆盖不变
- 路由来源/评分/置信度/原因码 provenance 全保留，`decision_source` 取值不变（前端类型无需改动）

### 7. 硬截断替换为 Agent 语义提取 (当前工作区)
- 核心改动：`web_research.py` 的 `_excerpt`（关键词打分 + 字符硬切，会从段落中间切断）被移除，改为 `SemanticExtractor` 目标语义提取
- 新模块 `services/semantic_extractor.py`：目标提取 Agent → 仍超预算则压缩 Agent 收敛 → 失败时整段关键词兜底（绝不砍半段）
  - 短内容短路：预算内零模型调用（`estimate_tokens ≤ max(128, budget)` 直接返回）
  - 同一 URL 的提取结果缓存在 `AgentRunContext.page_evidence`，`fetch_web_page` / `crawl_website` / 引用 snippet 复用，每页只提取一次
- 新工具函数 `services/text_utils.py::clip_to_sentence`：展示片段统一整句截断，不再 `[:N]` 半句切断 —— 引用 snippet（generator/builtin_tools）、sources 上下文（api/sources.py）、`web_search` 摘要、`notes.py` 摘要与来源 excerpt
- 保留的 `[:N]` 均为标签/标识符/DB 字段上限/安全边界（标题、tag 列表、文件 hash 前缀、robots.txt 解析上限），非展示正文
- 新增配置 `agent_extraction_enabled=True` / `agent_extraction_max_chars=3500`；`enabled=False` 时退化为原样返回（不截断、不调用模型）
- 新增测试 `tests/test_semantic_extractor.py`（14 项：短路/提取/压缩/兜底/缓存/整句截断）+ `test_research_agent.py` 笔记摘要句边界测试

### 8. 消息序列化统一 + run 内压缩阈值 (当前工作区)
- 三处历史序列化统一为 `<message index=N role="user">...</message>` 配对标签（`adaptive_routing` / `conversation_memory` / `context_compression`），修复 `<user>...</message>` 不对称缺陷
- `compress_messages` 新增 `min_compress_tokens` 门控，`AgentLoop` 每次迭代传 `agent_run_compress_threshold`（默认 20000）：低于阈值放行不压缩，避免对大上下文反复 map-reduce（省 token）
- 新增测试：`test_adaptive_routing` 配对标签、`test_context_compression` 阈值门控（跳过/触发两态）

### 9. 子 Agent 模型分层: fast 档统一 (当前工作区)
- 主 Agent 推理走 `agent_standard_model` / `agent_expert_model`（高智能档）；子 Agent 任务——路由分类、上下文压缩、目标语义提取、会话摘要压缩——统一走 `agent_fast_model`（轻量档）
- 新增 `model_selection.select_fast_model()`：按 `fast_general` profile 解析 fast 档模型，未配置时回退默认 LLM（各档同模型，行为与以前一致）
- 固定点：`AgentLoop` 的压缩器、`SemanticExtractor` 默认模型、`chat_execution` 的路由分类器与 `update_summary`
- 新增 `extract_facts` 内置工具：主 Agent 把长来源**引用**（chunk_id / 已抓取网页 URL）交给 fast 档提取 Agent 代读，只返回与 objective 相关的事实，不把全文拖进主上下文（省 token）
- `AGENT_SYSTEM_PROMPT` 新增 **Task Delegation To Sub-Agents** 小节：把"何时委派"的判断交给主 Agent——长来源只取部分事实时用 `extract_facts`、需要全文才用 `read_chunk`、只传引用不粘原文、不委派短内容；委派策略不再是代码写死
- 新增测试：`select_fast_model` 两态、`SemanticExtractor` 默认 fast、`AgentLoop` 压缩器固定 fast、`test_extract_facts.py`（chunk/URL 解析 + 错误引导）

## 配置注意

### `.env` / DB Settings 优先级
`/api/settings` 读取逻辑: **DB > `.env` > `config.py` 默认值**。  
修改设置通过前端设置弹窗会写入 DB，覆盖 `.env`。  
如果值不对，同时检查 `.env` 和 `sqlite3 data/app.db "SELECT * FROM settings;"`

### 当前模型配置
```
LLM: qwen3.5-9b  (Ollama @ 10.10.0.3:11434)
Embedding: bge-m3  (Ollama @ 10.10.0.3:11434)
```

### Agent 开关
`config.py:73` — `agent_enabled: bool = True`  
`False` 时回退到经典 RAG 流水线（`generator.py`)

### 路由模式 (`agent_routing_mode`)
`model`（默认）：每条 `auto` 请求先经 fast 模型语义路由，启发式仅作快通道 + 失败兜底；每条请求多一次 fast 模型调用（本地 Ollama 约 0.5–3s），由快通道缓解。  
想回滚旧行为：`.env` 设 `AGENT_ROUTING_MODE=adaptive`（旧混合）或 `heuristic`（纯启发式，零模型调用）。

### 目标语义提取 (`agent_extraction_enabled`)
`True`（默认）：网页正文按研究目标做 Agent 语义提取，超预算时压缩收敛，证据与引用 snippet 均不硬截断。  
每页大正文多一次模型调用（超过 3500 字才触发，短页短路）；想完全关掉：`.env` 设 `AGENT_EXTRACTION_ENABLED=False`（正文原样入库，展示片段仍整句截断）。

### run 内压缩触发阈值 (`agent_run_compress_threshold`)
默认 `20000`。Agent 循环每次迭代前对消息做压缩，但**只有上下文超过该阈值才触发 map-reduce**（低于 `agent_context_max_tokens=12000` 短路零调用，12000–20000 之间放行不压）。目的：避免对"已压缩过的上下文 + 新工具结果"反复整段通读压缩——压缩每次要读全文一遍（≈R token），单次迭代反而倒贴，只在防溢出/结果复用时才省。  
**硬约束**：该值必须小于 `模型窗口 − system prompt − tools schema − 输出(4096)`。qwen 32k 窗口下 20000 安全；小窗口模型（8k/16k）请调低，否则放行后主调用会溢出。

### 模型分层 (`agent_fast_model` / `agent_standard_model` / `agent_expert_model`)
三个值默认都为空 → 全部回退到默认 LLM 模型（分层不生效，行为同以前）。想分层只需设 `AGENT_FAST_MODEL`：
- `AGENT_FAST_MODEL`：子 Agent 任务 —— 路由分类、上下文压缩、目标语义提取、会话摘要压缩、`extract_facts`（难度不高但吃上下文、费 token 的活）
- `AGENT_STANDARD_MODEL` / `AGENT_EXPERT_MODEL`：主 Agent 推理 —— `standard_research` / `expert_supervisor` 及其 worker
本地 Ollama 可让 fast 档指向更小模型（如 `qwen3:4b`）省 token，主推理仍用大模型。

## 关键文件

| 文件 | 作用 |
|------|------|
| `backend/app/agent/loop.py` | ReAct Agent 主循环 + System Prompt |
| `backend/app/agent/routing.py` | 三级复杂度路由 + Agent Profile 注册表 |
| `backend/app/agent/adaptive_routing.py` | Agent 主导路由（模型优先分类 + 启发式快通道/兜底） |
| `backend/app/agent/model_selection.py` | Profile→模型映射 + `select_fast_model()` fast 档解析 |
| `backend/app/agent/planning.py` | Supervisor 目标规划与受限回退 |
| `backend/app/agent/supervisor.py` | 并行 worker、重试和结果汇总 |
| `backend/app/services/chat_execution.py` | Agent 执行编排（`agent_event_generator` + `ChatRunManager`） |
| `backend/app/agent/tools.py` | ToolRegistry + `@skill` 装饰器 |
| `backend/app/services/goal_runtime.py` | GoalNode 生命周期与有序运行事件 |
| `backend/app/services/context_compression.py` | 无硬截断的分层上下文压缩 |
| `backend/app/services/semantic_extractor.py` | 目标语义提取 (提取 Agent → 压缩收敛 → 整段兜底) |
| `backend/app/services/text_utils.py` | `clip_to_sentence` 整句截断工具 |
| `backend/app/agent/builtin_tools.py` | 4 个内置工具 (search/list_docs/read_chunk/extract_facts) |
| `backend/app/services/event_bus.py` | 内存 pub/sub (asyncio.Queue per doc_id) |
| `backend/app/services/task_manager.py` | Semaphore(10) 并发控制 |
| `backend/app/services/indexing_worker.py` | 后台索引胶水层 |
| `backend/app/services/indexer.py` | 索引流水线 (parse→chunk→embed→store) |
| `backend/app/db/vector_store.py` | FAISS 向量存储 (自动检测维度) |
| `backend/app/providers/ollama.py` | Ollama LLM + Embedding + Tool Calling |
| `backend/app/api/documents.py` | 上传 + SSE 进度端点 |
| `backend/app/api/chat.py` | 对话 SSE 端点 (Agent/经典双模式) |
| `backend/app/api/research.py` | 运行历史、目标详情与路由分析 API |
| `frontend/src/components/chat/ActivityTimeline.tsx` | 路由、目标树、工具与运行指标可视化 |
| `frontend/src/components/documents/DocumentUploader.tsx` | 上传区 + 实时进度卡片 |
| `frontend/src/components/chat/ChatInput.tsx` | 输入框 (有 indexed 文档才启用) |

## 数据库

SQLite 文件: `backend/data/app.db`  
FAISS 索引: `backend/data/faiss/rag_index.faiss` + `id_map.pkl`

```bash
# 查看数据库
sqlite3 backend/data/app.db
.tables    # chunks, conversations, documents, messages, settings
.schema    # 查看表结构
```

**状态流转**: `uploaded → parsing → chunking → embedding → storing → indexed` (或 `error`)

## 测试

```bash
# 后端启动
cd backend && python run.py

# 前端启动
cd frontend && npm run dev

# 后端完整单元测试
cd backend && .venv/Scripts/python -m unittest discover -s tests -v

# 前端类型检查与生产构建
cd frontend && npm run build

# 上传测试（含 SSE 进度）
cd backend && python _test_upload.py <文件路径>

# 数据库查询
sqlite3 -header -column backend/data/app.db "SELECT id, original_name, status FROM documents;"
```

## 已知待处理

1. 前端 OpenAI/Anthropic 模型下拉框未渲染（只显示 API Key 输入）
2. `_test_upload.py` 和 `_test_ocr.png` 是测试文件，未加入版本控制
3. `indexer.py` 中 `duration_secs` 字段从未写入
4. 删除文档后 FAISS 向量通过完全重建索引实现（效率低）
