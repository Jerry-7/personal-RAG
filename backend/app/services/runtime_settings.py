"""Apply persisted settings to live service instances."""

import json
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings


GROUP_KEYS = {
    "ollama": {
        "base_url": "ollama_base_url",
        "llm_model": "ollama_llm_model",
        "embedding_model": "ollama_embedding_model",
    },
    "openai": {
        "api_key": "openai_api_key",
        "llm_model": "openai_llm_model",
        "embedding_model": "openai_embedding_model",
    },
    "anthropic": {
        "api_key": "anthropic_api_key",
        "llm_model": "anthropic_llm_model",
    },
    "rag": {
        "chunk_size": "chunk_size",
        "chunk_overlap": "chunk_overlap",
        "retrieval_top_k": "retrieval_top_k",
        "final_top_k": "final_top_k",
    },
    "web": {
        "searxng_url": "searxng_base_url",
        "language": "web_search_language",
        "safe_search": "web_safe_search",
        "fetch_timeout_secs": "web_fetch_timeout_secs",
        "page_budget": "web_page_budget",
        "snapshot_retention_days": "web_snapshot_retention_days",
    },
}


def flatten_updates(updates: dict[str, Any]) -> dict[str, Any]:
    """Convert the API's nested settings payload to canonical setting keys."""
    flattened: dict[str, Any] = {}
    for key, value in updates.items():
        if isinstance(value, dict):
            mapping = GROUP_KEYS.get(key, {})
            for sub_key, sub_value in value.items():
                canonical = mapping.get(sub_key)
                if canonical and sub_value is not None:
                    flattened[canonical] = sub_value
        elif hasattr(settings, key) and value is not None:
            flattened[key] = value
    return flattened


def embedding_signature(overrides: dict[str, Any] | None = None) -> tuple[str, str]:
    """Return the provider/model pair that defines vector compatibility."""
    values = overrides or {}
    provider = str(values.get("embedding_provider", settings.embedding_provider))
    if provider == "openai":
        model = str(values.get("openai_embedding_model", settings.openai_embedding_model))
    else:
        model = str(values.get("ollama_embedding_model", settings.ollama_embedding_model))
    return provider, model


def apply_runtime_settings(values: dict[str, Any]) -> None:
    """Update settings and invalidate services that cache derived objects."""
    for key, value in values.items():
        if hasattr(settings, key):
            setattr(settings, key, value)

    from app.services.chunker import chunker
    from app.services.embedder import embedding_service
    from app.services.generator import generator
    from app.services.web_search import search_provider

    chunker.chunk_size = int(settings.chunk_size)
    chunker.chunk_overlap = int(settings.chunk_overlap)
    embedding_service.reset(settings.embedding_provider)
    generator.reset(settings.llm_provider)
    if hasattr(search_provider, "base_url"):
        search_provider.base_url = settings.searxng_base_url.rstrip("/")


def load_persisted_settings(db: Session) -> dict[str, Any]:
    """Load canonical values from SQLite and apply them to live services."""
    from app.db.models import Setting

    values = {row.key: json.loads(row.value_json) for row in db.query(Setting).all()}
    apply_runtime_settings(values)
    return values
