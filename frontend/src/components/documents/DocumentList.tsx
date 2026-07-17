/**
 * 文档列表组件
 *
 * 显示所有已上传文档，含状态徽章和删除按钮。
 * 未完成索引的文档自动通过 SSE 获取实时状态更新。
 */

import { useEffect, useRef } from 'react';
import { FileText, File, Film, Music, Image, Trash2 } from 'lucide-react';
import { useDocumentStore } from '../../store/documentStore';
import { listDocuments, deleteDocument, streamDocumentProgress } from '../../api/documents';
import type { DocumentItem } from '../../types/document';

/** 文件类型图标映射 */
const typeIcons: Record<string, React.ComponentType<{ className?: string }>> = {
  pdf: FileText, docx: FileText, doc: FileText, txt: FileText, md: FileText, csv: FileText,
  mp4: Film, avi: Film, mkv: Film, mov: Film, webm: Film,
  mp3: Music, wav: Music, flac: Music, ogg: Music, m4a: Music, aac: Music,
  jpg: Image, jpeg: Image, png: Image, bmp: Image, tiff: Image, tif: Image, webp: Image,
};

/** 状态标签配置 */
const statusConfig: Record<string, { label: string; color: string }> = {
  uploaded: { label: '待处理', color: 'bg-gray-100 text-gray-600' },
  parsing: { label: '解析中', color: 'bg-blue-100 text-blue-600' },
  chunking: { label: '分块中', color: 'bg-blue-100 text-blue-600' },
  embedding: { label: '向量化', color: 'bg-yellow-100 text-yellow-600' },
  storing: { label: '存储中', color: 'bg-yellow-100 text-yellow-600' },
  indexing: { label: '索引中', color: 'bg-yellow-100 text-yellow-600' },
  indexed: { label: '已就绪', color: 'bg-green-100 text-green-600' },
  error: { label: '失败', color: 'bg-red-100 text-red-600' },
};

export function DocumentList() {
  const {
    documents, setDocuments, setLoading, removeDocument,
    updateDocumentStatus, upsertProcessingTask, removeProcessingTask,
  } = useDocumentStore();

  const activeStreams = useRef<Map<string, AbortController>>(new Map());

  // 为未完成索引的文档建立 SSE 连接
  const connectForDoc = (doc: DocumentItem) => {
    if (doc.status === 'indexed' || doc.status === 'error') return;
    if (activeStreams.current.has(doc.id)) return;

    const controller = streamDocumentProgress(doc.id, {
      onProgress: (event) => {
        updateDocumentStatus(doc.id, event.status);
        upsertProcessingTask({
          docId: doc.id,
          filename: doc.original_name,
          status: event.status,
          message: event.message,
        });
      },
      onDone: () => {
        updateDocumentStatus(doc.id, 'indexed');
        removeProcessingTask(doc.id);
        activeStreams.current.delete(doc.id);
      },
      onError: () => {
        updateDocumentStatus(doc.id, 'error');
        removeProcessingTask(doc.id);
        activeStreams.current.delete(doc.id);
      },
    });

    activeStreams.current.set(doc.id, controller);
  };

  useEffect(() => {
    const fetchDocs = async () => {
      setLoading(true);
      try {
        const result = await listDocuments();
        setDocuments(result.documents);
        // 为所有非终态文档建立 SSE 连接
        result.documents.forEach(connectForDoc);
      } catch {
        // 静默处理
      } finally {
        setLoading(false);
      }
    };
    fetchDocs();

    // 清理：组件卸载时断开所有 SSE
    return () => {
      activeStreams.current.forEach((ctrl) => ctrl.abort());
      activeStreams.current.clear();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [setDocuments, setLoading]);

  const handleDelete = async (docId: string) => {
    try {
      await deleteDocument(docId);
      removeDocument(docId);
      // 断开对应的 SSE
      activeStreams.current.get(docId)?.abort();
      activeStreams.current.delete(docId);
    } catch {
      // 静默处理
    }
  };

  if (documents.length === 0) {
    return (
      <p className="text-xs text-gray-400 text-center py-4">暂无文档</p>
    );
  }

  return (
    <div className="space-y-2">
      <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
        文档列表 ({documents.length})
      </h3>
      {documents.map((doc: DocumentItem) => {
        const IconComp = typeIcons[doc.file_type] || File;
        const status = statusConfig[doc.status] || statusConfig.uploaded;
        return (
          <div
            key={doc.id}
            className="flex items-center gap-2 p-2 rounded-lg bg-white dark:bg-gray-800 border border-gray-100 dark:border-gray-700"
          >
            <IconComp className="w-4 h-4 text-gray-400 shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="text-xs truncate text-gray-700 dark:text-gray-300">
                {doc.original_name}
              </p>
              <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${status.color}`}>
                {status.label}
              </span>
            </div>
            <button
              onClick={() => handleDelete(doc.id)}
              className="p-1 rounded hover:bg-red-50 dark:hover:bg-red-900/20 text-gray-400 hover:text-red-500 transition-colors shrink-0"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
