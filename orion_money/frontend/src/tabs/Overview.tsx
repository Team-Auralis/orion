import { api } from '../lib/api';
import { useFetch } from '../hooks/useFetch';
import Panel from '../components/Panel';
import StatCard from '../components/StatCard';
import Badge from '../components/Badge';
import ErrorNote from '../components/ErrorNote';
import Spinner from '../components/Spinner';
import type {
  ApprovalsResponse,
  LedgerResponse,
  OpportunitiesResponse,
  StatusResponse,
  StrategiesResponse,
} from '../types';

const ACTIVE_STATUSES = new Set(['SCORED', 'PENDING', 'APPROVED']);

const AUTONOMY_TONE = {
  ENABLED: 'green',
  APPROVAL: 'amber',
  BLOCKED: 'red',
} as const;

export default function Overview() {
  const status = useFetch(() => api.get<StatusResponse>('/status'));
  const ledger = useFetch(() => api.get<LedgerResponse>('/ledger'));
  const strategies = useFetch(() => api.get<StrategiesResponse>('/strategies'));
  const opportunities = useFetch(() => api.get<OpportunitiesResponse>('/opportunities'));
  const approvals = useFetch(() =>
    api.get<ApprovalsResponse>('/approvals?status=pending'),
  );

  const summary = ledger.data?.summary ?? null;

  // Progress to the configured target: verified capital / target (paise).
  // Pending revenue never counts — only realised (deposited) capital does.
  const target = summary?.target_paise ?? 0;
  const progressRatio = target > 0 ? (summary?.capital ?? 0) / target : 0;
  const progressPct = Math.min(100, Math.round(progressRatio * 1000) / 10);

  const activeStrategies =
    strategies.data?.strategies.filter((s) => s.status === 'ACTIVE').length ?? null;
  const activeOpportunities =
    opportunities.data?.opportunities.filter((o) => ACTIVE_STATUSES.has(o.status)).length ??
    null;
  const pendingApprovals = approvals.data?.count ?? null;

  return (
    <div className="space-y-6">
      <Panel title="Capital" actions={<Badge tone="cyan">from /api/ledger</Badge>}>
        {ledger.error ? (
          <ErrorNote message={ledger.error} />
        ) : !summary ? (
          <Spinner />
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              <StatCard label="Capital" value={summary.capital_formatted} sub={summary.currency} />
              <StatCard
                label="Available"
                value={summary.available_cash_formatted}
                sub="usable right now"
              />
              <StatCard
                label="Reserved"
                value={summary.reserved_cash_formatted}
                sub="committed to pending spends"
              />
              <StatCard
                label="Spent"
                value={summary.spent_formatted}
                sub="gross spend"
                tone="warn"
              />
              <StatCard
                label="Verified revenue"
                value={summary.verified_revenue_formatted}
                sub="confirmed inflow only"
                tone="good"
              />
              <StatCard
                label="Net profit"
                value={summary.net_profit_formatted}
                sub="verified revenue − spent − fees + refunds"
                tone={summary.net_profit >= 0 ? 'good' : 'bad'}
              />
            </div>

            <div>
              <div className="mb-1 flex items-baseline justify-between text-xs">
                <span className="uppercase tracking-widest text-slate-400">
                  Progress to target
                </span>
                <span className="mono-num text-slate-300">
                  {summary.capital_formatted} of {summary.target_paise_formatted} ·{' '}
                  {progressPct}%
                </span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-white/10">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-blue-500 to-cyan-400 transition-all"
                  style={{ width: `${progressPct}%` }}
                />
              </div>
              <p className="mt-1 text-[11px] text-slate-500">
                formula: verified capital ÷ target (₹10,000 by default) — pending revenue is
                never counted
              </p>
            </div>
          </div>
        )}
      </Panel>

      <div className="grid gap-4 sm:grid-cols-3">
        <Panel title="Strategies (active)">
          {strategies.error ? (
            <ErrorNote message={strategies.error} />
          ) : activeStrategies === null ? (
            <Spinner />
          ) : (
            <div className="mono-num text-2xl font-semibold text-cyan-300">
              {activeStrategies}
              <span className="ml-2 text-xs font-normal text-slate-400">
                of {strategies.data?.count ?? 0} total
              </span>
            </div>
          )}
        </Panel>
        <Panel title="Active opportunities">
          {opportunities.error ? (
            <ErrorNote message={opportunities.error} />
          ) : activeOpportunities === null ? (
            <Spinner />
          ) : (
            <div className="mono-num text-2xl font-semibold text-blue-300">
              {activeOpportunities}
            </div>
          )}
        </Panel>
        <Panel title="Pending approvals">
          {approvals.error ? (
            <ErrorNote message={approvals.error} />
          ) : pendingApprovals === null ? (
            <Spinner />
          ) : (
            <div className="mono-num text-2xl font-semibold text-amber-300">
              {pendingApprovals}
            </div>
          )}
        </Panel>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Runtime" actions={<Badge tone="cyan">from /api/status</Badge>}>
          {status.error ? (
            <ErrorNote message={status.error} />
          ) : !status.data ? (
            <Spinner />
          ) : (
            <div className="space-y-2 text-sm">
              <Row k="mode" v={status.data.mode} />
              <Row
                k="kill switch"
                v={status.data.kill_switch_active ? 'ACTIVE' : 'inactive'}
                tone={status.data.kill_switch_active ? 'red' : 'green'}
              />
              {status.data.kill_switch_active && status.data.kill_switch_reason && (
                <Row k="kill reason" v={status.data.kill_switch_reason} />
              )}
              <Row k="model" v={`${status.data.model_status} — ${status.data.model_detail}`} />
              <Row k="database" v={status.data.db_ok ? 'ok' : 'DOWN'} />
              <Row k="uptime" v={`${Math.floor(status.data.uptime_s / 60)}m`} />
            </div>
          )}
        </Panel>

        <Panel title="Autonomy meter">
          {status.error ? (
            <ErrorNote message={status.error} />
          ) : !status.data ? (
            <Spinner />
          ) : (
            <div className="grid grid-cols-2 gap-2">
              {Object.entries(status.data.autonomy).map(([capability, level]) => (
                <div
                  key={capability}
                  className="flex items-center justify-between rounded-xl border border-white/10 bg-deep/60 px-3 py-2"
                >
                  <span className="text-sm text-slate-300">{capability}</span>
                  <Badge tone={AUTONOMY_TONE[level]}>{level}</Badge>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}

function Row({
  k,
  v,
  tone,
}: {
  k: string;
  v: string;
  tone?: 'red' | 'green';
}) {
  const color = tone === 'red' ? 'text-rose-300' : tone === 'green' ? 'text-emerald-300' : '';
  return (
    <div className="flex items-center justify-between border-b border-white/5 pb-1.5 last:border-0">
      <span className="text-xs uppercase tracking-widest text-slate-500">{k}</span>
      <span className={`font-mono text-xs ${color || 'text-slate-200'}`}>{v}</span>
    </div>
  );
}