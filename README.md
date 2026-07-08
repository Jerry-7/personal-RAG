# Personal RAG

个人 RAG（检索增强生成）系统 — 支持多格式文件上传、本地 Ollama 模型优先、引用来源追踪。

## 目录

- [功能概览](#功能概览)
- [技术架构](#技术架构)
- [快速开始](#快速开始)
- [项目结构](#项目结构)
- [RAG 数据流](#rag-数据流)
- [已完成功能](#已完成功能)
- [未来规划](#未来规划)
- [API 文档](#api-文档)

---

## 功能概览

### 核心能力

| 功能 | 说明 |
|------|------|
| **多格式上传** | PDF、Word (.docx)、TXT、Markdown、CSV、JSON、图片 (OCR)、视频/音频 (转录) |
| **本地模型优先** | Ollama 本地部署 LLM + Embedding，GPU 加速，零数据外泄 |
| **第三方 API** | 可选配置 OpenAI / Anthropic API Key 作为 fallback |
| **RAG 问答** | 上传文档 → 自动索引 → 提问时检索相关段落 → LLM 结合上下文生成回答 |
| **流式输出** | SSE 逐 token 推送，打字机效果实时渲染 |
| **引用追踪** | 回答中标记 `[1]` `[2]` 引用来源，点击在右侧栏查看原文高亮 |
| **视频支持** | 上传视频 → Whisper 转录 → 引用时标注时间戳 → 视频播放器跳转 |

### 界面布局

```
┌──────────┬──────────────────────────┬────────────┐
│  左侧栏   │       中央聊天区          │  右侧引用栏  │
│          │                          │  (可收起)   │
│ 上传区域  │  AI: 根据文档，答案是...  │            │
│ 拖拽/点击 │  [1] X报告 第4页 [2]...  │  来源 #1    │
│          │                          │  ┌───────┐ │
│ 文档列表  │  ─────────────────────── │  │高亮文本│ │
│ 📄 report │  输入框            [发送] │  └───────┘ │
│ 🎬 video  │                          │  前后上下文  │
│ 🖼 photo  │                          │            │
└──────────┴──────────────────────────┴────────────┘
```

---

## 技术架构

### 技术栈

| 层级 | 技术 | 选型理由 |
|------|------|----------|
| 后端框架 | **Python FastAPI** | 原生 async/SSE/WebSocket, Pydantic 验证, 自动 API 文档 |
| 前端框架 | **React 18 + TypeScript + Vite** | 复杂交互 UI (引用侧栏), HMR 开发体验 |
| CSS | **TailwindCSS v4** | 原子化 CSS, 暗色模式支持 |
| 状态管理 | **Zustand** | 轻量 (~1KB), 4 个独立 store |
| 向量存储 | **FAISS** (IndexFlatIP) + **SQLite** | FAISS 高性能余弦搜索, SQLite 存元数据; 无需额外服务 |
| 关系数据库 | **SQLite + SQLAlchemy ORM** | 零配置, 5 张表管理文档/对话/设置 |
| PDF 解析 | **PyMuPDF** (fitz) | 原生 UTF-8, 10x 快于 pdfplumber, 中文支持 |
| Word 解析 | **python-docx** | 标准库, 支持段落和表格 |
| 文本分块 | **递归字符分割** (中文感知) | 分隔符: `\n\n → \n → 。→ ！→ ？→ . → ! → ? → 空格` |
| 语音转录 | **faster-whisper** | CTranslate2 后端, INT8 量化, GPU 加速 |
| OCR | **Tesseract** / **PaddleOCR** | 自动回退, PaddleOCR 中文 95%+ 准确率 |
| LLM Provider | **Ollama** (qwen2.5:14b) | 本地 GPU 推理, 中文能力强 |
| 云 LLM (可选) | **OpenAI** (GPT-4o) / **Anthropic** (Claude) | API Key 配置后启用 |
| Embedding | **Ollama** (nomic-embed-text, 768维) | 本地免费, 多语言 |
| 流式通信 | **SSE** (Server-Sent Events) | HTTP 原生, 自动重连, 支持取消 |
| 图标 | **lucide-react** | Tree-shakeable, 按需导入 |

### 架构图

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend (React + Vite)                  │
│  ┌──────────┐  ┌──────────────┐  ┌────────────────────┐    │
│  │ Upload   │  │  Chat View   │  │  Citation Sidebar  │    │
│  │ (drag/drop)│  │ (SSE stream) │  │  (highlight/video) │    │
│  └────┬─────┘  └──────┬───────┘  └─────────┬──────────┘    │
└───────┼────────────────┼────────────────────┼───────────────┘
        │ REST           │ SSE                │ REST
        ▼                ▼                    ▼
┌─────────────────────────────────────────────────────────────┐
│                  Backend (FastAPI + Uvicorn)                 │
│                                                             │
│  ┌──────────┐  ┌───────────┐  ┌────────────┐               │
│  │ Parsers  │  │ Retriever │  │  Generator  │              │
│  │ PDF/DOCX │  │ FAISS     │  │  RAG Prompt │              │
│  │ TXT/IMG  │  │ search    │  │  + LLM call │              │
│  │ Video    │  │ +SQLite   │  │  +Citation  │              │
│  └────┬─────┘  └─────┬─────┘  └──────┬─────┘               │
│       │              │               │                      │
│  ┌────┴──────────────┴───────────────┴────┐                 │
│  │           Provider 抽象层               │                │
│  │  Ollama (本地) │ OpenAI │ Anthropic    │                 │
│  └────────────────────────────────────────┘                 │
└─────────────────────────────────────────────────────────────┘
        │                │                   │
        ▼                ▼                   ▼
┌──────────────┐  ┌──────────┐  ┌──────────────────┐
│  FAISS Index │  │  SQLite  │  │  Ollama Server   │
│  (向量搜索)   │  │  (元数据) │  │  (GPU 本地推理)    │
└──────────────┘  └──────────┘  └──────────────────┘
```

---

## 快速开始

### 环境要求

- **Python** 3.13+
- **Node.js** 22+
- **Ollama** (已部署并运行)
- **Tesseract** (可选, 用于图片 OCR)
- **ffmpeg** (可选, 用于视频转录时的音频提取)

### 1. 确保 Ollama 运行并拉取模型

```bash
ollama serve                          # 启动 Ollama 服务
ollama pull nomic-embed-text          # Embedding 模型 (~274MB)
ollama pull qwen2.5:14b               # LLM 模型 (推荐中文, ~8.5GB)
# 或使用更小的模型:
ollama pull qwen2.5:7b                # LLM 模型 (~4.4GB)
```

### 2. 安装 Python 依赖

```bash
cd backend
python -m venv .venv                  # 创建虚拟环境
.venv\Scripts\activate                # Windows 激活
# 或: source .venv/bin/activate      # Linux/Mac

pip install -r requirements.txt
```

### 3. 启动后端

```bash
python run.py                         # http://localhost:8000
# python run.py --reload              # 开发模式 (热重载)
# python run.py --port 8080           # 自定义端口
```

### 4. 安装前端依赖并启动

```bash
cd frontend
npm install
npm run dev                           # http://localhost:5173
```

### 5. 开始使用

1. 打开浏览器访问 `http://localhost:5173`
2. 在左侧上传 PDF/Word/视频文件
3. 等待文件状态变为 **"已就绪"**
4. 在聊天框输入问题, 按 Enter 发送
5. 点击回答中的 `[1]` `[2]` 标记查看来源

### 可选: 安装 OCR 支持

```bash
# Tesseract (英文为主, 安装简单)
# 1. 下载安装: https://github.com/UB-Mannheim/tesseract/wiki
# 2. pip install pytesseract

# PaddleOCR (中英文混合, 中文准确率 95%+)
pip install paddlepaddle paddleocr
```

---

## 项目结构

```
personal-rag/
│
├── README.md                           # 本文件
├── .gitignore                          # Git 忽略规则
│
├── backend/                            # Python FastAPI 后端
│   ├── .env                            # 环境变量 (Ollama URL, API Keys)
│   ├── .gitignore
│   ├── requirements.txt                # Python 依赖清单
│   ├── run.py                          # uvicorn 启动入口
│   │
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                     # FastAPI 应用创建, CORS, 生命周期
│   │   ├── config.py                   # pydantic-settings 配置管理
│   │   ├── dependencies.py             # FastAPI 依赖注入
│   │   │
│   │   ├── api/                        # ── REST API 路由层 ──
│   │   │   ├── router.py               # 路由聚合器 (/api/*)
│   │   │   ├── documents.py            # 文件上传 / 列表 / 删除
│   │   │   ├── chat.py                 # SSE 流式 RAG 问答 + 对话历史
│   │   │   ├── sources.py              # 引用来源内容查询
│   │   │   ├── models.py               # 可用模型列表 (Ollama/API)
│   │   │   └── settings.py             # 设置读取 / 更新
│   │   │
│   │   ├── schemas/                    # ── Pydantic 数据模型 ──
│   │   │   ├── document.py             # Document, Chunk, UploadResponse
│   │   │   ├── chat.py                 # ChatRequest, CitationData, MessageItem
│   │   │   ├── source.py               # SourceResponse (text/video)
│   │   │   └── settings.py             # ProviderConfig, RAGConfig
│   │   │
│   │   ├── services/                   # ── 核心业务服务层 ──
│   │   │   ├── parser/                # 文件解析器
│   │   │   │   ├── base.py            #   抽象基类 BaseParser + ParsedDocument
│   │   │   │   ├── registry.py        #   解析器注册表 (扩展名 → 解析器)
│   │   │   │   ├── pdf.py             #   PDF 解析 (PyMuPDF)
│   │   │   │   ├── docx.py            #   Word 解析 (python-docx)
│   │   │   │   ├── text.py            #   纯文本 (TXT/MD/CSV/JSON)
│   │   │   │   ├── image.py           #   图片 OCR (Tesseract/PaddleOCR 自动回退)
│   │   │   │   └── media.py           #   音视频转录 (faster-whisper + ffmpeg)
│   │   │   ├── chunker.py             # 中文感知递归文本分块
│   │   │   ├── embedder.py            # Embedding 批量生成 (Ollama/OpenAI)
│   │   │   ├── retriever.py           # FAISS 向量搜索 + SQLite 元数据填充
│   │   │   ├── generator.py           # RAG Prompt 构建 + LLM 调用编排
│   │   │   ├── citation.py            # 流式 [N] 引用实时解析
│   │   │   └── indexer.py             # 文档索引流水线编排
│   │   │
│   │   ├── providers/                 # ── LLM/Embedding Provider 抽象层 ──
│   │   │   ├── base.py                # 抽象接口 (LLMProvider, EmbeddingProvider)
│   │   │   ├── ollama.py              # Ollama 实现 (本地 GPU)
│   │   │   ├── openai_provider.py     # OpenAI 实现 (GPT-4o, text-embedding-3)
│   │   │   └── anthropic_provider.py  # Anthropic 实现 (Claude)
│   │   │
│   │   ├── db/                        # ── 数据持久化层 ──
│   │   │   ├── database.py            # SQLAlchemy 引擎 + 会话
│   │   │   ├── models.py              # ORM: Document, Chunk, Conversation,
│   │   │   │                          #       Message, Setting (5 张表)
│   │   │   └── vector_store.py        # FAISS IndexFlatIP + L2 归一化
│   │   │
│   │   └── utils/
│   │       └── file_utils.py          # MIME 检测, 文件哈希, 安全文件名
│   │
│   ├── tests/                          # 测试目录
│   └── data/                           # 运行时数据 (gitignored)
│       ├── uploads/                    # 上传的原始文件
│       ├── faiss/                      # FAISS 索引持久化
│       ├── transcripts/                # Whisper 转录缓存
│       └── app.db                      # SQLite 元数据库
│
├── frontend/                           # React + TypeScript 前端
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts                  # Vite 配置 + API 代理
│   │
│   └── src/
│       ├── main.tsx                    # React 入口
│       ├── App.tsx                     # 根组件 (三栏布局)
│       ├── index.css                   # Tailwind + 全局样式
│       │
│       ├── api/                        # ── HTTP API 客户端层 ──
│       │   ├── client.ts               # Axios 实例 (baseURL, 拦截器)
│       │   ├── documents.ts            # 文件上传/列表/删除
│       │   ├── chat.ts                 # SSE 流式查询 (fetch + ReadableStream)
│       │   ├── sources.ts              # 引用来源查询
│       │   └── settings.ts             # 设置读取/更新
│       │
│       ├── store/                      # ── Zustand 状态管理 ──
│       │   ├── chatStore.ts            # 对话消息, 流式状态, 引用
│       │   ├── documentStore.ts        # 文档列表, 上传进度
│       │   ├── sidebarStore.ts         # 引用侧栏开关, 激活引用
│       │   └── settingsStore.ts        # 设置状态, 弹窗开关
│       │
│       ├── components/                 # ── React 组件 ──
│       │   ├── layout/
│       │   │   ├── AppShell.tsx         # CSS Grid 三栏布局
│       │   │   └── Header.tsx           # 顶栏 (标题/模型/设置按钮)
│       │   │
│       │   ├── chat/
│       │   │   ├── ChatContainer.tsx    # 聊天区域容器
│       │   │   ├── MessageList.tsx      # 消息列表 (自动滚动)
│       │   │   ├── MessageBubble.tsx    # 消息气泡 (Markdown + 引用标记)
│       │   │   ├── ChatInput.tsx        # 输入框 (Enter 发送, 取消生成)
│       │   │   ├── CitationMark.tsx     # 内联 [1] [2] 可点击引用按钮
│       │   │   ├── StreamingText.tsx    # 打字机效果流式文本
│       │   │   └── EmptyChat.tsx        # 空聊天占位引导
│       │   │
│       │   ├── documents/
│       │   │   ├── DocumentUploader.tsx # 拖拽上传 + 文件选择
│       │   │   └── DocumentList.tsx     # 文档卡片列表 (状态/类型/删除)
│       │   │
│       │   ├── citations/              # ⭐ 核心特性: 引用系统
│       │   │   ├── CitationSidebar.tsx  # 右侧滑出引用面板
│       │   │   ├── TextCitation.tsx     # 文本来源 (高亮段落 + 上下文)
│       │   │   └── VideoCitation.tsx    # 视频来源 (播放器 + 时间戳)
│       │   │
│       │   └── settings/
│       │       └── SettingsModal.tsx    # 设置弹窗 (LLM/Embedding/RAG参数)
│       │
│       ├── hooks/                      # 自定义 Hooks
│       ├── types/                      # TypeScript 类型定义
│       │   ├── document.ts             # DocumentItem, UploadResponse
│       │   ├── chat.ts                 # MessageItem, CitationData, SSEEvent
│       │   ├── source.ts               # SourceResponse, SourceChunkInfo
│       │   └── settings.ts             # AppSettings, AvailableModels
│       └── vite-env.d.ts
│
└── scripts/                            # 辅助脚本
    ├── install.ps1                     # Windows 一键安装
    └── start.ps1                       # 启动前后端
```

---

## RAG 数据流

### 流程 1: 文件上传 → 索引

```
用户拖拽/选择文件
  │
  ▼
POST /api/documents/upload (multipart/form-data)
  │
  ├─ SHA-256 哈希去重, MIME 检测
  ├─ 保存到 data/uploads/
  ├─ 创建 Document 记录 (status=processing)
  │
  ▼
[异步索引流水线 - indexer.py]
  │
  ├─ Step 1: PARSE (解析)
  │   PDF → PyMuPDF (逐页提取 + 页码)
  │   DOCX → python-docx (段落 + 表格)
  │   TXT → 直接读取 (UTF-8/GBK 自动检测)
  │   图片 → Tesseract/PaddleOCR (OCR)
  │   视频 → ffmpeg 提取音频 → faster-whisper 转录
  │   Output: ParsedDocument {text, pages/segments, metadata}
  │
  ├─ Step 2: CHUNK (分块)
  │   递归字符分割: \n\n → \n → 。→ ！→ ？
  │   chunk_size=1000, overlap=200 (可配置)
  │   Output: [{text, metadata, chunk_index}, ...]
  │
  ├─ Step 3: EMBED (向量化)
  │   Batch (32) → Ollama nomic-embed-text → 768-dim
  │   Output: [[float x 768], ...]
  │
  ├─ Step 4: STORE (存储)
  │   FAISS IndexFlatIP: 向量 + ID 映射
  │   SQLite chunks 表: 文本 + 元数据
  │   Update: document.status = "indexed"
  │
  └─ SSE 通知前端: "索引完成"
```

### 流程 2: 提问 → 回答 (核心 RAG)

```
用户输入问题, 按 Enter
  │
  ▼
POST /api/chat/query {question, conversation_id}
  │
  ├─ Step 1: EMBED QUERY
  │   question → Ollama nomic-embed-text → 768-dim vector
  │
  ├─ Step 2: RETRIEVE
  │   FAISS.search(query_vec, k=8)
  │   → SQLite 填充元数据 (文件名/页码/时间戳)
  │   → 返回 top 4 最相关分块
  │
  ├─ Step 3: BUILD PROMPT
  │   [Source 1] (from report.pdf, page 4):
  │   ...检索到的段落文本...
  │
  │   [Source 2] (from interview.mp4, 03:24-03:45):
  │   ...转录文本...
  │
  ├─ Step 4: GENERATE (流式)
  │   LLM.chat_stream(prompt) → 逐 token 输出
  │   CitationParser.feed(token) → 实时检测 [N]
  │
  └─ SSE 推送前端:
      event: token     → "根据"
      event: token     → "文档"
      event: citation  → {index: 1}
      event: token     → "显示..."
      event: done      → {citations: [{doc_id, chunk_id, filename, page}]}
```

### 流程 3: 引用点击 → 来源展示

```
用户点击回答中的 [1] 按钮
  │
  ▼
GET /api/sources/{doc_id}/chunks/{chunk_id}
  │
  ├─ SQLite: 查询 Document + Chunk 记录
  ├─ FAISS: 获取相邻分块 (上下文)
  │
  ▼
右侧 CitationSidebar 滑出:
  │
  ├─ 文本来源 (source_type=text):
  │   ┌──────────────────────┐
  │   │ 📄 report.pdf 第4页   │  ← SourceCard
  │   ├──────────────────────┤
  │   │ ...上文 (灰色字)...    │
  │   │ ┌──────────────────┐ │
  │   │ │ 目标段落 (黄色高亮) │ │  ← HighlightedPassage
  │   │ └──────────────────┘ │
  │   │ ...下文 (灰色字)...    │
  │   └──────────────────────┘
  │
  └─ 视频来源 (source_type=video):
      ┌──────────────────────┐
      │ 🎬 interview.mp4     │  ← SourceCard
      ├──────────────────────┤
      │  ▶ 视频播放器         │  ← 自动 seek 到时间戳
      │  [03:24-03:45] [5:10]│  ← 可点击时间戳
      ├──────────────────────┤
      │ 转录文本 (高亮段落)    │
      └──────────────────────┘
```

---

## 已完成功能

### Phase 1-2: 后端核心 ✅

- [x] FastAPI 应用骨架, CORS, 生命周期管理
- [x] pydantic-settings 配置 (.env 支持)
- [x] SQLAlchemy ORM (5 张表: documents, chunks, conversations, messages, settings)
- [x] FAISS IndexFlatIP 向量存储 (L2 归一化, 余弦相似度)
- [x] Ollama Provider (LLM chat + Embedding)
- [x] OpenAI Provider (GPT-4o + text-embedding-3-small)
- [x] Anthropic Provider (Claude)
- [x] Provider 抽象层 (LLMProvider / EmbeddingProvider 接口)
- [x] 文件上传 / 列表 / 删除 API
- [x] 解析器注册表 (29 种文件格式)
- [x] PDF 解析 (PyMuPDF, 逐页, 中文)
- [x] Word 解析 (python-docx, 段落+表格)
- [x] 纯文本解析 (TXT/MD/CSV/JSON, UTF-8/GBK 自动检测)
- [x] 中文感知递归文本分块 (层级分隔符)
- [x] Ollama Embedding 批量生成
- [x] 文档索引流水线 (parse → chunk → embed → store)

### Phase 3: RAG 查询流程 ✅

- [x] FAISS 向量检索 + SQLite 元数据填充
- [x] RAG Prompt 构建 ([Source N] 格式)
- [x] 流式 LLM 生成 (Ollama/OpenAI/Anthropic)
- [x] 流式 [N] 引用实时解析 (CitationParser)
- [x] SSE 流式 Chat API (token/citation/done 事件)
- [x] 取消生成支持 (POST /api/chat/cancel)
- [x] 对话持久化 (Conversation + Message)
- [x] 对话历史 API
- [x] 来源查询 API (文本+上下文, 视频+时间戳)

### Phase 4: 前端核心 ✅

- [x] Vite + React 18 + TypeScript 脚手架
- [x] TailwindCSS v4 + 暗色模式
- [x] Zustand 状态管理 (4 个 store)
- [x] Axios API 客户端 + 拦截器
- [x] 三栏 CSS Grid 布局 (导航 / 聊天 / 引用)
- [x] Header (标题/模型指示/设置入口)
- [x] 拖拽文件上传 + 文件选择
- [x] 文档列表 (类型图标/状态徽章/删除)
- [x] 聊天消息列表 (Markdown 渲染)
- [x] 流式文本渲染 (打字机效果 + 闪烁光标)
- [x] 内联引用标记 [N] 按钮
- [x] 消息输入框 (Enter 发送, Shift+Enter 换行)
- [x] SSE 流消费 (fetch + ReadableStream)
- [x] 取消生成按钮

### Phase 5: 引用侧栏 (核心特性) ✅

- [x] CitationSidebar 右侧滑出面板
- [x] 文本来源展示 (高亮段落 + 上下文)
- [x] 视频来源展示 (播放器 + 时间戳跳转)
- [x] 来源文档元数据卡片
- [x] 多引用堆叠 + 标签切换

### Phase 6: 视频/OCR ✅

- [x] faster-whisper 集成 (CTranslate2, GPU 加速)
- [x] 视频文件音频提取 (ffmpeg)
- [x] 转录结果缓存 (避免重复转录)
- [x] 图片 OCR (Tesseract / PaddleOCR 自动回退)
- [x] 29 种文件格式支持

### Phase 7: 设置 & 配置 ✅

- [x] SettingsModal 三 Tab (LLM / Embedding / RAG 参数)
- [x] Ollama URL + 模型选择
- [x] OpenAI / Anthropic API Key 管理 (密码遮蔽)
- [x] 参数滑块 (chunk_size, overlap, top_k)
- [x] 可用模型列表 API

---

## 未来规划

### 短期 (v0.2)

- [ ] **用户认证**: 简单的密码保护 (单用户场景)
- [ ] **更好的检索排序**: 交叉编码器 (cross-encoder) 重排序 8→4
- [ ] **混合检索**: BM25 关键词 + 向量语义混合搜索
- [ ] **文档分块可视化**: 展示文档如何被切分，调试分块策略
- [ ] **批量上传**: 一次选择多个文件
- [ ] **上传进度**: WebSocket 实时推送索引进度百分比

### 中期 (v0.3)

- [ ] **语义分块**: 基于嵌入相似度断点的智能分块 (替换固定大小)
- [ ] **多轮对话优化**: 对话历史压缩 + 上下文窗口管理
- [ ] **文档标签/分类**: 按项目或主题组织文档
- [ ] **搜索功能**: 全文搜索 + 语义搜索已上传文档
- [ ] **导出对话**: 导出为 Markdown/PDF
- [ ] **RAG 质量评估**: 展示检索相关性分数, 引用准确率
- [ ] **深色模式完善**: 所有组件自适应

### 长期 (v1.0)

- [ ] **多用户支持**: 用户隔离, 每人独立的文档库
- [ ] **Agent 模式**: 多步推理 (ReAct), 工具调用 (计算器、搜索)
- [ ] **知识图谱**: 实体关系抽取, 图谱可视化
- [ ] **文档对比**: 并排对比两个文档的差异
- [ ] **定时索引**: 监控文件夹自动索引新文件
- [ ] **插件系统**: 自定义解析器/分块器/检索器
- [ ] **Docker 部署**: 一键 `docker compose up`
- [ ] **移动端适配**: 响应式设计, PWA 离线支持
- [ ] **多语言界面**: i18n (中/英)
- [ ] **性能优化**: 向量量化 (PQ/IVF), 索引分片
- [ ] **数据备份恢复**: 一键导出/导入所有数据

### 技术债务

- [ ] 后端单元测试 (pytest)
- [ ] 前端组件测试 (Vitest + Testing Library)
- [ ] E2E 测试 (Playwright)
- [ ] API 错误处理完善
- [ ] 日志系统 (结构体日志)
- [ ] 性能基准测试

---

## API 文档

启动后端后访问 `http://localhost:8000/docs` 查看 Swagger UI。

### 核心端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/health` | 健康检查 |
| `POST` | `/api/documents/upload` | 上传文件 (multipart/form-data) |
| `GET` | `/api/documents` | 文档列表 (?status=&file_type=) |
| `DELETE` | `/api/documents/{id}` | 删除文档 |
| `POST` | `/api/chat/query` | RAG 问答 (SSE 流) |
| `POST` | `/api/chat/cancel` | 取消生成 |
| `GET` | `/api/chat/history` | 对话历史列表 |
| `GET` | `/api/chat/conversations/{id}` | 对话消息详情 |
| `GET` | `/api/sources/{doc_id}/chunks/{chunk_id}` | 引用来源内容 |
| `GET` | `/api/models` | 可用模型列表 |
| `GET` | `/api/settings` | 当前设置 |
| `PUT` | `/api/settings` | 更新设置 |
| `GET` | `/files/{filename}` | 原始文件下载 |

### SSE 事件格式 (Chat)

```
event: token
data: {"text": "根据"}

event: citation
data: {"index": 1}

event: done
data: {"citations": [...], "conversation_id": "...", "message_id": "..."}

event: error
data: {"message": "错误描述"}
```
