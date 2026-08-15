import { useState } from 'react';
import {
  Bot,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleDashed,
  GitFork,
  GitMerge,
  Globe2,
  Loader2,
  Route,
  RotateCcw,
  Search,
  Target,
  XCircle,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useChatStore } from '../../store/chatStore';
import { retryChatRun } from '../../services/chatExecution';
import type { AgentStep, GoalNodeData } from '../../types/chat';

const toolLabels: Record<string, string> = {
  web_search: '搜索网页',
  fetch_web_page: '读取网页',
  crawl_website: '研究站点',
  search_knowledge_base: '检索知识库',
  read_chunk: '读取本地来源',
  list_documents: '检查文档',
  create_note_draft: '整理笔记草稿',
};

const profileLabels: Record<string, string> = {
  fast_general: '快速 Agent',
  standard_research: '研究 Agent',
  expert_supervisor: '主控 Agent',
  local_retriever: '本地检索',
  web_researcher: '网页研究',
  expert_synthesizer: '专家汇总',
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

function StatusIcon({ status }: { status: GoalNodeData['status'] | AgentStep['status'] }) {
  if (status === 'running') return <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-blue-600" />;
  if (status === 'failed' || status === 'cancelled') return <XCircle className="h-3.5 w-3.5 shrink-0 text-red-500" />;
  if (status === 'completed') return <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-green-600" />;
  return <CircleDashed className="h-3.5 w-3.5 shrink-0 text-gray-400" />;
}

function ToolActivity({ step }: { step: AgentStep }) {
  const Icon = step.name === 'web_search'
    ? Search
    : step.name?.includes('web') || step.name === 'crawl_website'
      ? Globe2
      : Search;

  return (
    <div className="min-w-0 text-[11px] text-gray-500 dark:text-gray-400">
      <div className="flex min-h-6 items-center gap-2">
        <Icon className="h-3 w-3 shrink-0" />
        <span className="min-w-0 flex-1 truncate">{toolLabels[step.name || ''] || step.name}</span>
        <StatusIcon status={step.status} />
        {!!step.duration_ms && (
          <span className="shrink-0 tabular-nums text-[10px] text-gray-400">{step.duration_ms}ms</span>
        )}
      </div>
      {step.name === 'web_search' && step.status === 'completed' && step.result && (
        <div className="ml-5 mt-1 max-h-40 overflow-y-auto whitespace-pre-wrap leading-5">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
              a: ({ children, href }) => (
                <a href={href} target="_blank" rel="noreferrer" className="font-medium text-blue-600 hover:underline dark:text-blue-400">
                  {children}
                </a>
              ),
            }}
          >
            {step.result}
          </ReactMarkdown>
        </div>
      )}
    </div>
  );
}

interface GoalBranchProps {
  goal: GoalNodeData;
  goals: GoalNodeData[];
  steps: AgentStep[];
  compact?: boolean;
}

function GoalBranch({ goal, goals, steps, compact = false }: GoalBranchProps) {
  const children = goals.filter((item) => item.parent_id === goal.id);
  const independent = children.filter((item) => item.dependencies.length === 0);
  const dependent = children.filter((item) => item.dependencies.length > 0);
  const goalSteps = steps.filter((step) => step.node_id === goal.id);
  const Icon = goal.kind === 'root' ? Target : Bot;

  return (
    <div className="min-w-0">
      <div className="flex min-h-7 items-center gap-2 text-xs text-gray-700 dark:text-gray-300">
        <Icon className="h-3.5 w-3.5 shrink-0" />
        <span className="min-w-0 flex-1 truncate font-medium" title={goal.title}>{goal.title}</span>
        <span className="shrink-0 text-[10px] text-gray-400">
          {profileLabels[goal.agent_profile] || goal.agent_profile}
        </span>
        {goal.attempt > 1 && (
          <span className="shrink-0 text-[10px] font-medium text-amber-600 dark:text-amber-400">
            重试 {goal.attempt}/{goal.max_attempts}
          </span>
        )}
        <StatusIcon status={goal.status} />
      </div>

      {goal.error_message && (
        <p className={`ml-5 mt-1 text-[10px] leading-4 ${goal.status === 'running' ? 'text-amber-600 dark:text-amber-400' : 'text-red-500'}`}>
          {goal.status === 'running' ? '上次尝试：' : ''}{goal.error_message}
        </p>
      )}

      {!!goalSteps.length && (
        <div className="ml-[7px] border-l border-gray-200 py-1 pl-4 dark:border-gray-700">
          {goalSteps.map((step, index) => (
            <ToolActivity key={step.id || `${step.name}-${index}`} step={step} />
          ))}
        </div>
      )}

      {independent.length > 1 ? (
        <div className="ml-[7px] border-l border-gray-200 pb-1 pl-4 pt-2 dark:border-gray-700">
          <div className="mb-2 flex items-center gap-2 text-[10px] font-medium text-blue-600 dark:text-blue-400">
            <GitFork className="h-3.5 w-3.5" />
            并行执行 · {independent.length} 个 Agent
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {independent.map((child) => (
              <div key={child.id} className="min-w-0 border-l-2 border-blue-200 pl-3 dark:border-blue-800">
                <GoalBranch goal={child} goals={goals} steps={steps} compact />
              </div>
            ))}
          </div>
        </div>
      ) : (
        independent.map((child) => (
          <div key={child.id} className={`${compact ? 'ml-2' : 'ml-[7px]'} border-l border-gray-200 pl-4 dark:border-gray-700`}>
            <GoalBranch goal={child} goals={goals} steps={steps} compact={compact} />
          </div>
        ))
      )}

      {dependent.map((child) => (
        <div key={child.id} className="ml-[7px] border-l border-gray-200 pl-4 pt-1 dark:border-gray-700">
          <div className="mb-1 flex items-center gap-2 text-[10px] text-gray-400">
            <GitMerge className="h-3.5 w-3.5" />
            汇合 {child.dependencies.length} 个分支
          </div>
          <GoalBranch goal={child} goals={goals} steps={steps} />
        </div>
      ))}
    </div>
  );
}

export function ActivityTimeline() {
  const [expanded, setExpanded] = useState(true);
  const steps = useChatStore((state) => state.agentSteps);
  const routeSelection = useChatStore((state) => state.routeSelection);
  const goalNodes = useChatStore((state) => state.goalNodes);
  const isStreaming = useChatStore((state) => state.isStreaming);
  const runId = useChatStore((state) => state.runId);

  if (!steps.length && !routeSelection && !goalNodes.length) return null;

  const roots = goalNodes.filter((goal) => goal.parent_id === null);
  const assignedGoalIds = new Set(goalNodes.map((goal) => goal.id));
  const unassignedSteps = steps.filter((step) => !step.node_id || !assignedGoalIds.has(step.node_id));
  const running = isStreaming || goalNodes.some((goal) => goal.status === 'running');
  const retryable = Boolean(
    runId
      && !isStreaming
      && roots.some((goal) => goal.status === 'failed' || goal.status === 'cancelled')
  );
  const activityCount = steps.length + goalNodes.length + (routeSelection ? 1 : 0);

  return (
    <div className="ml-11 mr-2 min-w-0 border-l-2 border-gray-200 pl-3 dark:border-gray-700">
      <div className="flex min-w-0 items-center">
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="flex h-8 min-w-0 flex-1 items-center gap-2 text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
        >
          {expanded ? <ChevronDown className="h-3.5 w-3.5 shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
          <span className="truncate">{running ? '正在执行' : `执行活动 · ${activityCount} 项`}</span>
        </button>
        {retryable && runId && (
          <button
            type="button"
            onClick={() => retryChatRun(runId)}
            className="flex h-7 shrink-0 items-center gap-1 px-2 text-[11px] font-medium text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300"
            title="重新执行此运行"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            重试运行
          </button>
        )}
      </div>

      {expanded && (
        <div className="max-w-3xl space-y-2 pb-3">
          {routeSelection && (
            <div className="text-xs text-gray-600 dark:text-gray-400">
              <div className="flex min-h-7 items-center gap-2">
                <Route className="h-3.5 w-3.5 shrink-0" />
                <span className="min-w-0 flex-1 truncate">
                  {tierLabels[routeSelection.tier]} · {routeLabels[routeSelection.route]}
                </span>
                <span className="shrink-0 tabular-nums text-[10px] text-gray-400">
                  评分 {routeSelection.score} · 工具 ≤ {routeSelection.tool_call_budget}
                </span>
                <Check className="h-3.5 w-3.5 shrink-0 text-green-600" />
              </div>
              {!!routeSelection.reasons.length && (
                <p className="ml-5 text-[10px] text-gray-400">
                  {routeSelection.reasons.map((reason) => reasonLabels[reason] || reason).join(' · ')}
                </p>
              )}
            </div>
          )}

          {roots.map((goal) => (
            <GoalBranch key={goal.id} goal={goal} goals={goalNodes} steps={steps} />
          ))}

          {!!unassignedSteps.length && (
            <div className="border-l border-gray-200 pl-4 dark:border-gray-700">
              {unassignedSteps.map((step, index) => (
                <ToolActivity key={step.id || `${step.name}-${index}`} step={step} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
