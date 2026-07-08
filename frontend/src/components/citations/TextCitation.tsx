/**
 * 文本来源展示组件
 *
 * 显示来源文本内容，目标分块高亮（黄色背景），
 * 前后上下文以较浅颜色显示。
 */

import type { SourceResponse } from '../../types/source';

interface TextCitationProps {
  source: SourceResponse;
}

export function TextCitation({ source }: TextCitationProps) {
  const { chunk, surrounding_chunks } = source;

  return (
    <div className="space-y-4">
      {/* 上下文 - 前一个分块 */}
      {surrounding_chunks
        .filter((n) => n.chunk_index < chunk.chunk_index)
        .map((n, i) => (
          <p key={`prev-${i}`} className="text-xs text-gray-400 dark:text-gray-500 leading-relaxed">
            {n.text.length > 300 ? n.text.slice(0, 300) + '...' : n.text}
          </p>
        ))}

      {/* 目标分块 - 高亮 */}
      <div className="bg-yellow-50 dark:bg-yellow-900/30 border-l-4 border-yellow-400 pl-3 py-2 rounded-r">
        <p className="text-sm text-gray-800 dark:text-gray-200 leading-relaxed whitespace-pre-wrap">
          {chunk.text}
        </p>
        {chunk.page_number && (
          <p className="text-xs text-gray-400 mt-2">
            第 {chunk.page_number} 页
          </p>
        )}
      </div>

      {/* 上下文 - 后一个分块 */}
      {surrounding_chunks
        .filter((n) => n.chunk_index > chunk.chunk_index)
        .map((n, i) => (
          <p key={`next-${i}`} className="text-xs text-gray-400 dark:text-gray-500 leading-relaxed">
            {n.text.length > 300 ? n.text.slice(0, 300) + '...' : n.text}
          </p>
        ))}
    </div>
  );
}
