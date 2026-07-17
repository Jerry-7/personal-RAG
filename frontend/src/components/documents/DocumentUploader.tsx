/**
 * 文件上传组件
 *
 * 支持拖拽上传和点击选择文件。
 * 上传后立即返回，通过 SSE 实时展示后台索引进度。
 */

import { useState, useCallback, useRef } from 'react';
import type { DragEvent } from 'react';
import { Upload, FileText, Loader2, CheckCircle2, XCircle } from 'lucide-react';
import { useDocumentStore } from '../../store/documentStore';
import { uploadDocument, listDocuments, streamDocumentProgress } from '../../api/documents';
import type { ProcessingTask } from '../../types/document';

/** 状态 → 中文标签 */
const statusLabel: Record<string, string> = {
  uploaded: '等待处理',
  parsing: '解析中',
  chunking: '分块中',
  embedding: '向量化',
  storing: '存储中',
};

export function DocumentUploader() {
  const [isDragging, setIsDragging] = useState(false);
  const {
    isUploading, uploadError,
    processingQueue,
    setUploading, setUploadError,
    setDocuments, addDocument,
    updateDocumentStatus,
    upsertProcessingTask, removeProcessingTask,
  } = useDocumentStore();

  // 跟踪活跃的 SSE 连接
  const activeStreams = useRef<Map<string, AbortController>>(new Map());

  /** 启动单个文档的 SSE 进度流 */
  const connectProgressStream = useCallback(
    (docId: string, filename: string) => {
      // 避免重复连接
      if (activeStreams.current.has(docId)) return;

      const controller = streamDocumentProgress(docId, {
        onProgress: (event) => {
          updateDocumentStatus(docId, event.status);
          upsertProcessingTask({
            docId,
            filename,
            status: event.status,
            message: event.message,
          });
        },
        onDone: () => {
          updateDocumentStatus(docId, 'indexed');
          removeProcessingTask(docId);
          activeStreams.current.delete(docId);
          // 刷新列表获取最终元数据
          listDocuments().then((r) => setDocuments(r.documents)).catch(() => {});
        },
        onError: (event) => {
          updateDocumentStatus(docId, 'error');
          removeProcessingTask(docId);
          activeStreams.current.delete(docId);
          setUploadError(`${filename}: ${event.message}`);
        },
      });

      activeStreams.current.set(docId, controller);
    },
    [updateDocumentStatus, upsertProcessingTask, removeProcessingTask, setDocuments, setUploadError]
  );

  const handleUpload = useCallback(
    async (file: File) => {
      setUploading(true);
      setUploadError(null);

      try {
        // 上传文件（立即返回）
        const result = await uploadDocument(file);
        const docId = result.id;

        // 添加到文档列表
        addDocument({
          id: docId,
          filename: result.filename,
          original_name: result.original_name,
          file_type: result.file_type,
          file_size_bytes: 0,
          status: 'uploaded',
          chunk_count: 0,
          created_at: result.created_at,
          updated_at: result.created_at,
        });

        // 添加到处理队列并启动 SSE
        upsertProcessingTask({
          docId,
          filename: file.name,
          status: 'uploaded',
          message: '等待处理...',
        });
        connectProgressStream(docId, file.name);
      } catch (err: unknown) {
        let message = '上传失败';
        if (err instanceof Error) {
          message = err.message;
        }
        // 429 队列满
        if (message.includes('429') || message.includes('队列已满')) {
          message = '索引队列已满，请等待当前任务完成后再试';
        }
        setUploadError(message);
      } finally {
        setUploading(false);
      }
    },
    [setUploading, setUploadError, addDocument, upsertProcessingTask, connectProgressStream]
  );

  const handleDrop = useCallback(
    (e: DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) handleUpload(file);
    },
    [handleUpload]
  );

  const handleDragOver = (e: DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => setIsDragging(false);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleUpload(file);
  };

  return (
    <div>
      {/* 上传区域 */}
      <label
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        className={`flex flex-col items-center justify-center gap-2 p-6 border-2 border-dashed rounded-xl cursor-pointer transition-colors ${
          isDragging
            ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20'
            : 'border-gray-300 dark:border-gray-600 hover:border-blue-400'
        }`}
      >
        <input
          type="file"
          className="hidden"
          accept=".pdf,.docx,.doc,.txt,.md,.csv,.mp4,.mp3,.avi,.mkv,.mov,.webm,.wav,.flac,.ogg,.m4a,.aac,.wma,.jpg,.jpeg,.png,.bmp,.tiff,.tif,.webp"
          onChange={handleFileChange}
          disabled={isUploading}
        />

        {isUploading ? (
          <div className="flex flex-col items-center gap-2">
            <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
            <span className="text-sm text-gray-600 dark:text-gray-400">
              上传文件中...
            </span>
          </div>
        ) : (
          <>
            <Upload className="w-8 h-8 text-gray-400" />
            <span className="text-sm text-gray-600 dark:text-gray-400">
              拖拽文件到此处或点击上传
            </span>
            <span className="text-xs text-gray-400">
              PDF / Word / TXT / 视频 / 图片
            </span>
          </>
        )}

        {uploadError && (
          <p className="text-xs text-red-500 mt-1">{uploadError}</p>
        )}
      </label>

      {/* 后台处理进度 */}
      {processingQueue.length > 0 && (
        <div className="mt-3 space-y-2">
          <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
            处理中 ({processingQueue.length})
          </h4>
          {processingQueue.map((task: ProcessingTask) => (
            <ProcessingCard key={task.docId} task={task} />
          ))}
        </div>
      )}
    </div>
  );
}

/** 单个处理任务卡片 */
function ProcessingCard({ task }: { task: ProcessingTask }) {
  const isDone = task.status === 'indexed';
  const isError = task.status === 'error';
  const label = statusLabel[task.status] || task.status;

  return (
    <div className="flex items-center gap-2 p-2 rounded-lg bg-white dark:bg-gray-800 border border-gray-100 dark:border-gray-700">
      <FileText className="w-4 h-4 text-gray-400 shrink-0" />
      <div className="flex-1 min-w-0">
        <p className="text-xs truncate text-gray-700 dark:text-gray-300">
          {task.filename}
        </p>
        <p className="text-[10px] text-gray-400">{label}</p>
      </div>
      {isDone ? (
        <CheckCircle2 className="w-4 h-4 text-green-500 shrink-0" />
      ) : isError ? (
        <XCircle className="w-4 h-4 text-red-500 shrink-0" />
      ) : (
        <Loader2 className="w-4 h-4 text-blue-500 animate-spin shrink-0" />
      )}
    </div>
  );
}
