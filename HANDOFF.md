# Personal RAG — 对话交接文档

> 最后更新: 2026-07-18  
> 当前分支: `feature/agent`

## 项目概览

个人 RAG 系统，三栏布局：左侧文档管理 | 中间对话区 | 右侧引用面板。  
后端 FastAPI + SQLite + FAISS，前端 React + TypeScript + Zustand。

## 当前分支状态

| 分支 | 说明 |
|------|------|
| `master` | 经典 RAG 流水线（固定检索→生成） |
| `feature/agent` | **当前** — Agent 架构 + 异步上传 |

`feature/agent` 领先 `origin/feature/agent` 5 个未推送提交。

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

## 关键文件

| 文件 | 作用 |
|------|------|
| `backend/app/agent/loop.py` | ReAct Agent 主循环 + System Prompt |
| `backend/app/agent/tools.py` | ToolRegistry + `@skill` 装饰器 |
| `backend/app/agent/builtin_tools.py` | 3 个内置工具 (search/list_docs/read_chunk) |
| `backend/app/services/event_bus.py` | 内存 pub/sub (asyncio.Queue per doc_id) |
| `backend/app/services/task_manager.py` | Semaphore(10) 并发控制 |
| `backend/app/services/indexing_worker.py` | 后台索引胶水层 |
| `backend/app/services/indexer.py` | 索引流水线 (parse→chunk→embed→store) |
| `backend/app/db/vector_store.py` | FAISS 向量存储 (自动检测维度) |
| `backend/app/providers/ollama.py` | Ollama LLM + Embedding + Tool Calling |
| `backend/app/api/documents.py` | 上传 + SSE 进度端点 |
| `backend/app/api/chat.py` | 对话 SSE 端点 (Agent/经典双模式) |
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

# 上传测试（含 SSE 进度）
cd backend && python _test_upload.py <文件路径>

# 数据库查询
sqlite3 -header -column backend/data/app.db "SELECT id, original_name, status FROM documents;"
```

## 已知待处理

1. 前端 OpenAI/Anthropic 模型下拉框未渲染（只显示 API Key 输入）
2. `_test_upload.py` 和 `_test_ocr.png` 是测试文件，未加入版本控制
3. Agent 模式下前端 `tool_call`/`tool_result` 事件的 UI 展示不完整
4. `indexer.py` 中 `duration_secs` 字段从未写入
5. 删除文档后 FAISS 向量通过完全重建索引实现（效率低）
