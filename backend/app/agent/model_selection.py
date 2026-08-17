"""Resolve the concrete model assigned to an Agent profile."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agent.routing import AgentProfile
from app.config import settings


@dataclass(frozen=True)
class AgentModelSelection:
    provider: str
    model: str
    model_key: str
    uses_default: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_provider": self.provider,
            "model_name": self.model,
            "model_key": self.model_key,
            "model_uses_default": self.uses_default,
        }


def _default_model(provider: str, config: Any) -> str:
    attribute = {
        "ollama": "ollama_llm_model",
        "openai": "openai_llm_model",
        "anthropic": "anthropic_llm_model",
    }.get(provider)
    if attribute is None:
        raise ValueError(f"Unsupported LLM provider: {provider}")
    return str(getattr(config, attribute)).strip()


def select_agent_model(
    profile: AgentProfile,
    *,
    config: Any = settings,
) -> AgentModelSelection:
    """Map a profile's model key to a configured model with explicit fallback."""
    model_key = profile.model_key or profile.tier
    if model_key not in {"fast", "standard", "expert"}:
        raise ValueError(f"Unsupported Agent model key: {model_key}")
    provider = str(config.llm_provider).strip().lower()
    configured = str(getattr(config, f"agent_{model_key}_model", None) or "").strip()
    return AgentModelSelection(
        provider=provider,
        model=configured or _default_model(provider, config),
        model_key=model_key,
        uses_default=not bool(configured),
    )


def select_fast_model(config: Any = settings) -> AgentModelSelection:
    """固定 fast 档模型，供子 Agent 任务统一使用。

    压缩、目标语义提取、路由分类等"难度不高但费 token、吃上下文"的活
    全部走轻量档模型，与主 Agent 的推理模型解耦。未配置 `agent_fast_model`
    时回退到默认 LLM 模型（此时各档同模型，行为与以前一致）。
    """
    from app.agent.routing import build_default_agent_registry

    return select_agent_model(
        build_default_agent_registry().require("fast_general"),
        config=config,
    )
