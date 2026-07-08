/**
 * 引用来源数据类型定义
 */

/** 来源文档信息 */
export interface SourceDocumentInfo {
  id: string;
  filename: string;
  original_name: string;
  file_type: string;
  page_count?: number;
  duration_secs?: number;
  created_at?: string;
}

/** 来源分块信息 */
export interface SourceChunkInfo {
  id: string;
  text: string;
  page_number?: number;
  chunk_index: number;
  start_timestamp?: number;
  end_timestamp?: number;
  source_type: 'text' | 'video' | 'audio';
}

/** 相邻分块（上下文） */
export interface NeighborChunk {
  text: string;
  chunk_index: number;
  page_number?: number;
}

/** 来源完整响应 */
export interface SourceResponse {
  document: SourceDocumentInfo;
  chunk: SourceChunkInfo;
  surrounding_chunks: NeighborChunk[];
}
