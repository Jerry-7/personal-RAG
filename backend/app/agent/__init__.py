# Personal RAG - Agent 模块
"""
Agent 模块

将 RAG 系统升级为 LLM 自主决策的 Agent 架构。
核心组件:
- ToolRegistry: 工具注册表，支持 @skill 装饰器
- AgentLoop: ReAct 模式的 think→act→observe 循环
"""

from app.agent.tools import ToolRegistry, tool_registry
from app.agent.loop import AgentLoop
from app.agent import builtin_tools  # noqa: F401 — 注册内置工具

__all__ = ["ToolRegistry", "tool_registry", "AgentLoop"]
