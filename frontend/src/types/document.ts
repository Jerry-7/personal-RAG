/**
 * 文档数据类型定义
 */

/** 文档状态 */
export type DocumentStatus = 'uploaded' | 'parsing' | 'chunking' | 'indexing' | 'indexed' | 'error';

/** 文档列表项 */
export interface DocumentItem {
  id: string;
  filename: string;
  original_name: string;
  file_type: string;
  file_size_bytes: number;
  status: DocumentStatus;
  chunk_count: number;
  page_count?: number;
  duration_secs?: number;
  error_message?: string;
  created_at: string;
  updated_at: string;
}

/** 上传响应 */
export interface UploadResponse {
  id: string;
  filename: string;
  original_name: string;
  file_type: string;
  status: string;
  created_at: string;
}
