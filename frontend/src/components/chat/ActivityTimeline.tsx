import { useState } from 'react';
import { Check, ChevronDown, ChevronRight, Globe2, Loader2, Route, Search, Target, XCircle } from 'lucide-react';
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

const tierLabels = { fast: '快速', standard: '标准', expert: '专家' } as const;
const routeLabels = { direct: '直接处理', tool_agent: '工具执行', supervisor: '主 Agent 编排' } as const;
const reasonLabels: Record<string, string> = {
  empty_request: '空请求',
  long_request: '长请求',
  very_long_request: '超长请求',
  complex_intent: '复杂意图',
  multiple_sources: '多来源',
  multiple_questions: '多个问题',
  web_mode: '网页模式',
  long_context: '长上下文',
  simple_fact_intent: '简单事实',
  tool_access_required: '需要工具',
};

export function ActivityTimeline() {
  const [expanded, setExpanded] = useState(false);
  const steps = useChatStore((state) => state.agentSteps);
  const routeSelection = useChatStore((state) => state.routeSelection);
  const goalNodes = useChatStore((state) => state.goalNodes);
  const isStreaming = useChatStore((state) => state.isStreaming);
  if (!steps.length && !routeSelection && !goalNodes.length) return null;
  const running = isStreaming || steps.some((step) => step.status === 'running');
  const activityCount = steps.length + goalNodes.length + (routeSelection ? 1 : 0);
  return (
    <div className="ml-11 max-w-[80%] border-l-2 border-gray-200 pl-3 dark:border-gray-700">
      <button onClick={() => setExpanded(!expanded)} className="flex h-8 items-center gap-2 text-xs text-gray-500">
        {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        {running ? '正在执行' : `执行活动 · ${activityCount} 项`}
      </button>
      {expanded && <div className="space-y-2 pb-2">
        {goalNodes.map((goal) => (
          <div key={goal.id} className="text-xs text-gray-600 dark:text-gray-400">
            <div className="flex items-center gap-2">
              <Target className="h-3.5 w-3.5" />
              <span className="flex-1 truncate" title={goal.title}>{goal.title}</span>
              <span className="text-[10px] text-gray-400">{goal.agent_profile}</span>
              {goal.status === 'running' ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : goal.status === 'failed' || goal.status === 'cancelled' ? (
                <XCircle className="h-3.5 w-3.5 text-red-500" />
              ) : (
                <Check className="h-3.5 w-3.5 text-green-600" />
              )}
            </div>
            {goal.error_message && <p className="ml-5 mt-1 text-[10px] text-red-500">{goal.error_message}</p>}
          </div>
        ))}
        {routeSelection && (
          <div className="text-xs text-gray-600 dark:text-gray-400">
            <div className="flex items-center gap-2">
              <Route className="h-3.5 w-3.5" />
              <span className="flex-1 truncate">
                {tierLabels[routeSelection.tier]} · {routeLabels[routeSelection.route]}
              </span>
              <span className="text-[10px] tabular-nums text-gray-400">
                评分 {routeSelection.score} · 工具 ≤ {routeSelection.tool_call_budget}
              </span>
              <Check className="h-3.5 w-3.5 text-green-600" />
            </div>
            {!!routeSelection.reasons.length && (
              <p className="ml-5 mt-1 text-[10px] text-gray-400">
                {routeSelection.reasons.map((reason) => reasonLabels[reason] || reason).join(' · ')}
              </p>
            )}
          </div>
        )}
        {steps.map((step, index) => {
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
