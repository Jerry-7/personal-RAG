"""Read-only web research tools."""

from app.agent.context import AgentRunContext
from app.agent.tools import tool_registry
from app.services.web_research import web_research_service
from app.services.web_search import search_provider


async def _web_search(
    query: str,
    language: str = "all",
    time_range: str = "",
    max_results: int = 5,
    *,
    context: AgentRunContext,
) -> str:
    context.web_search_performed = True
    results = await search_provider.search(
        query,
        language=language,
        time_range=time_range or None,
        max_results=max_results,
    )
    if not results:
        return "网页搜索没有返回结果。"
    lines = [
        "网页搜索候选（不可直接引用；必须先用 fetch_web_page 读取正文，"
        "并使用该工具返回的 [N]）:"
    ]
    for index, result in enumerate(results, start=1):
        lines.append(
            f"[W{index}](<{result.url}>) 候选链接（非正式引用）: {result.title}\n"
            f"搜索摘要（非证据）: {result.snippet[:500]}"
        )
    return "\n\n".join(lines)


async def _fetch_web_page(
    url: str,
    objective: str,
    *,
    context: AgentRunContext,
) -> str:
    page, _, citation = await web_research_service.fetch_and_store(context, url, objective)
    excerpt = web_research_service._excerpt(page.content, objective)
    return f"[{citation}] {page.title}\nURL: {page.url}\n\n{excerpt}"


async def _crawl_website(
    start_url: str,
    objective: str,
    *,
    context: AgentRunContext,
) -> str:
    pages = await web_research_service.crawl(context, start_url, objective)
    if not pages:
        return "站内研究没有读取到页面。"
    parts: list[str] = []
    for page, _, citation, depth in pages:
        excerpt = web_research_service._excerpt(page.content, objective, limit=1800)
        parts.append(f"[{citation}] {page.title} (深度 {depth})\nURL: {page.url}\n{excerpt}")
    return "\n\n".join(parts)


def register_research_tools() -> None:
    tool_registry.register(
        "web_search",
        "使用自托管搜索引擎查找网页候选。搜索摘要不能替代正文证据，之后应调用 fetch_web_page。",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索查询"},
                "language": {"type": "string", "description": "语言代码，默认 all"},
                "time_range": {"type": "string", "enum": ["", "day", "month", "year"]},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            "required": ["query"],
        },
        _web_search,
        source="web",
    )
    tool_registry.register(
        "fetch_web_page",
        "读取一个公开 HTML 或 PDF 页面正文并注册可复核引用。",
        {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "objective": {"type": "string", "description": "希望从页面中寻找的信息"},
            },
            "required": ["url", "objective"],
        },
        _fetch_web_page,
        source="web",
    )
    tool_registry.register(
        "crawl_website",
        "在同一域名内按预算进行受限递归研究，最多 8 页、深度 2。",
        {
            "type": "object",
            "properties": {
                "start_url": {"type": "string"},
                "objective": {"type": "string"},
            },
            "required": ["start_url", "objective"],
        },
        _crawl_website,
        source="web",
    )


register_research_tools()
