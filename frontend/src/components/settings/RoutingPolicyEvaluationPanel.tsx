import { BarChart3, GitFork, Loader2 } from 'lucide-react';
import type {
  RoutingPolicyEvaluation,
  RoutingPolicySimulation,
  RoutingTier,
} from '../../types/routingPolicy';


const tierLabels: Record<RoutingTier, string> = {
  fast: '快速',
  standard: '标准',
  expert: '专家',
};
const tiers: RoutingTier[] = ['fast', 'standard', 'expert'];

function formatDuration(durationMs: number | null): string {
  if (durationMs === null) return '--';
  if (durationMs < 1000) return `${durationMs}ms`;
  return `${(durationMs / 1000).toFixed(1)}s`;
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
