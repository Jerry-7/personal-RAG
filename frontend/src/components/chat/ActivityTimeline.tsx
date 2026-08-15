import { useState } from 'react';
import {
  Bot,
  BarChart3,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleDashed,
  Clock3,
  GitFork,
  GitMerge,
  Globe2,
  History,
  Loader2,
  Lightbulb,
  Pause,
  Play,
  Route,
  RotateCcw,
  Search,
  Target,
  ThumbsDown,
  ThumbsUp,
  Wrench,
  XCircle,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useChatStore } from '../../store/chatStore';
import { pauseChatExecution, resumeChatExecution, retryChatRun } from '../../services/chatExecution';
import { loadRunSnapshot } from '../../services/runHistory';
import { removeRunFeedback, saveRunFeedback } from '../../services/runFeedback';
import type {
  AgentRunFeedbackReason,
  AgentStep,
  GoalNodeData,
  RoutingRecommendationAction,
} from '../../types/chat';

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
  manual_tier_override: '手动指定',
};

const runStatusLabels = {
  running: '正在执行',
  paused: '已暂停',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
  interrupted: '已中断',
} as const;

const feedbackReasonLabels: Record<AgentRunFeedbackReason, string> = {
  incorrect: '内容不正确',
  missing_evidence: '证据不足',
  too_slow: '执行过慢',
  over_complicated: '过度复杂',
};

const recommendationLabels: Record<RoutingRecommendationAction, string> = {
  upgrade_tier: '升级 Agent 等级',
  downgrade_tier: '试用较低等级',
  investigate_reliability: '检查运行可靠性',
  review_planning: '检查目标规划',
  investigate_quality: '检查回答质量',
  optimize_latency: '优化执行耗时',
  simplify_route: '简化执行路径',
  keep_policy: '保持当前策略',
};

const recommendationReasonLabels: Record<string, string> = {
  low_operational_success: '运行成功率偏低',
  high_tool_failure: '工具失败率偏高',
  low_user_satisfaction: '用户满意率偏低',
  missing_evidence: '证据不足',
  incorrect: '内容不正确',
  too_slow: '执行过慢',
  over_complicated: '过度复杂',
  high_quality_low_utilization: '质量稳定且预算利用率低',
  stable_policy: '当前策略稳定',
};

const confidenceLabels = { low: '低置信', medium: '中置信', high: '高置信' } as const;

function formatDuration(durationMs: number | null): string {
  if (durationMs === null) return '--';
  if (durationMs < 1000) return `${durationMs}ms`;
  if (durationMs < 60000) return `${(durationMs / 1000).toFixed(1)}s`;
  return `${Math.floor(durationMs / 60000)}m ${Math.round((durationMs % 60000) / 1000)}s`;
}

function getAgentTreeShape(goals: GoalNodeData[]): { maxChildren: number; maxDepth: number } {
  const primary = goals
    .filter((goal) => goal.kind === 'agent')
    .sort((left, right) => left.sequence - right.sequence)[0];
  if (!primary) return { maxChildren: 0, maxDepth: 0 };

  const parents = new Map(goals.map((goal) => [goal.id, goal.parent_id]));
  const descendants: GoalNodeData[] = [];
  let maxDepth = 0;
  for (const goal of goals) {
    if (goal.id === primary.id) continue;
    let parentId = goal.parent_id;
    let depth = 0;
    const visited = new Set([goal.id]);
    while (parentId && !visited.has(parentId)) {
      visited.add(parentId);
      depth += 1;
      if (parentId === primary.id) {
        descendants.push(goal);
        maxDepth = Math.max(maxDepth, depth);
        break;
      }
      parentId = parents.get(parentId) || null;
    }
  }

  const descendantIds = new Set(descendants.map((goal) => goal.id));
  const childCounts = new Map<string, number>();
  for (const goal of descendants) {
    if (goal.parent_id === primary.id || (goal.parent_id && descendantIds.has(goal.parent_id))) {
      childCounts.set(goal.parent_id, (childCounts.get(goal.parent_id) || 0) + 1);
    }
  }
  return {
    maxChildren: Math.max(0, ...childCounts.values()),
    maxDepth,
  };
}

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
        {goal.model_name && (
          <span
            className="max-w-32 shrink truncate text-[10px] text-gray-400"
            title={`${goal.model_provider}: ${goal.model_name}`}
          >
            {goal.model_name}
          </span>
        )}
        {goal.tool_call_budget > 0 && (
          <span className="shrink-0 tabular-nums text-[10px] text-gray-400">
            工具 {goalSteps.length}/{goal.tool_call_budget}
          </span>
        )}
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
  const [controlPending, setControlPending] = useState(false);
  const [feedbackPending, setFeedbackPending] = useState(false);
  const steps = useChatStore((state) => state.agentSteps);
  const routeSelection = useChatStore((state) => state.routeSelection);
  const goalNodes = useChatStore((state) => state.goalNodes);
  const isStreaming = useChatStore((state) => state.isStreaming);
  const isPaused = useChatStore((state) => state.isPaused);
  const runId = useChatStore((state) => state.runId);
  const runHistory = useChatStore((state) => state.runHistory);
  const runSnapshot = useChatStore((state) => state.runSnapshot);
  const routingAnalytics = useChatStore((state) => state.routingAnalytics);

  if (!steps.length && !routeSelection && !goalNodes.length && !runSnapshot && !runHistory.length) return null;

  const roots = goalNodes.filter((goal) => goal.parent_id === null);
  const assignedGoalIds = new Set(goalNodes.map((goal) => goal.id));
  const unassignedSteps = steps.filter((step) => !step.node_id || !assignedGoalIds.has(step.node_id));
  const running = isStreaming
    || runSnapshot?.status === 'running'
    || goalNodes.some((goal) => goal.status === 'running');
  const retryable = Boolean(
    runId
      && !isStreaming
      && (runSnapshot?.retryable
        ?? roots.some((goal) => goal.status === 'failed' || goal.status === 'cancelled'))
  );
  const activityCount = steps.length + goalNodes.length + (routeSelection ? 1 : 0);
  const terminalGoalCount = goalNodes.filter((goal) =>
    goal.status === 'completed' || goal.status === 'failed' || goal.status === 'cancelled'
  ).length;
  const goalProgress = goalNodes.length
    ? Math.round(terminalGoalCount * 100 / goalNodes.length)
    : runSnapshot?.metrics.progress_percent ?? 0;
  const retryAttempts = goalNodes.reduce(
    (total, goal) => total + Math.max(0, goal.attempt - 1),
    0,
  );
  const liveTreeShape = getAgentTreeShape(goalNodes);
  const observedMaxChildren = routeSelection?.observed_max_children ?? liveTreeShape.maxChildren;
  const observedMaxDepth = routeSelection?.observed_max_depth ?? liveTreeShape.maxDepth;
  const updateFeedback = async (
    rating: 'positive' | 'negative',
    reason?: AgentRunFeedbackReason,
  ) => {
    if (!runId || feedbackPending) return;
    setFeedbackPending(true);
    try {
      if (runSnapshot?.feedback?.rating === rating && !reason) {
        await removeRunFeedback(runId);
      } else {
        await saveRunFeedback(runId, rating, reason);
      }
    } catch (error) {
      console.error('Failed to update Agent run feedback', error);
    } finally {
      setFeedbackPending(false);
    }
  };
  const updateFeedbackReason = async (reason?: AgentRunFeedbackReason) => {
    if (!runId || feedbackPending) return;
    setFeedbackPending(true);
    try {
      await saveRunFeedback(runId, 'negative', reason);
    } catch (error) {
      console.error('Failed to update feedback reason', error);
    } finally {
      setFeedbackPending(false);
    }
  };
  const togglePaused = async () => {
    if (controlPending) return;
    setControlPending(true);
    try {
      if (isPaused) await resumeChatExecution();
      else await pauseChatExecution();
    } catch (error) {
      console.error('Failed to update Agent run state', error);
    } finally {
      setControlPending(false);
    }
  };

  return (
    <div className="ml-11 mr-2 min-w-0 border-l-2 border-gray-200 pl-3 dark:border-gray-700">
      <div className="flex min-w-0 items-center">
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="flex h-8 min-w-0 flex-1 items-center gap-2 text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
        >
          {expanded ? <ChevronDown className="h-3.5 w-3.5 shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
          <span className="truncate">
            {isPaused
              ? '已暂停'
              : !isStreaming && runSnapshot
                ? runStatusLabels[runSnapshot.status]
                : running
                  ? '正在执行'
                  : `执行活动 · ${activityCount} 项`}
          </span>
        </button>
        {isStreaming && runId && (
          <button
            type="button"
            onClick={() => void togglePaused()}
            disabled={controlPending}
            className="flex h-7 shrink-0 items-center gap-1 px-2 text-[11px] font-medium text-gray-600 hover:text-gray-900 disabled:opacity-50 dark:text-gray-400 dark:hover:text-gray-100"
            title={isPaused ? '继续执行' : '暂停执行'}
          >
            {isPaused ? <Play className="h-3.5 w-3.5" /> : <Pause className="h-3.5 w-3.5" />}
            {isPaused ? '继续' : '暂停'}
          </button>
        )}
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
          {(runHistory.length > 1 || runSnapshot) && (
            <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-gray-400">
              {runHistory.length > 1 && (
                <label className="flex min-w-0 items-center gap-1.5">
                  <History className="h-3.5 w-3.5 shrink-0" />
                  <select
                    aria-label="选择运行记录"
                    value={runId || ''}
                    disabled={isStreaming}
                    onChange={(event) => void loadRunSnapshot(event.target.value).catch(() => undefined)}
                    className="h-6 max-w-56 border-0 bg-transparent pr-1 text-[10px] text-gray-500 outline-none disabled:opacity-50 dark:text-gray-400"
                  >
                    {runHistory.map((run, index) => (
                      <option key={run.id} value={run.id}>
                        {`运行 ${runHistory.length - index} · ${runStatusLabels[run.status]}`}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {runSnapshot && (
                <>
                  <span className="font-medium text-gray-600 dark:text-gray-300">
                    {runStatusLabels[runSnapshot.status]}
                  </span>
                  <span className="flex items-center gap-1 tabular-nums">
                    <Clock3 className="h-3 w-3" />
                    {formatDuration(runSnapshot.metrics.duration_ms)}
                  </span>
                  <span className="flex items-center gap-1 tabular-nums">
                    <Bot className="h-3 w-3" />
                    {runSnapshot.metrics.agent_count} Agent
                  </span>
                  <span className="flex items-center gap-1 tabular-nums">
                    <Wrench className="h-3 w-3" />
                    {runSnapshot.metrics.tool_calls_used}/{runSnapshot.metrics.tool_call_budget}
                  </span>
                  <span className="flex items-center gap-1 tabular-nums">
                    <Globe2 className="h-3 w-3" />
                    {runSnapshot.metrics.web_pages_used}/{runSnapshot.metrics.web_page_budget}
                  </span>
                  {runSnapshot.retry_of_run_id && <span>重试运行</span>}
                  {runSnapshot.retry_count > 0 && <span>{runSnapshot.retry_count} 次后续重试</span>}
                  {runSnapshot.status === 'completed' && runId && (
                    <span className="flex items-center gap-0.5">
                      <button
                        type="button"
                        aria-label="回答有帮助"
                        aria-pressed={runSnapshot.feedback?.rating === 'positive'}
                        title="回答有帮助"
                        disabled={feedbackPending}
                        onClick={() => void updateFeedback('positive')}
                        className={`flex h-6 w-6 items-center justify-center rounded-sm disabled:opacity-50 ${
                          runSnapshot.feedback?.rating === 'positive'
                            ? 'bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-400'
                            : 'text-gray-400 hover:text-green-600'
                        }`}
                      >
                        <ThumbsUp className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        aria-label="回答需要改进"
                        aria-pressed={runSnapshot.feedback?.rating === 'negative'}
                        title="回答需要改进"
                        disabled={feedbackPending}
                        onClick={() => void updateFeedback('negative')}
                        className={`flex h-6 w-6 items-center justify-center rounded-sm disabled:opacity-50 ${
                          runSnapshot.feedback?.rating === 'negative'
                            ? 'bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-400'
                            : 'text-gray-400 hover:text-red-500'
                        }`}
                      >
                        <ThumbsDown className="h-3.5 w-3.5" />
                      </button>
                    </span>
                  )}
                </>
              )}
            </div>
          )}
          {runSnapshot?.feedback?.rating === 'negative' && runId && (
            <label className="ml-5 flex min-w-0 items-center gap-2 text-[10px] text-gray-400">
              <span className="shrink-0">改进原因</span>
              <select
                aria-label="选择需要改进的原因"
                value={runSnapshot.feedback.reason || ''}
                disabled={feedbackPending}
                onChange={(event) => void updateFeedbackReason(
                  (event.target.value || undefined) as AgentRunFeedbackReason | undefined,
                )}
                className="h-6 min-w-0 max-w-40 rounded-sm border border-gray-200 bg-white px-1.5 text-[10px] text-gray-600 outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-300"
              >
                <option value="">未选择</option>
                {(Object.entries(feedbackReasonLabels) as [AgentRunFeedbackReason, string][]).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </label>
          )}
          {routingAnalytics && routingAnalytics.summary.run_count > 0 && (
            <div className="flex min-h-5 min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-gray-400">
              <BarChart3 className="h-3.5 w-3.5 shrink-0" />
              <span className="shrink-0">最近 {routingAnalytics.summary.run_count} 次</span>
              <span
                className={`shrink-0 font-medium ${
                  routingAnalytics.summary.operational_success_rate >= 90
                    ? 'text-green-600 dark:text-green-500'
                    : routingAnalytics.summary.operational_success_rate >= 60
                      ? 'text-amber-600 dark:text-amber-500'
                      : 'text-red-500'
                }`}
                title="终态运行的执行成功率，不代表回答质量"
              >
                执行成功 {routingAnalytics.summary.operational_success_rate}%
              </span>
              <span className="shrink-0 tabular-nums">
                平均 {formatDuration(routingAnalytics.summary.average_duration_ms)}
              </span>
              <span className="shrink-0 tabular-nums">
                预算 {routingAnalytics.summary.tool_budget_utilization}%
              </span>
              {routingAnalytics.summary.retry_run_count > 0 && (
                <span className="shrink-0 tabular-nums">重试 {routingAnalytics.summary.retry_rate}%</span>
              )}
              {routingAnalytics.summary.rated_run_count > 0 && (
                <span className="shrink-0 tabular-nums text-teal-600 dark:text-teal-400">
                  满意 {routingAnalytics.summary.user_satisfaction_rate}% · {routingAnalytics.summary.rated_run_count} 份
                </span>
              )}
              <div className="flex h-1.5 min-w-16 flex-1 overflow-hidden rounded-sm bg-gray-200 dark:bg-gray-700" aria-label="Agent 等级样本分布">
                {(['fast', 'standard', 'expert'] as const).map((tier) => {
                  const count = routingAnalytics.summary.tier_counts[tier];
                  if (!count) return null;
                  return (
                    <span
                      key={tier}
                      title={`${tierLabels[tier]} ${count}`}
                      className={tier === 'fast' ? 'bg-emerald-500' : tier === 'standard' ? 'bg-blue-500' : 'bg-amber-500'}
                      style={{ width: `${count * 100 / routingAnalytics.summary.run_count}%` }}
                    />
                  );
                })}
              </div>
            </div>
          )}
          {routingAnalytics && (
            routingAnalytics.recommendation_report.items.length > 0 ? (
              <div className="space-y-1 text-[10px] text-gray-400">
                {routingAnalytics.recommendation_report.items.slice(0, 3).map((item) => (
                  <div
                    key={`${item.tier}-${item.route}-${item.planning_source}`}
                    className="flex min-h-5 min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5"
                  >
                    <Lightbulb className={`h-3.5 w-3.5 shrink-0 ${
                      item.action === 'keep_policy'
                        ? 'text-green-600'
                        : item.action === 'investigate_reliability'
                          ? 'text-red-500'
                          : 'text-amber-500'
                    }`} />
                    <span className="font-medium text-gray-600 dark:text-gray-300">
                      {tierLabels[item.tier]} · {recommendationLabels[item.action]}
                    </span>
                    <span>{confidenceLabels[item.confidence]}</span>
                    <span>
                      {item.reason_codes.map((reason) => recommendationReasonLabels[reason] || reason).join(' · ')}
                    </span>
                    <span className="tabular-nums">
                      成功 {item.evidence.operational_success_rate}%
                      {item.evidence.rated_run_count > 0 && ` · 满意 ${item.evidence.user_satisfaction_rate}%`}
                    </span>
                  </div>
                ))}
                {routingAnalytics.recommendation_report.items.length > 3 && (
                  <p className="ml-5">另有 {routingAnalytics.recommendation_report.items.length - 3} 条建议</p>
                )}
                {!routingAnalytics.recommendation_report.readiness.feedback_ready && (
                  <p className="ml-5 tabular-nums">
                    质量建议样本 {routingAnalytics.recommendation_report.readiness.rated_run_count}/{routingAnalytics.recommendation_report.readiness.minimum_rated_runs}
                  </p>
                )}
              </div>
            ) : (
              <div className="flex min-h-5 min-w-0 flex-wrap items-center gap-x-2 text-[10px] text-gray-400">
                <Lightbulb className="h-3.5 w-3.5 shrink-0" />
                <span className="tabular-nums">
                  运行样本 {routingAnalytics.recommendation_report.readiness.terminal_run_count}/{routingAnalytics.recommendation_report.readiness.minimum_terminal_runs}
                </span>
                <span className="tabular-nums">
                  反馈样本 {routingAnalytics.recommendation_report.readiness.rated_run_count}/{routingAnalytics.recommendation_report.readiness.minimum_rated_runs}
                </span>
              </div>
            )
          )}
          {runSnapshot?.error_message && (
            <p className="text-[10px] leading-4 text-red-500">
              {runSnapshot.error_message}
            </p>
          )}
          {!!goalNodes.length && (
            <div className="flex min-h-5 items-center gap-2 text-[10px] text-gray-400">
              <Target className="h-3.5 w-3.5 shrink-0" />
              <div
                className="h-1.5 min-w-16 flex-1 overflow-hidden rounded-sm bg-gray-200 dark:bg-gray-700"
                role="progressbar"
                aria-label="目标执行进度"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={goalProgress}
              >
                <div
                  className={`h-full transition-[width] ${goalProgress === 100 ? 'bg-green-600' : 'bg-blue-600'}`}
                  style={{ width: `${goalProgress}%` }}
                />
              </div>
              <span className="shrink-0 tabular-nums">
                {terminalGoalCount}/{goalNodes.length} · {goalProgress}%
              </span>
              {retryAttempts > 0 && <span className="shrink-0">重试 {retryAttempts}</span>}
            </div>
          )}
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
                {routeSelection.model_name && (
                  <span
                    className="max-w-36 shrink truncate text-[10px] text-gray-400"
                    title={`${routeSelection.model_provider}: ${routeSelection.model_name}`}
                  >
                    {routeSelection.model_name}
                  </span>
                )}
                <Check className="h-3.5 w-3.5 shrink-0 text-green-600" />
              </div>
              <div className="ml-5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[10px] text-gray-400">
                {!!routeSelection.reasons.length && (
                  <span>{routeSelection.reasons.map((reason) => reasonLabels[reason] || reason).join(' · ')}</span>
                )}
                <span className="tabular-nums">
                  层级 {observedMaxDepth}/{routeSelection.max_depth} · 分支 {observedMaxChildren}/{routeSelection.max_children}
                </span>
              </div>
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
