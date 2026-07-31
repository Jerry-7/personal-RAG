/**
 * 文档管理 API
 */

import client from './client';
import type {
  DocumentItem,
  UploadResponse,
  ProgressCallbacks,
} from '../types/document';
import { streamSSE } from './sse';

/** 上传文件（立即返回，后台异步索引） */
export async function uploadDocument(file: File): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append('file', file);
  const { data } = await client.post<UploadResponse>('/documents/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 60000, // 60s 仅用于文件传输，不再等待索引
  });
  return data;
}

/** 获取文档列表 */
export async function listDocuments(params?: {
  status?: string;
  file_type?: string;
}): Promise<{ documents: DocumentItem[]; total: number }> {
  const { data } = await client.get('/documents', { params });
  return data;
}

/**
 * SSE 流式监听文档索引进度
 *
 * 复用与 chat.ts 相同的 fetch + ReadableStream 模式。
 * 返回 AbortController 用于取消连接。
 */
export function streamDocumentProgress(
  docId: string,
  callbacks: ProgressCallbacks
): AbortController {
  return streamSSE(`/api/documents/${docId}/progress`, {
    onMessage: ({ event, data }) => {
      switch (event) {
                  case 'progress':
                    callbacks.onProgress(data as Parameters<typeof callbacks.onProgress>[0]);
                    break;
                  case 'done':
                    callbacks.onDone(data as Parameters<typeof callbacks.onDone>[0]);
                    break;
                  case 'error':
                    callbacks.onError(data as Parameters<typeof callbacks.onError>[0]);
                    break;
      }
    },
    onError: (error) => callbacks.onError({ doc_id: docId, status: 'error', message: error.message }),
  });
}

/** 删除文档 */
export async function deleteDocument(docId: string): Promise<{ document_id: string; chunks_deleted: number }> {
  const { data } = await client.delete(`/documents/${docId}`);
  return data;
}
