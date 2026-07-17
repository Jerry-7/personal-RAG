/**
 * 文档管理 API
 */

import client from './client';
import type {
  DocumentItem,
  UploadResponse,
  ProgressCallbacks,
} from '../types/document';

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
  const controller = new AbortController();

  fetch(`/api/documents/${docId}/progress`, { signal: controller.signal })
    .then(async (response) => {
      if (!response.ok) {
        callbacks.onError({ doc_id: docId, status: 'error', message: `HTTP ${response.status}` });
        return;
      }
      if (!response.body) {
        callbacks.onError({ doc_id: docId, status: 'error', message: '响应体为空' });
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          let eventType = '';
          for (const line of lines) {
            if (line.startsWith('event: ')) {
              eventType = line.slice(7).trim();
            } else if (line.startsWith('data: ')) {
              const dataStr = line.slice(6);
              try {
                const data = JSON.parse(dataStr);
                switch (eventType) {
                  case 'progress':
                    callbacks.onProgress(data);
                    break;
                  case 'done':
                    callbacks.onDone(data);
                    break;
                  case 'error':
                    callbacks.onError(data);
                    break;
                }
              } catch {
                // 跳过 JSON 解析失败的行
              }
            }
          }
        }
      } catch (err: unknown) {
        if (err instanceof Error && err.name !== 'AbortError') {
          callbacks.onError({ doc_id: docId, status: 'error', message: err.message });
        }
      }
    })
    .catch((err) => {
      if (err.name !== 'AbortError') {
        callbacks.onError({ doc_id: docId, status: 'error', message: err.message });
      }
    });

  return controller;
}

/** 删除文档 */
export async function deleteDocument(docId: string): Promise<{ document_id: string; chunks_deleted: number }> {
  const { data } = await client.delete(`/documents/${docId}`);
  return data;
}
