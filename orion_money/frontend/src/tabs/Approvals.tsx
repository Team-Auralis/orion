import { useState } from 'react';
import { api, ApiError } from '../lib/api';
import { useFetch } from '../hooks/useFetch';
import Panel from '../components/Panel';
import Badge from '../components/Badge';
import ErrorNote from '../components/ErrorNote';
import Spinner from '../components/Spinner';
import type { ApprovalDecisionResult, ApprovalsResponse } from '../types';

export default function Approvals() {
  const pending = useFetch(() => api.get<ApprovalsResponse>('/approvals?status=pending'));
  const history = useFetch(() => api.get<ApprovalsResponse>('/approvals?limit=25'));
  const [busyId, setBusyId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [rejectReasons, setRejectReasons] = useState<Record<number, string>>({});

  const act = async (id: number, kind: 'approve' | 'reject') => {
    setBusyId(id);
    setActionError(null);
    try {
      if (kind === 'approve') {
        await api.post<ApprovalDecisionResult>(`/approvals/${id}/approve`);
      } else {
        const reason = rejectReasons[id]?.trim() || 'rejected via dashboard';
        await api.post<ApprovalDecisionResult>(`/approvals/${id}/reject`, { reason });
      }
      pending.reload();
      history.reload();
    } catch (err) {
      setActionError(
        err instanceof ApiError ? `${err.message} ${err.reasons.join('; ')}` : String(err),
      );
    } finally {
      setBusyId(null);
    }
  };

  const decided = (history.data?.approvals ?? []).filter((a) => a.status !== 'PENDING');

  return (
    <div className="space-y-6">
      <Panel title="Pending approvals" actions={<Badge tone="cyan">GET /api/approvals?status=pending</Badge>}>
        {actionError && (
          <div className="mb-3">
            <ErrorNote message={actionError} />
          </div>
        )}
        {pending.error ? (
          <ErrorNote message={pending.error} />
        ) : !pending.data ? (
          <Spinner />
        ) : pending.data.count === 0 ? (
          <div className="text-sm text-slate-500">
            nothing pending — the queue is clear
          </div>
        ) : (
          <div className="space-y-3">
            {pending.data.approvals.map((a) => (
              <div
                key={a.id}
                className="rounded-xl border border-amber-400/20 bg-deep/60 p-4"
              >
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                  <span className="font-medium text-slate-100">
                    #{a.id} {a.kind} {a.why && <span className="text-slate-400">— {a.why}</span>}
                  </span>
                  <Badge tone="amber">{a.status}</Badge>
                </div>
                <div className="mb-3 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
                  <Info k="cost" v={a.cost_formatted ?? '—'} />
                  <Info
                    k="potential revenue"
                    v={a.potential_revenue_paise != null ? `₹${(a.potential_revenue_paise / 100).toFixed(2)}` : '—'}
                  />
                  <Info k="risk" v={a.risk_level ?? '—'} />
                  <Info k="destination" v={a.destination || '—'} />
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    onClick={() => void act(a.id, 'approve')}
                    disabled={busyId === a.id}
                    className="rounded-lg bg-emerald-400/15 px-3 py-1.5 text-xs font-semibold text-emerald-200 transition hover:bg-emerald-400/25 disabled:opacity-50"
                  >
                    Approve
                  </button>
                  <input
                    value={rejectReasons[a.id] ?? ''}
                    onChange={(e) =>
                      setRejectReasons((r) => ({ ...r, [a.id]: e.target.value }))
                    }
                    placeholder="reject reason"
                    className="w-48 rounded-lg border border-white/10 bg-deep px-2 py-1.5 text-xs text-slate-100 outline-none placeholder:text-slate-500 focus:border-cyan-400/60"
                  />
                  <button
                    onClick={() => void act(a.id, 'reject')}
                    disabled={busyId === a.id}
                    className="rounded-lg bg-rose-400/15 px-3 py-1.5 text-xs font-semibold text-rose-200 transition hover:bg-rose-400/25 disabled:opacity-50"
                  >
                    Reject
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <Panel title="Recent decisions" actions={<Badge tone="cyan">GET /api/approvals</Badge>}>
        {history.error ? (
          <ErrorNote message={history.error} />
        ) : !history.data ? (
          <Spinner />
        ) : decided.length === 0 ? (
          <div className="text-sm text-slate-500">no decided approvals yet</div>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-white/10">
            <table className="w-full min-w-[44rem] text-left text-sm">
              <thead>
                <tr className="border-b border-white/10 text-[11px] uppercase tracking-widest text-slate-500">
                  <th className="px-3 py-2">#</th>
                  <th className="px-3 py-2">Kind</th>
                  <th className="px-3 py-2">Why</th>
                  <th className="px-3 py-2">Cost</th>
                  <th className="px-3 py-2">Decision</th>
                  <th className="px-3 py-2">Reason</th>
                </tr>
              </thead>
              <tbody>
                {decided.map((a) => (
                  <tr key={a.id} className="border-b border-white/5 last:border-0 hover:bg-white/5">
                    <td className="px-3 py-2 text-slate-400">{a.id}</td>
                    <td className="px-3 py-2 text-slate-200">{a.kind}</td>
                    <td className="max-w-[22rem] truncate px-3 py-2 text-slate-400">{a.why}</td>
                    <td className="mono-num px-3 py-2 text-slate-300">{a.cost_formatted ?? '—'}</td>
                    <td className="px-3 py-2">
                      <Badge tone={a.status === 'APPROVED' ? 'green' : a.status === 'REJECTED' ? 'red' : 'slate'}>
                        {a.decision ?? a.status}
                      </Badge>
                    </td>
                    <td className="max-w-[22rem] truncate px-3 py-2 text-slate-400">
                      {a.decision_reason ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}

function Info({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-slate-500">{k}</div>
      <div className="font-mono text-[13px] text-slate-200">{v}</div>
    </div>
  );
}