/**
 * 文档管理状态 (Zustand)
 *
 * 管理上传文档列表和上传进度。
 */

import { create } from 'zustand';
import type { DocumentItem } from '../types/document';

interface DocumentState {
  /** 已上传文档列表 */
  documents: DocumentItem[];
  /** 是否正在加载 */
  isLoading: boolean;
  /** 是否正在上传 */
  isUploading: boolean;
  /** 上传进度 0-100 */
  uploadProgress: number;
  /** 上传错误信息 */
  uploadError: string | null;

  // Actions
  setDocuments: (docs: DocumentItem[]) => void;
  addDocument: (doc: DocumentItem) => void;
  removeDocument: (id: string) => void;
  updateDocumentStatus: (id: string, status: DocumentItem['status']) => void;
  setLoading: (loading: boolean) => void;
  setUploading: (uploading: boolean) => void;
  setUploadProgress: (progress: number) => void;
  setUploadError: (error: string | null) => void;
}

export const useDocumentStore = create<DocumentState>((set) => ({
  documents: [],
  isLoading: false,
  isUploading: false,
  uploadProgress: 0,
  uploadError: null,

  setDocuments: (docs) => set({ documents: docs }),

  addDocument: (doc) =>
    set((s) => ({ documents: [doc, ...s.documents] })),

  removeDocument: (id) =>
    set((s) => ({ documents: s.documents.filter((d) => d.id !== id) })),

  updateDocumentStatus: (id, status) =>
    set((s) => ({
      documents: s.documents.map((d) => (d.id === id ? { ...d, status } : d)),
    })),

  setLoading: (loading) => set({ isLoading: loading }),

  setUploading: (uploading) => set({ isUploading: uploading }),

  setUploadProgress: (progress) => set({ uploadProgress: progress }),

  setUploadError: (error) => set({ uploadError: error }),
}));
