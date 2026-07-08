/**
 * 引用侧边栏容器组件
 *
 * 右侧滑出面板，展示引用来源的详细内容。
 * 支持文本来源的高亮显示和视频来源的时间戳跳转。
 */

import { useEffect, useState } from 'react';
import { X } from 'lucide-react';
import { TextCitation } from './TextCitation';
import { VideoCitation } from './VideoCitation';
import { useSidebarStore } from '../../store/sidebarStore';
import { getSourceChunk } from '../../api/sources';
import type { SourceResponse } from '../../types/source';

export function CitationSidebar() {
  const { isOpen, activeCitations, activeCitationIndex, closeSidebar, setLoading } =
    useSidebarStore();
  const [sources, setSources] = useState<Map<string, SourceResponse>>(new Map());

  // 当前激活的引用
  const activeCitation = activeCitations.find((c) => c.index === activeCitationIndex);

  useEffect(() => {
    if (!activeCitation) return;

    const cacheKey = `${activeCitation.document_id}_${activeCitation.chunk_id}`;
    if (sources.has(cacheKey)) return;

    setLoading(true);
    getSourceChunk(activeCitation.document_id, activeCitation.chunk_id)
      .then((data) => {
        setSources((prev) => new Map(prev).set(cacheKey, data));
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [activeCitation, sources, setLoading]);

  if (!isOpen) return null;

  const cacheKey = activeCitation
    ? `${activeCitation.document_id}_${activeCitation.chunk_id}`
    : null;
  const sourceData = cacheKey ? sources.get(cacheKey) : null;

  return (
    <div className="h-full flex flex-col">
      {/* 头部 */}
      <div className="flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-700">
        <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
          引用来源 {activeCitation ? `#${activeCitation.index}` : ''}
        </h3>
        <button
          onClick={closeSidebar}
          className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
        >
          <X className="w-4 h-4 text-gray-500" />
        </button>
      </div>

      {/* 引用导航标签 */}
      {activeCitations.length > 1 && (
        <div className="flex gap-1 p-2 border-b border-gray-100 dark:border-gray-800 overflow-x-auto">
          {activeCitations.map((c) => (
            <button
              key={`${c.document_id}_${c.chunk_id}`}
              onClick={() => useSidebarStore.getState().setActiveCitation(c.index)}
              className={`px-2 py-1 text-xs rounded-full shrink-0 transition-colors ${
                c.index === activeCitationIndex
                  ? 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300'
                  : 'hover:bg-gray-100 text-gray-500'
              }`}
            >
              #{c.index} {c.filename}
            </button>
          ))}
        </div>
      )}

      {/* 内容 */}
      <div className="flex-1 overflow-y-auto">
        {!sourceData && (
          <div className="flex items-center justify-center h-32 text-sm text-gray-400">
            加载中...
          </div>
        )}

        {sourceData && activeCitation && (
          <>
            {/* 文档元数据 */}
            <div className="p-4 bg-gray-50 dark:bg-gray-800 border-b border-gray-100 dark:border-gray-700">
              <p className="text-sm font-medium text-gray-800 dark:text-gray-200">
                {sourceData.document.original_name}
              </p>
              <p className="text-xs text-gray-500">
                {sourceData.document.file_type.toUpperCase()}
                {sourceData.chunk.page_number && ` · 第 ${sourceData.chunk.page_number} 页`}
                {sourceData.chunk.start_timestamp != null &&
                  ` · ${formatTime(sourceData.chunk.start_timestamp)}-${formatTime(sourceData.chunk.end_timestamp || 0)}`}
              </p>
            </div>

            {/* 来源内容 */}
            <div className="p-4">
              {sourceData.chunk.source_type === 'video' || sourceData.chunk.source_type === 'audio' ? (
                <VideoCitation source={sourceData} citation={activeCitation} />
              ) : (
                <TextCitation source={sourceData} />
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/** 格式化秒数为 mm:ss */
function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}
