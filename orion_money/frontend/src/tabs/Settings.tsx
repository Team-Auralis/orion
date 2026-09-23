import { useState } from 'react';
import { api, ApiError } from '../lib/api';
import { useFetch } from '../hooks/useFetch';
import Panel from '../components/Panel';
import Badge from '../components/Badge';
import ErrorNote from '../components/ErrorNote';
import Spinner from '../components/Spinner';
import type { HealthResponse, KillSwitchResult, StatusResponse } from '../types';

export default function Settings() {
  const status = useFetch(() => api.get<StatusResponse>('/status'));
  const health = useFetch(() => api.get<HealthResponse>('/health'));
  const [busy, setBusy] = useState<'kill' | 'lift' | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const engage = async () => {
    const reason = window.prompt(
      'Engage the ORION kill switch? Every financial endpoint will 403 until lifted.\n\nReason (optional):',
      'engaged via dashboard',
    );
    if (reason === null) return; // cancelled
    setBusy('kill');
    setError(null);
    try {
      const r = await api.post<KillSwitchResult>('/kill', { reason });
      setResult(`kill switch ${r.active ? 'engaged' : 'already off'} (reason: ${r.reason || '—'})`);
      status.reload();
    } catch (err) {
      setError(err instanceof ApiError ? `${err.message} ${err.reasons.join('; ')}` : String(err));
    } finally {
      setBusy(null);
    }
  };

  const lift = async () => {
    const reason = window.prompt('Lift the kill switch?\n\nReason (optional):', 'all clear');
    if (reason === null) return;
    setBusy('lift');
    setError(null);
    try {
      const r = await api.post<KillSwitchResult>('/kill/lift', { reason });
      setResult(`kill switch ${r.active ? 'still active' : 'lifted'} (reason: ${r.reason || '—'})`);
      status.reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  const s = status.data;

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Panel title="Runtime status" actions={<Badge tone="cyan">GET /api/status</Badge>}>
        {status.error ? (
          <ErrorNote message={status.error} />
        ) : !s ? (
          <Spinner />
        ) : (
          <div className="space-y-2 text-sm">
            <Row k="mode" v={s.mode} />
            <Row
              k="kill switch"
              v={s.kill_switch_active ? 'ACTIVE' : 'inactive'}
              tone={s.kill_switch_active ? 'red' : 'green'}
            />
            {s.kill_switch_active && s.kill_switch_reason && (
              <Row k="kill reason" v={s.kill_switch_reason} />
            )}
            <Row k="model" v={`${s.model_status}`} sub={s.model_detail} />
            <Row k="database" v={s.db_ok ? 'ok' : 'DOWN'} />
            <Row k="uptime" v={`${Math.floor(s.uptime_s / 60)}m ${s.uptime_s % 60}s`} />
          </div>
        )}
      </Panel>

      <Panel title="Health checks" actions={<Badge tone="cyan">GET /api/health</Badge>}>
        {health.error ? (
          <ErrorNote message={health.error} />
        ) : !health.data ? (
          <Spinner />
        ) : (
          <>
            <div className="space-y-2 text-sm">
              {Object.entries(health.data.checks).map(([k, v]) => (
                <Row
                  key={k}
                  k={k}
                  v={v}
                  tone={v === 'pass' || v === 'ok' || v === 'inactive' ? 'green' : v === 'fail' || v === 'active' ? 'red' : undefined}
                />
              ))}
            </div>
            <div className="mt-3 text-[11px] text-slate-500">
              overall: <span className={health.data.ok ? 'text-emerald-300' : 'text-rose-300'}>
                {health.data.ok ? 'ok' : 'degraded'}
              </span>
            </div>
          </>
        )}
      </Panel>

      <Panel
        title="Kill switch"
        actions={<Badge tone={s?.kill_switch_active ? 'red' : 'green'}>{s?.kill_switch_active ? 'ACTIVE' : 'inactive'}</Badge>}
        className="lg:col-span-2"
      >
        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={() => void engage()}
            disabled={busy !== null || s?.kill_switch_active}
            className="rounded-lg bg-rose-400/15 px-4 py-2 text-sm font-semibold text-rose-200 transition hover:bg-rose-400/25 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy === 'kill' ? 'engaging…' : 'Engage kill switch'}
          </button>
          <button
            onClick={() => void lift()}
            disabled={busy !== null || !s?.kill_switch_active}
            className="rounded-lg bg-emerald-400/15 px-4 py-2 text-sm font-semibold text-emerald-200 transition hover:bg-emerald-400/25 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy === 'lift' ? 'lifting…' : 'Lift kill switch'}
          </button>
          <span className="text-xs text-slate-500">
            hard circuit breaker — POST /api/kill · POST /api/kill/lift · engages instantly,
            persists in the DB
          </span>
        </div>
        {error && (
          <div className="mt-3">
            <ErrorNote message={error} />
          </div>
        )}
        {result && (
          <div className="mt-3 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs text-slate-300">
            {result}
          </div>
        )}
      </Panel>
    </div>
  );
}

function Row({
  k,
  v,
  sub,
  tone,
}: {
  k: string;
  v: string;
  sub?: string;
  tone?: 'red' | 'green';
}) {
  const color = tone === 'red' ? 'text-rose-300' : tone === 'green' ? 'text-emerald-300' : '';
  return (
    <div className="flex items-center justify-between gap-3 border-b border-white/5 pb-1.5 last:border-0">
      <div>
        <div className="text-xs uppercase tracking-widest text-slate-500">{k}</div>
        {sub && <div className="text-[11px] text-slate-500">{sub}</div>}
      </div>
      <span className={`font-mono text-xs ${color || 'text-slate-200'}`}>{v}</span>
    </div>
  );
}