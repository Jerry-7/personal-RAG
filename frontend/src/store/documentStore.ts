/**
 * 文档管理状态 (Zustand)
 *
 * 管理上传文档列表和上传进度。
 */

import { create } from 'zustand';
import type { DocumentItem, ProcessingTask } from '../types/document';

interface DocumentState {
  /** 已上传文档列表 */
  documents: DocumentItem[];
  /** 是否正在加载 */
  isLoading: boolean;
  /** 是否正在上传（文件传输阶段） */
  isUploading: boolean;
  /** 上传进度 0-100 */
  uploadProgress: number;
  /** 上传错误信息 */
  uploadError: string | null;
  /** 正在后台处理的任务 */
  processingQueue: ProcessingTask[];

  // Actions
  setDocuments: (docs: DocumentItem[]) => void;
  addDocument: (doc: DocumentItem) => void;
  removeDocument: (id: string) => void;
  updateDocumentStatus: (id: string, status: DocumentItem['status']) => void;
  setLoading: (loading: boolean) => void;
  setUploading: (uploading: boolean) => void;
  setUploadProgress: (progress: number) => void;
  setUploadError: (error: string | null) => void;
  /** 添加/更新处理中任务 */
  upsertProcessingTask: (task: ProcessingTask) => void;
  /** 移除处理中任务 */
  removeProcessingTask: (docId: string) => void;
}

export const useDocumentStore = create<DocumentState>((set) => ({
  documents: [],
  isLoading: false,
  isUploading: false,
  uploadProgress: 0,
  uploadError: null,
  processingQueue: [],

  setDocuments: (docs) => set({ documents: docs }),

  addDocument: (doc) =>
    set((s) => ({ documents: [doc, ...s.documents] })),

  removeDocument: (id) =>
    set((s) => ({
      documents: s.documents.filter((d) => d.id !== id),
      processingQueue: s.processingQueue.filter((t) => t.docId !== id),
    })),

  updateDocumentStatus: (id, status) =>
    set((s) => ({
      documents: s.documents.map((d) => (d.id === id ? { ...d, status } : d)),
    })),

  setLoading: (loading) => set({ isLoading: loading }),

  setUploading: (uploading) => set({ isUploading: uploading }),

  setUploadProgress: (progress) => set({ uploadProgress: progress }),

  setUploadError: (error) => set({ uploadError: error }),

  upsertProcessingTask: (task) =>
    set((s) => {
      const idx = s.processingQueue.findIndex((t) => t.docId === task.docId);
      if (idx >= 0) {
        const updated = [...s.processingQueue];
        updated[idx] = task;
        return { processingQueue: updated };
      }
      return { processingQueue: [...s.processingQueue, task] };
    }),

  removeProcessingTask: (docId) =>
    set((s) => ({
      processingQueue: s.processingQueue.filter((t) => t.docId !== docId),
    })),
}));
