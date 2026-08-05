import { useState } from 'react';
import { Check, ChevronDown, ChevronRight, Globe2, Loader2, Search, XCircle } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useChatStore } from '../../store/chatStore';

const labels: Record<string, string> = {
  web_search: '搜索网页',
  fetch_web_page: '读取网页',
  crawl_website: '研究站点',
  search_knowledge_base: '检索知识库',
  read_chunk: '读取本地来源',
  list_documents: '检查文档',
  create_note_draft: '整理笔记草稿',
};

export function ActivityTimeline() {
  const [expanded, setExpanded] = useState(false);
  const steps = useChatStore((state) => state.agentSteps);
  if (!steps.length) return null;
  const running = steps.some((step) => step.status === 'running');
  return (
    <div className="ml-11 max-w-[80%] border-l-2 border-gray-200 pl-3 dark:border-gray-700">
      <button onClick={() => setExpanded(!expanded)} className="flex h-8 items-center gap-2 text-xs text-gray-500">
        {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        {running ? '正在研究' : `研究活动 · ${steps.length} 步`}
      </button>
      {expanded && <div className="space-y-2 pb-2">{steps.map((step, index) => {
        const Icon = step.name === 'web_search' ? Search : step.name?.includes('web') || step.name === 'crawl_website' ? Globe2 : Search;
        return <div key={step.id || `${step.name}-${index}`} className="text-xs text-gray-600 dark:text-gray-400">
          <div className="flex items-center gap-2">
            <Icon className="h-3.5 w-3.5" />
            <span className="flex-1 truncate">{labels[step.name || ''] || step.name}</span>
            {step.status === 'running' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : step.status === 'failed' ? <XCircle className="h-3.5 w-3.5 text-red-500" /> : <Check className="h-3.5 w-3.5 text-green-600" />}
            {!!step.duration_ms && <span className="tabular-nums text-[10px] text-gray-400">{step.duration_ms}ms</span>}
          </div>
          {step.name === 'web_search' && step.status === 'completed' && step.result && (
            <div className="ml-5 mt-1 max-h-48 overflow-y-auto whitespace-pre-wrap text-[11px] leading-5 text-gray-500 dark:text-gray-400">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                  a: ({ children, href }) => <a href={href} target="_blank" rel="noreferrer" className="font-medium text-blue-600 hover:underline dark:text-blue-400">{children}</a>,
                }}
              >
                {step.result}
              </ReactMarkdown>
            </div>
          )}
        </div>;
      })}</div>}
    </div>
  );
}
