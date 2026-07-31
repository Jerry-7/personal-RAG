/**
 * 引用侧边栏容器组件
 *
 * 右侧滑出面板，展示引用来源的详细内容。
 * 支持文本来源的高亮显示和视频来源的时间戳跳转。
 */

import { useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ExternalLink, X } from 'lucide-react';
import { TextCitation } from './TextCitation';
import { VideoCitation } from './VideoCitation';
import { useSidebarStore } from '../../store/sidebarStore';
import { getNoteSource, getSourceChunk, getWebSnapshot } from '../../api/sources';
import type { NoteSourceResponse, SourceResponse, WebSourceResponse } from '../../types/source';

export function CitationSidebar() {
  const { isOpen, activeCitations, activeCitationIndex, closeSidebar, setLoading } =
    useSidebarStore();
  const [sources, setSources] = useState<Map<string, SourceResponse>>(new Map());
  const [webSources, setWebSources] = useState<Map<string, WebSourceResponse>>(new Map());
  const [noteSources, setNoteSources] = useState<Map<string, NoteSourceResponse>>(new Map());

  // 当前激活的引用
  const activeCitation = activeCitations.find((c) => c.index === activeCitationIndex);

  useEffect(() => {
    if (!activeCitation) return;

    if (activeCitation.source_type === 'web' && activeCitation.snapshot_id) {
      if (webSources.has(activeCitation.snapshot_id)) return;
      setLoading(true);
      getWebSnapshot(activeCitation.snapshot_id)
        .then((data) => setWebSources((prev) => new Map(prev).set(activeCitation.snapshot_id!, data)))
        .catch(console.error).finally(() => setLoading(false));
      return;
    }
    if (activeCitation.source_type === 'note' && activeCitation.source_id) {
      if (noteSources.has(activeCitation.source_id)) return;
      setLoading(true);
      getNoteSource(activeCitation.source_id)
        .then((data) => setNoteSources((prev) => new Map(prev).set(activeCitation.source_id!, data)))
        .catch(console.error).finally(() => setLoading(false));
      return;
    }
    const cacheKey = `${activeCitation.document_id}_${activeCitation.chunk_id}`;
    if (sources.has(cacheKey)) return;

    setLoading(true);
    getSourceChunk(activeCitation.document_id, activeCitation.chunk_id)
      .then((data) => {
        setSources((prev) => new Map(prev).set(cacheKey, data));
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [activeCitation, sources, webSources, noteSources, setLoading]);

  if (!isOpen) return null;

  const cacheKey = activeCitation
    ? `${activeCitation.document_id}_${activeCitation.chunk_id}`
    : null;
  const sourceData = cacheKey ? sources.get(cacheKey) : null;
  const webData = activeCitation?.snapshot_id ? webSources.get(activeCitation.snapshot_id) : null;
  const noteData = activeCitation?.source_id ? noteSources.get(activeCitation.source_id) : null;

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
        {!sourceData && !webData && !noteData && (
          <div className="flex items-center justify-center h-32 text-sm text-gray-400">
            加载中...
          </div>
        )}

        {webData && activeCitation && (
          <div>
            <div className="border-b border-gray-100 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-800">
              <p className="text-sm font-medium text-gray-800 dark:text-gray-200">{webData.title}</p>
              <a href={webData.url} target="_blank" rel="noreferrer" className="mt-1 flex items-center gap-1 break-all text-xs text-blue-600">{webData.url}<ExternalLink className="h-3 w-3 shrink-0" /></a>
              <p className="mt-2 text-[10px] text-gray-500">抓取于 {new Date(webData.fetched_at).toLocaleString()} · {webData.content_hash.slice(0, 12)}</p>
            </div>
            <div className="whitespace-pre-wrap p-4 text-sm leading-6 text-gray-700 dark:text-gray-300">{webData.content}</div>
          </div>
        )}

        {noteData && activeCitation && (
          <div>
            <div className="border-b border-gray-100 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-800">
              <p className="text-sm font-medium">{noteData.title}</p>
              <p className="mt-1 text-[10px] text-gray-500">笔记 · 更新于 {new Date(noteData.updated_at).toLocaleString()}</p>
            </div>
            <div className="prose prose-sm max-w-none p-4 dark:prose-invert"><ReactMarkdown remarkPlugins={[remarkGfm]}>{noteData.content_md}</ReactMarkdown></div>
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
