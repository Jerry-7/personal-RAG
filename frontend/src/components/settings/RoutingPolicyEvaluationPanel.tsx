import {
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  CircleDashed,
  GitCompare,
  GitFork,
  Loader2,
  RotateCcw,
} from 'lucide-react';
import type {
  RoutingPolicyEvaluation,
  RoutingPolicyExperiment,
  RoutingPolicySimulation,
  RoutingTier,
} from '../../types/routingPolicy';


const tierLabels: Record<RoutingTier, string> = {
  fast: '快速',
  standard: '标准',
  expert: '专家',
};
const tiers: RoutingTier[] = ['fast', 'standard', 'expert'];
const experimentStatusLabels: Record<RoutingPolicyExperiment['status'], string> = {
  not_applicable: '无试验基线',
  collecting: '采集运行样本',
  awaiting_feedback: '等待质量反馈',
  operational_alert: '运行指标告警',
  ready: '样本已就绪',
};
const recommendationLabels: Record<RoutingPolicyExperiment['recommendation'], string> = {
  not_applicable: '无需评估',
  collect_runs: '继续收集运行',
  collect_feedback: '继续收集反馈',
  rollback: '建议回滚',
  keep: '建议保留',
  review: '需要人工复核',
};

function formatDuration(durationMs: number | null): string {
  if (durationMs === null) return '--';
  if (durationMs < 1000) return `${durationMs}ms`;
  return `${(durationMs / 1000).toFixed(1)}s`;
}

function formatDelta(value: number | null, suffix = 'pp'): string {
  if (value === null) return '--';
  return `${value > 0 ? '+' : ''}${value}${suffix}`;
}

function ExperimentSummary({ experiment }: { experiment: RoutingPolicyExperiment }) {
  const RecommendationIcon = experiment.recommendation === 'keep'
    ? CheckCircle2
    : experiment.recommendation === 'rollback'
      ? RotateCcw
      : experiment.status === 'operational_alert'
        ? AlertTriangle
        : CircleDashed;
  const recommendationColor = experiment.recommendation === 'keep'
    ? 'text-green-600'
    : experiment.recommendation === 'rollback'
      ? 'text-red-500'
      : experiment.recommendation === 'review'
        ? 'text-amber-600'
        : 'text-gray-500';
  const runProgress = Math.min(
    100,
    experiment.readiness.terminal_run_count * 100 / experiment.readiness.minimum_terminal_runs,
  );
  const feedbackProgress = Math.min(
    100,
    experiment.readiness.rated_run_count * 100 / experiment.readiness.minimum_rated_runs,
  );

  return (
    <div className="space-y-2 border-y border-gray-200 py-2 dark:border-gray-700">
      <div className="flex min-h-6 flex-wrap items-center gap-x-3 gap-y-1 text-[10px]">
        <GitCompare className="h-3.5 w-3.5 shrink-0 text-gray-400" />
        <span className="font-medium text-gray-600 dark:text-gray-300">
          策略 v{experiment.current_policy_version}
          {experiment.baseline_policy_version !== null && ` 对比 v${experiment.baseline_policy_version}`}
        </span>
        <span className="text-gray-400">{experimentStatusLabels[experiment.status]}</span>
        <span className={`flex items-center gap-1 font-medium ${recommendationColor}`}>
          <RecommendationIcon className="h-3 w-3" />
          {recommendationLabels[experiment.recommendation]}
        </span>
      </div>

      {experiment.status !== 'not_applicable' && (
        <>
          <div className="grid grid-cols-2 gap-3 text-[10px] text-gray-500">
            <div className="min-w-0">
              <div className="mb-1 flex justify-between gap-2 tabular-nums">
                <span>终态运行</span>
                <span>{experiment.readiness.terminal_run_count}/{experiment.readiness.minimum_terminal_runs}</span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-sm bg-gray-200 dark:bg-gray-700">
                <div className="h-full bg-blue-600" style={{ width: `${runProgress}%` }} />
              </div>
            </div>
            <div className="min-w-0">
              <div className="mb-1 flex justify-between gap-2 tabular-nums">
                <span>质量反馈</span>
                <span>{experiment.readiness.rated_run_count}/{experiment.readiness.minimum_rated_runs}</span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-sm bg-gray-200 dark:bg-gray-700">
                <div className="h-full bg-teal-600" style={{ width: `${feedbackProgress}%` }} />
              </div>
            </div>
          </div>
          <div className="flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-gray-400">
            <span>成功率 {formatDelta(experiment.comparison.operational_success_rate_delta)}</span>
            <span>平均耗时 {formatDelta(experiment.comparison.average_duration_ms_delta, 'ms')}</span>
            <span>工具失败 {formatDelta(experiment.comparison.tool_failure_rate_delta)}</span>
            <span>满意度 {formatDelta(experiment.comparison.user_satisfaction_rate_delta)}</span>
          </div>
        </>
      )}
    </div>
  );
}

interface RoutingPolicyEvaluationPanelProps {
  evaluation: RoutingPolicyEvaluation | null;
  simulation: RoutingPolicySimulation | null;
  isSimulating: boolean;
  canSimulate: boolean;
  onSimulate: () => void;
}

export function RoutingPolicyEvaluationPanel({
  evaluation,
  simulation,
  isSimulating,
  canSimulate,
  onSimulate,
}: RoutingPolicyEvaluationPanelProps) {
  if (!evaluation || !simulation) {
    return (
      <div className="flex min-h-32 items-center justify-center text-gray-400">
        <Loader2 className="h-4 w-4 animate-spin" />
      </div>
    );
  }

  return (
    <section className="space-y-3 border-t border-gray-200 pt-4 dark:border-gray-700">
      <div className="flex min-h-6 items-center justify-between gap-3">
        <h3 className="flex items-center gap-2 text-xs font-medium text-gray-500">
          <BarChart3 className="h-3.5 w-3.5" />
          策略效果评估
        </h3>
        <button
          type="button"
          onClick={onSimulate}
          disabled={isSimulating || !canSimulate}
          className="flex h-7 items-center gap-1.5 rounded border border-gray-300 px-2 text-[11px] text-gray-600 hover:bg-gray-50 disabled:opacity-40 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-800"
        >
          {isSimulating
            ? <Loader2 className="h-3 w-3 animate-spin" />
            : <GitFork className="h-3 w-3" />}
          重新模拟
        </button>
      </div>

      <div className="overflow-x-auto border-y border-gray-200 dark:border-gray-700">
        <table className="w-full min-w-[30rem] text-left text-[10px]">
          <thead className="text-gray-400">
            <tr className="h-7">
              <th className="pr-3 font-medium">策略</th>
              <th className="pr-3 font-medium">终态</th>
              <th className="pr-3 font-medium">执行成功</th>
              <th className="pr-3 font-medium">平均耗时</th>
              <th className="pr-3 font-medium">工具失败</th>
              <th className="font-medium">满意度</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
            {evaluation.observed_versions.map((item) => (
              <tr key={item.version} className="h-8 text-gray-600 dark:text-gray-300">
                <td className="pr-3 font-medium">v{item.version}</td>
                <td className="pr-3 tabular-nums">{item.metrics.terminal_run_count}</td>
                <td className="pr-3 tabular-nums">{item.metrics.operational_success_rate}%</td>
                <td className="pr-3 tabular-nums">{formatDuration(item.metrics.average_duration_ms)}</td>
                <td className="pr-3 tabular-nums">{item.metrics.tool_failure_rate}%</td>
                <td className="tabular-nums">
                  {item.metrics.rated_run_count > 0
                    ? `${item.metrics.user_satisfaction_rate}%`
                    : '--'}
                </td>
              </tr>
            ))}
            {evaluation.observed_versions.length === 0 && (
              <tr><td colSpan={6} className="py-3 text-gray-400">暂无运行样本</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <ExperimentSummary experiment={evaluation.experiment} />

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-gray-500">
        <span className="font-medium text-gray-600 dark:text-gray-300">
          模拟标准 {simulation.candidate_policy.standard_min_score} · 专家 {simulation.candidate_policy.expert_min_score}
        </span>
        <span className="tabular-nums">
          可用样本 {simulation.eligibility.eligible_auto_run_count}/{simulation.eligibility.terminal_run_count}
        </span>
        <span className="tabular-nums">重分流 {simulation.changed_run_count}</span>
        <span className="tabular-nums">升级 {simulation.upgrade_run_count}</span>
        <span className="tabular-nums">降级 {simulation.downgrade_run_count}</span>
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-gray-400">
        <span>排除手动 {simulation.eligibility.excluded_manual_override_count}</span>
        <span>排除基线不一致 {simulation.eligibility.excluded_baseline_mismatch_count}</span>
        <span>排除未结束 {simulation.eligibility.excluded_non_terminal_count}</span>
        <span>质量预测 --</span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[26rem] border-collapse text-center text-[10px]">
          <caption className="mb-1 text-left text-gray-400">实际层级 → 模拟层级</caption>
          <thead className="text-gray-400">
            <tr className="h-6">
              <th className="text-left font-medium">实际 \ 模拟</th>
              {tiers.map((tier) => <th key={tier} className="font-medium">{tierLabels[tier]}</th>)}
            </tr>
          </thead>
          <tbody className="text-gray-600 dark:text-gray-300">
            {tiers.map((source) => (
              <tr key={source} className="h-7 border-t border-gray-100 dark:border-gray-800">
                <th className="text-left font-medium">{tierLabels[source]}</th>
                {tiers.map((target) => (
                  <td key={target} className="tabular-nums">{simulation.transitions[source][target]}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
