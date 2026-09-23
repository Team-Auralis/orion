import { useState } from 'react';
import { api, ApiError } from '../lib/api';
import { useFetch } from '../hooks/useFetch';
import Panel from '../components/Panel';
import Badge from '../components/Badge';
import ErrorNote from '../components/ErrorNote';
import Spinner from '../components/Spinner';
import type { OpportunitiesResponse, ScanResult } from '../types';

function statusTone(status: string) {
  switch (status) {
    case 'SCORED':
      return 'cyan' as const;
    case 'PENDING':
      return 'amber' as const;
    case 'APPROVED':
      return 'green' as const;
    case 'REJECTED':
      return 'red' as const;
    default:
      return 'slate' as const;
  }
}

export default function Opportunities() {
  const [statusFilter, setStatusFilter] = useState('');
  const [scanning, setScanning] = useState(false);
  const [scanResult, setScanResult] = useState<ScanResult | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const opps = useFetch(() =>
    api.get<OpportunitiesResponse>(
      statusFilter ? `/opportunities?status=${statusFilter}&limit=200` : '/opportunities?limit=200',
    ),
  );

  const runScan = async () => {
    setScanning(true);
    setActionError(null);
    try {
      const r = await api.post<ScanResult>('/opportunities/scan');
      setScanResult(r);
      opps.reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? `${err.message} ${err.reasons.join('; ')}` : String(err));
    } finally {
      setScanning(false);
    }
  };

  return (
    <Panel
      title="Opportunities"
      actions={
        <>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="rounded-lg border border-white/10 bg-deep px-2 py-1 text-xs text-slate-200 outline-none focus:border-cyan-400/60"
          >
            <option value="">all statuses</option>
            <option value="DISCOVERED">DISCOVERED</option>
            <option value="SCORED">SCORED</option>
            <option value="PENDING">PENDING</option>
            <option value="APPROVED">APPROVED</option>
            <option value="REJECTED">REJECTED</option>
          </select>
          <button
            onClick={runScan}
            disabled={scanning}
            className="rounded-lg bg-cyan-400/15 px-3 py-1.5 text-xs font-semibold text-cyan-200 transition hover:bg-cyan-400/25 disabled:opacity-50"
          >
            {scanning ? 'scanning…' : 'Scan now'}
          </button>
        </>
      }
    >
      {actionError && (
        <div className="mb-3">
          <ErrorNote message={actionError} />
        </div>
      )}
      {scanResult && (
        <div className="mb-3 text-xs text-slate-400">
          scan complete — {scanResult.created} new, {scanResult.scored} scored,{' '}
          {scanResult.total} total (POST /api/opportunities/scan)
        </div>
      )}

      {opps.error ? (
        <ErrorNote message={opps.error} />
      ) : !opps.data ? (
        <Spinner />
      ) : opps.data.count === 0 ? (
        <div className="text-sm text-slate-500">
          no opportunities — run a scan first
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-white/10">
          <table className="w-full min-w-[56rem] text-left text-sm">
            <thead>
              <tr className="border-b border-white/10 text-[11px] uppercase tracking-widest text-slate-500">
                <th className="px-3 py-2">Opportunity</th>
                <th className="px-3 py-2">Score</th>
                <th className="px-3 py-2">Value</th>
                <th className="px-3 py-2">Cost</th>
                <th className="px-3 py-2">Risk</th>
                <th className="px-3 py-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {opps.data.opportunities.map((o) => (
                <tr key={o.id} className="border-b border-white/5 last:border-0 hover:bg-white/5">
                  <td className="px-3 py-2">
                    <div className="text-slate-200">{o.name}</div>
                    <div className="max-w-[26rem] truncate text-xs text-slate-500">
                      {o.description}
                    </div>
                  </td>
                  <td className="mono-num px-3 py-2 text-slate-200">
                    {o.score_0_100 != null ? o.score_0_100.toFixed(1) : '—'}
                  </td>
                  <td className="mono-num px-3 py-2 text-emerald-300">
                    {o.estimated_value_formatted}
                  </td>
                  <td className="mono-num px-3 py-2 text-amber-300">{o.cost_formatted}</td>
                  <td className="px-3 py-2">
                    {o.suspicious ? (
                      <Badge tone="red">SUSPICIOUS</Badge>
                    ) : o.status === 'REJECTED' ? (
                      <Badge tone="amber">REJECTED</Badge>
                    ) : (
                      <span className="text-slate-600">—</span>
                    )}
                    {(o.suspicious_reason || o.rejected_reason) && (
                      <div className="mt-0.5 max-w-[16rem] truncate text-[11px] text-slate-500">
                        {o.suspicious_reason ?? o.rejected_reason}
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <Badge tone={statusTone(o.status)}>{o.status}</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}