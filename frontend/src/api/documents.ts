/**
 * 文档管理 API
 */

import client from './client';
import type { DocumentItem, UploadResponse } from '../types/document';

/** 上传文件 */
export async function uploadDocument(file: File): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append('file', file);
  const { data } = await client.post<UploadResponse>('/documents/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 300000, // 5 min for large files
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

/** 删除文档 */
export async function deleteDocument(docId: string): Promise<{ document_id: string; chunks_deleted: number }> {
  const { data } = await client.delete(`/documents/${docId}`);
  return data;
}
