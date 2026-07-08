#!/usr/bin/env python3
"""
Personal RAG - 后端启动脚本

用法:
    python run.py              # 默认端口 8000
    python run.py --port 8080  # 指定端口
    python run.py --reload     # 开发模式热重载
"""

import sys

import uvicorn


def main():
    """启动 uvicorn ASGI 服务器。"""
    host = "127.0.0.1"
    port = 8000
    reload = "--reload" in sys.argv or "--dev" in sys.argv

    # 解析 --port 参数
    for i, arg in enumerate(sys.argv):
        if arg == "--port" and i + 1 < len(sys.argv):
            port = int(sys.argv[i + 1])

    print(f"""
╔══════════════════════════════════════════════════════════╗
║              Personal RAG - Backend Server               ║
╠══════════════════════════════════════════════════════════╣
║  API 地址:  http://{host}:{port}                          ║
║  API 文档:  http://{host}:{port}/docs                     ║
║  OpenAPI:   http://{host}:{port}/openapi.json             ║
║  Ollama:    http://localhost:11434                       ║
╚══════════════════════════════════════════════════════════╝
""")

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
