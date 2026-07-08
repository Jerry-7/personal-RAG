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

export interface AppSettings {
  llm_provider: string;
  embedding_provider: string;
  ollama: OllamaConfig;
  openai: OpenAIConfig;
  anthropic: AnthropicConfig;
  rag: RAGConfig;
}

export interface AvailableModels {
  ollama_llm_models: string[];
  ollama_embed_models: string[];
  openai_llm_models: string[];
  openai_embed_models: string[];
  anthropic_models: string[];
}
