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

/** SSE 进度事件 */
export interface ProgressEvent {
  doc_id: string;
  status: DocumentStatus;
  message: string;
}

/** SSE 完成事件 */
export interface ProgressDoneEvent {
  doc_id: string;
  status: 'indexed';
  chunk_count?: number;
}

/** SSE 错误事件 */
export interface ProgressErrorEvent {
  doc_id: string;
  status: 'error';
  message: string;
}

/** SSE 进度流回调 */
export interface ProgressCallbacks {
  onProgress: (event: ProgressEvent) => void;
  onDone: (event: ProgressDoneEvent) => void;
  onError: (event: ProgressErrorEvent) => void;
}

/** 正在处理的任务 */
export interface ProcessingTask {
  docId: string;
  filename: string;
  status: DocumentStatus;
  message: string;
}
