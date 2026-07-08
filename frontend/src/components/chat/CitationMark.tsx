/**
 * 引用标记组件
 *
 * 在 AI 回复中内联显示可点击的 [N] 引用标记。
 * 点击时触发右侧 CitationSidebar 展示来源内容。
 */

import { useSidebarStore } from '../../store/sidebarStore';
import type { CitationData } from '../../types/chat';

interface CitationMarkProps {
  index: number;
  citation?: CitationData;
}

export function CitationMark({ index, citation }: CitationMarkProps) {
  const openSource = useSidebarStore((s) => s.openSource);

  const handleClick = () => {
    if (citation) {
      openSource(citation);
    }
  };

  return (
    <button
      onClick={handleClick}
      disabled={!citation}
      className="inline-flex items-center justify-center w-5 h-5 mx-0.5 rounded-full bg-yellow-100 dark:bg-yellow-900 text-yellow-800 dark:text-yellow-200 text-[10px] font-bold hover:bg-yellow-200 dark:hover:bg-yellow-800 transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-default align-middle"
      title={citation ? `来源: ${citation.filename}${citation.page_number ? ` 第${citation.page_number}页` : ''}` : undefined}
    >
      {index}
    </button>
  );
}
