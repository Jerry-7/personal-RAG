import { useEffect, useState } from 'react';
import { Check, Loader2, RotateCcw, Save } from 'lucide-react';
import {
  createRoutingPolicy,
  getRoutingPolicies,
  getRoutingPolicyEvaluation,
  rollbackRoutingPolicy,
  simulateRoutingPolicy,
} from '../../api/routingPolicies';
import type {
  RoutingPolicyEvaluation,
  RoutingPolicyReport,
  RoutingPolicySimulation,
} from '../../types/routingPolicy';
import { RoutingPolicyEvaluationPanel } from './RoutingPolicyEvaluationPanel';


const sourceLabels = {
  default: '默认',
  manual: '手动',
  rollback: '回滚',
} as const;

function formatCreatedAt(value: string | null): string {
  if (!value) return '内置策略';
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value));
}

export function RoutingPolicySettings() {
  const [report, setReport] = useState<RoutingPolicyReport | null>(null);
  const [evaluation, setEvaluation] = useState<RoutingPolicyEvaluation | null>(null);
  const [simulation, setSimulation] = useState<RoutingPolicySimulation | null>(null);
  const [standardMin, setStandardMin] = useState(2);
  const [expertMin, setExpertMin] = useState(4);
  const [note, setNote] = useState('');
  const [pending, setPending] = useState<'create' | number | null>(null);
  const [isSimulating, setIsSimulating] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const refresh = async () => {
    const [next, nextEvaluation] = await Promise.all([
      getRoutingPolicies(),
      getRoutingPolicyEvaluation(),
    ]);
    setReport(next);
    setEvaluation(nextEvaluation);
    setSimulation(nextEvaluation.simulation);
    setStandardMin(next.current.standard_min_score);
    setExpertMin(next.current.expert_min_score);
    return next;
  };

  const simulate = async () => {
    if (!valid || isSimulating) return;
    setIsSimulating(true);
    setMessage(null);
    try {
      setSimulation(await simulateRoutingPolicy(standardMin, expertMin));
    } catch (error) {
      console.error('模拟路由策略失败', error);
      setMessage('模拟失败，请检查阈值和服务状态');
    } finally {
      setIsSimulating(false);
    }
  };

  useEffect(() => {
    refresh().catch((error) => {
      console.error('加载路由策略失败', error);
      setMessage('加载路由策略失败');
    });
  }, []);

  const activate = async () => {
    if (!report || pending !== null) return;
    setPending('create');
    setMessage(null);
    try {
      await createRoutingPolicy({
        standard_min_score: standardMin,
        expert_min_score: expertMin,
        expected_active_version: report.current.version,
        note: note.trim() || undefined,
      });
      const next = await refresh();
      setNote('');
      setMessage(`策略 v${next.current.version} 已激活`);
    } catch (error) {
      console.error('激活路由策略失败', error);
      await refresh().catch(() => undefined);
      setMessage('策略未保存，当前版本已刷新');
    } finally {
      setPending(null);
    }
  };

  const rollback = async (version: number) => {
    if (!report || pending !== null || version === report.current.version) return;
    setPending(version);
    setMessage(null);
    try {
      await rollbackRoutingPolicy(version, {
        expected_active_version: report.current.version,
        note: `恢复策略 v${version}`,
      });
      const next = await refresh();
      setMessage(`已创建回滚策略 v${next.current.version}`);
    } catch (error) {
      console.error('回滚路由策略失败', error);
      await refresh().catch(() => undefined);
      setMessage('回滚未执行，当前版本已刷新');
    } finally {
      setPending(null);
    }
  };

  if (!report) {
    return (
      <div className="flex min-h-40 items-center justify-center text-sm text-gray-400">
        {message || <Loader2 className="h-5 w-5 animate-spin" />}
      </div>
    );
  }

  const valid = standardMin >= 1 && standardMin < expertMin && expertMin <= 10;
  const changed = standardMin !== report.current.standard_min_score
    || expertMin !== report.current.expert_min_score;
  const versions = report.versions.some((item) => item.version === 0)
    ? report.versions
    : [
        ...report.versions,
        {
          version: 0,
          standard_min_score: 2,
          expert_min_score: 4,
          source: 'default' as const,
          based_on_version: null,
          note: null,
          is_active: report.current.version === 0,
          created_at: null,
        },
      ];

  return (
    <div className="space-y-5">
      <section className="space-y-3">
        <div className="flex min-h-7 items-center justify-between gap-3 border-b border-gray-200 pb-2 dark:border-gray-700">
          <div className="min-w-0">
            <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
              当前策略 v{report.current.version}
            </p>
            <p className="text-[11px] text-gray-400">
              {sourceLabels[report.current.source]} · {formatCreatedAt(report.current.created_at)}
            </p>
          </div>
          <Check className="h-4 w-4 shrink-0 text-green-600" />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <label className="min-w-0">
            <span className="mb-1 block text-xs font-medium text-gray-500">标准 Agent 起始分数</span>
            <input
              type="number"
              min={1}
              max={9}
              value={standardMin}
              onChange={(event) => setStandardMin(Number(event.target.value))}
              className="h-9 w-full rounded border border-gray-300 bg-white px-2 text-sm dark:border-gray-600 dark:bg-gray-800"
            />
          </label>
          <label className="min-w-0">
            <span className="mb-1 block text-xs font-medium text-gray-500">专家 Agent 起始分数</span>
            <input
              type="number"
              min={2}
              max={10}
              value={expertMin}
              onChange={(event) => setExpertMin(Number(event.target.value))}
              className="h-9 w-full rounded border border-gray-300 bg-white px-2 text-sm dark:border-gray-600 dark:bg-gray-800"
            />
          </label>
        </div>

        <div className="flex min-h-6 flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-gray-500">
          <span>快速 0-{Math.max(0, standardMin - 1)}</span>
          <span>标准 {standardMin}-{Math.max(standardMin, expertMin - 1)}</span>
          <span>专家 {expertMin}+</span>
        </div>

        <div className="flex gap-2">
          <input
            value={note}
            maxLength={512}
            onChange={(event) => setNote(event.target.value)}
            placeholder="版本备注"
            className="h-9 min-w-0 flex-1 rounded border border-gray-300 bg-white px-2 text-sm dark:border-gray-600 dark:bg-gray-800"
          />
          <button
            type="button"
            onClick={activate}
            disabled={!valid || !changed || pending !== null}
            className="flex h-9 shrink-0 items-center gap-1.5 rounded bg-blue-600 px-3 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-40"
          >
            {pending === 'create' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
            激活新版本
          </button>
        </div>
        {message && <p className="text-xs text-gray-500">{message}</p>}
      </section>

      <RoutingPolicyEvaluationPanel
        evaluation={evaluation}
        simulation={simulation}
        isSimulating={isSimulating}
        canSimulate={valid}
        onSimulate={simulate}
      />

      <section>
        <h3 className="mb-2 text-xs font-medium text-gray-500">版本历史</h3>
        <div className="divide-y divide-gray-200 border-y border-gray-200 dark:divide-gray-700 dark:border-gray-700">
          {versions.map((item) => (
            <div key={item.version} className="flex min-h-12 items-center gap-3 py-2">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-x-2 text-xs text-gray-700 dark:text-gray-300">
                  <span className="font-medium">v{item.version}</span>
                  <span>{sourceLabels[item.source]}</span>
                  <span className="tabular-nums">标准 {item.standard_min_score} · 专家 {item.expert_min_score}</span>
                  {item.is_active && <span className="text-green-600">已激活</span>}
                </div>
                <p className="mt-0.5 truncate text-[10px] text-gray-400" title={item.note || undefined}>
                  {formatCreatedAt(item.created_at)}{item.note ? ` · ${item.note}` : ''}
                </p>
              </div>
              {!item.is_active && (
                <button
                  type="button"
                  title={`恢复策略 v${item.version}`}
                  onClick={() => rollback(item.version)}
                  disabled={pending !== null}
                  className="flex h-8 w-8 shrink-0 items-center justify-center rounded hover:bg-gray-100 disabled:opacity-40 dark:hover:bg-gray-800"
                >
                  {pending === item.version
                    ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    : <RotateCcw className="h-3.5 w-3.5" />}
                </button>
              )}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
