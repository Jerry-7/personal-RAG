# Personal RAG - Agent 工具注册表
"""
工具注册表模块

提供 @skill 装饰器注册自定义工具，管理工具元数据和执行。
内置工具将现有 RAG 检索包装为 Agent 可调用的 tool。

工具定义遵循 OpenAI function calling 格式:
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": "在已上传文档中搜索相关内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"}
                },
                "required": ["query"]
            }
        }
    }
"""

import inspect
import logging
from collections.abc import Callable
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 工具执行返回值的最大字符数（超出截断）
MAX_TOOL_RESULT_LENGTH = 3000


class ToolDef:
    """
    单个工具的定义。

    Attributes:
        name: 工具唯一名称
        description: 工具描述（LLM 用来判断何时调用）
        parameters: OpenAI 格式的参数 schema
        handler: 异步处理函数
        source: 来源标识 ("builtin" | "skill" | "mcp")
    """

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: Callable,
        source: str = "builtin",
    ) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler
        self.source = source

    def to_openai_format(self) -> dict[str, Any]:
        """导出为 OpenAI tool definition 格式。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """
    工具注册表。

    管理所有 Agent 可用的工具，支持三种来源：
    - builtin: 内置 RAG 工具
    - skill: 用户通过 @skill 装饰器注册的自定义工具
    - mcp: MCP server 提供的工具

    提供注册、查询、导出和执行功能。
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolDef] = {}

    # ── 注册 ──────────────────────────────────────────────────

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: Callable,
        source: str = "skill",
    ) -> None:
        """
        注册一个工具。

        Args:
            name: 工具唯一名称
            description: 工具描述
            parameters: OpenAI 格式的参数 schema
            handler: async callable 处理函数
            source: 来源标识
        """
        self._tools[name] = ToolDef(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
            source=source,
        )
        logger.info("Tool registered: %s (source=%s)", name, source)

    def skill(self, name: str, description: str):
        """
        装饰器：将 async 函数注册为 Agent 工具。

        自动从函数签名提取 parameters schema。

        Usage:
            @tool_registry.skill(name="my_tool", description="Does something")
            async def my_tool(query: str, limit: int = 10) -> str:
                ...

        Args:
            name: 工具名称
            description: 工具描述
        """
        def decorator(func):
            params = _func_to_parameters(func)
            self.register(name, description, params, func, source="skill")
            return func
        return decorator

    # ── 查询 ──────────────────────────────────────────────────

    def get(self, name: str) -> Optional[ToolDef]:
        """按名称获取工具定义。"""
        return self._tools.get(name)

    def list_all(self) -> list[ToolDef]:
        """列出所有已注册工具。"""
        return list(self._tools.values())

    def to_openai_format(self) -> list[dict[str, Any]]:
        """将所有工具导出为 OpenAI tool definitions 格式。"""
        return [t.to_openai_format() for t in self._tools.values()]

    # ── 执行 ──────────────────────────────────────────────────

    async def execute(self, name: str, arguments: dict[str, Any]) -> str:
        """
        执行指定工具并返回结果字符串。

        Args:
            name: 工具名称
            arguments: 工具参数

        Returns:
            工具执行结果（字符串格式，供 LLM 消费）

        Raises:
            ValueError: 工具不存在
            RuntimeError: 工具执行失败
        """
        tool = self._tools.get(name)
        if not tool:
            raise ValueError(f"工具不存在: {name}")

        try:
            result = await tool.handler(**arguments)
            result_str = str(result)
            # 截断过长结果，避免撑爆 context
            if len(result_str) > MAX_TOOL_RESULT_LENGTH:
                result_str = result_str[:MAX_TOOL_RESULT_LENGTH] + "...(截断)"
            return result_str
        except Exception as e:
            logger.exception("Tool execution failed: %s", name)
            return f"工具执行失败: {str(e)}"


def _func_to_parameters(func: Callable) -> dict[str, Any]:
    """
    从函数签名推断 OpenAI parameters schema。

    将 Python 类型注解映射为 JSON Schema type:
        str → "string", int → "integer", float → "number",
        bool → "boolean", list → "array"

    Args:
        func: 异步函数

    Returns:
        {"type": "object", "properties": {...}, "required": [...]}
    """
    sig = inspect.signature(func)
    properties = {}
    required = []

    type_map = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        list: "array",
        dict: "object",
    }

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue

        annotation = param.annotation
        json_type = "string"
        if annotation is not inspect.Parameter.empty:
            json_type = type_map.get(annotation, "string")

        prop = {"type": json_type}

        # 从 docstring 提取参数描述（如果有的话）
        if param.default is not inspect.Parameter.empty:
            prop["default"] = param.default
        else:
            required.append(param_name)

        properties[param_name] = prop

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


# ── 全局单例 ──────────────────────────────────────────────────

tool_registry = ToolRegistry()
