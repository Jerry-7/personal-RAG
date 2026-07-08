/**
 * 文件上传组件
 *
 * 支持拖拽上传和点击选择文件。
 * 上传后触发后端异步索引流水线。
 */

import { useState, useCallback } from 'react';
import type { DragEvent } from 'react';
import { Upload } from 'lucide-react';
import { useDocumentStore } from '../../store/documentStore';
import { uploadDocument, listDocuments } from '../../api/documents';

export function DocumentUploader() {
  const [isDragging, setIsDragging] = useState(false);
  const { isUploading, uploadProgress, uploadError, setUploading, setUploadProgress, setUploadError, setDocuments } =
    useDocumentStore();

  const handleUpload = useCallback(
    async (file: File) => {
      setUploading(true);
      setUploadProgress(0);
      setUploadError(null);

      try {
        setUploadProgress(30);
        await uploadDocument(file);
        setUploadProgress(100);

        // 刷新文档列表
        const result = await listDocuments();
        setDocuments(result.documents);
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : '上传失败';
        setUploadError(message);
      } finally {
        setUploading(false);
        setUploadProgress(0);
      }
    },
    [setUploading, setUploadProgress, setUploadError, setDocuments]
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
              上传中... {uploadProgress}%
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
    </div>
  );
}
