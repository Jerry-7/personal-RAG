/**
 * 设置/配置数据类型定义
 */

export interface OllamaConfig {
  base_url: string;
  llm_model: string;
  embedding_model: string;
}

export interface OpenAIConfig {
  api_key?: string;
  llm_model: string;
  embedding_model: string;
}

export interface AnthropicConfig {
  api_key?: string;
  llm_model: string;
}

export interface RAGConfig {
  chunk_size: number;
  chunk_overlap: number;
  retrieval_top_k: number;
  final_top_k: number;
}

export interface WebResearchConfig {
  searxng_url: string;
  language: string;
  safe_search: number;
  fetch_timeout_secs: number;
  page_budget: number;
  snapshot_retention_days: number;
}

export interface AppSettings {
  llm_provider: string;
  embedding_provider: string;
  ollama: OllamaConfig;
  openai: OpenAIConfig;
  anthropic: AnthropicConfig;
  rag: RAGConfig;
  web: WebResearchConfig;
}

export interface AvailableModels {
  ollama_llm_models: string[];
  ollama_embed_models: string[];
  openai_llm_models: string[];
  openai_embed_models: string[];
  anthropic_models: string[];
}
