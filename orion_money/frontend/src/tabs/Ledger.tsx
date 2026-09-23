import { useState, type ChangeEvent, type FormEvent } from 'react';
import { api, ApiError } from '../lib/api';
import { useFetch } from '../hooks/useFetch';
import Panel from '../components/Panel';
import Badge from '../components/Badge';
import Field from '../components/Field';
import ErrorNote from '../components/ErrorNote';
import Spinner from '../components/Spinner';
import type { LedgerResponse, RevenueResult, SpendResult } from '../types';

type EntryType = LedgerResponse['entries'][number];

function entryTone(type: string) {
  switch (type) {
    case 'REVENUE':
      return 'green' as const;
    case 'SPEND':
      return 'amber' as const;
    case 'RESERVE':
      return 'blue' as const;
    case 'REFUND':
    case 'RELEASE_RESERVE':
      return 'cyan' as const;
    case 'DISPUTE':
      return 'red' as const;
    default:
      return 'slate' as const;
  }
}

export default function Ledger() {
  const ledger = useFetch(() => api.get<LedgerResponse>('/ledger?limit=100'));

  const [rev, setRev] = useState({
    amount_paise: '',
    source: '',
    reference: '',
    verification_method: '',
    confidence: '',
  });
  const [spend, setSpend] = useState({ amount_paise: '', category: '', reason: '' });
  const [busy, setBusy] = useState<'rev' | 'spend' | null>(null);
  const [revResult, setRevResult] = useState<RevenueResult | null>(null);
  const [spendResult, setSpendResult] = useState<SpendResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const setRevField =
    (key: keyof typeof rev) =>
    (e: ChangeEvent<HTMLInputElement>) =>
      setRev((f) => ({ ...f, [key]: e.target.value }));
  const setSpendField =
    (key: keyof typeof spend) =>
    (e: ChangeEvent<HTMLInputElement>) =>
      setSpend((f) => ({ ...f, [key]: e.target.value }));

  const submitRevenue = async (e: FormEvent) => {
    e.preventDefault();
    setBusy('rev');
    setError(null);
    setRevResult(null);
    try {
      const result = await api.post<RevenueResult>('/ledger/revenue', {
        amount_paise: Number(rev.amount_paise),
        source: rev.source,
        reference: rev.reference,
        verification_method: rev.verification_method || null,
        confidence: rev.confidence ? Number(rev.confidence) : 0,
      });
      setRevResult(result);
      setRev((f) => ({ ...f, amount_paise: '', reference: '' }));
      ledger.reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  const submitSpend = async (e: FormEvent) => {
    e.preventDefault();
    setBusy('spend');
    setError(null);
    setSpendResult(null);
    try {
      const result = await api.post<SpendResult>('/ledger/spend', {
        amount_paise: Number(spend.amount_paise),
        category: spend.category,
        reason: spend.reason,
      });
      setSpendResult(result);
      setSpend((f) => ({ ...f, amount_paise: '' }));
      ledger.reload();
    } catch (err) {
      setError(err instanceof ApiError ? `${err.message} ${err.reasons.join('; ')}` : String(err));
    } finally {
      setBusy(null);
    }
  };

  const summary = ledger.data?.summary ?? null;

  return (
    <div className="space-y-6">
      <Panel title="Summary" actions={<Badge tone="cyan">GET /api/ledger</Badge>}>
        {ledger.error ? (
          <ErrorNote message={ledger.error} />
        ) : !summary ? (
          <Spinner />
        ) : (
          <>
            <div className="mb-3 flex flex-wrap gap-2 text-xs">
              <Chip label="capital" value={summary.capital_formatted} />
              <Chip label="available" value={summary.available_cash_formatted} tone="good" />
              <Chip label="reserved" value={summary.reserved_cash_formatted} />
              <Chip label="spent" value={summary.spent_formatted} tone="warn" />
              <Chip label="verified revenue" value={summary.verified_revenue_formatted} tone="good" />
              <Chip label="pending revenue" value={summary.pending_revenue_formatted} />
              <Chip label="fees" value={summary.fees_formatted} />
              <Chip label="refunds" value={summary.refunds_formatted} />
              <Chip
                label="net profit"
                value={summary.net_profit_formatted}
                tone={summary.net_profit >= 0 ? 'good' : 'bad'}
              />
            </div>
            <div className="text-[11px] text-slate-500">
              {summary.entry_count} ledger entries · every value is integer paise, displayed via
              the API's formatted strings
            </div>
          </>
        )}
      </Panel>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Record verified revenue" actions={<Badge tone="cyan">POST /api/ledger/revenue</Badge>}>
          <form onSubmit={submitRevenue} className="grid gap-3 sm:grid-cols-2">
            <Field
              label="Amount (paise) *"
              type="number"
              min={1}
              required
              value={rev.amount_paise}
              onChange={setRevField('amount_paise')}
            />
            <Field label="Source *" required value={rev.source} onChange={setRevField('source')} />
            <Field
              label="Reference"
              value={rev.reference}
              onChange={setRevField('reference')}
              hint="unique id for the payout"
            />
            <Field
              label="Verification method"
              value={rev.verification_method}
              onChange={setRevField('verification_method')}
              hint="e.g. payout-confirmed — required for VERIFIED"
            />
            <Field
              label="Confidence (0–1)"
              type="number"
              min={0}
              max={1}
              step={0.01}
              value={rev.confidence}
              onChange={setRevField('confidence')}
              hint="≥ 0.9 with a method ⇒ VERIFIED"
            />
            <div className="flex items-end">
              <button
                type="submit"
                disabled={busy === 'rev'}
                className="w-full rounded-lg bg-emerald-400/15 px-4 py-2 text-sm font-semibold text-emerald-200 transition hover:bg-emerald-400/25 disabled:opacity-50"
              >
                {busy === 'rev' ? 'recording…' : 'Record revenue'}
              </button>
            </div>
          </form>
          {revResult && (
            <div className="mt-3 rounded-xl border border-emerald-400/20 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200">
              {revResult.entry.type} {revResult.entry.amount_formatted} →{' '}
              <span className="font-mono">{revResult.status}</span> (verified:{' '}
              {revResult.verified ? 'yes' : 'no'}) — available{' '}
              {revResult.available_cash_formatted}
            </div>
          )}
        </Panel>

        <Panel
          title="Record expense"
          actions={<Badge tone="cyan">POST /api/ledger/spend → policy/approval</Badge>}
        >
          <form onSubmit={submitSpend} className="grid gap-3 sm:grid-cols-2">
            <Field
              label="Amount (paise) *"
              type="number"
              min={1}
              required
              value={spend.amount_paise}
              onChange={setSpendField('amount_paise')}
            />
            <Field
              label="Category *"
              required
              value={spend.category}
              onChange={setSpendField('category')}
            />
            <Field
              label="Reason"
              value={spend.reason}
              onChange={setSpendField('reason')}
              className="sm:col-span-2"
            />
            <div className="flex items-end sm:col-span-2">
              <button
                type="submit"
                disabled={busy === 'spend'}
                className="w-full rounded-lg bg-amber-400/15 px-4 py-2 text-sm font-semibold text-amber-200 transition hover:bg-amber-400/25 disabled:opacity-50"
              >
                {busy === 'spend' ? 'submitting…' : 'Submit expense'}
              </button>
            </div>
          </form>
          {spendResult && (
            <div className="mt-3 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs text-slate-300">
              status <span className="font-mono text-slate-100">{spendResult.status}</span>
              {spendResult.simulated && (
                <span className="ml-2 text-amber-300">SIMULATED — no money moved (dry run)</span>
              )}
              {spendResult.approval && (
                <div className="mt-1 text-slate-400">
                  approval #{spendResult.approval.id} →{' '}
                  <span className="font-mono">{spendResult.approval.status}</span>
                  {spendResult.approval.decision && (
                    <span className="text-slate-500"> ({spendResult.approval.decision})</span>
                  )}
                </div>
              )}
              {spendResult.entry && (
                <div className="mt-1 text-emerald-300">
                  ledger write #{spendResult.entry.id} {spendResult.entry.amount_formatted}
                </div>
              )}
            </div>
          )}
        </Panel>
      </div>

      {error && (
        <div>
          <ErrorNote message={error} />
        </div>
      )}

      <Panel title="Ledger entries" actions={<Badge tone="cyan">GET /api/ledger</Badge>}>
        {ledger.error ? (
          <ErrorNote message={ledger.error} />
        ) : !ledger.data ? (
          <Spinner />
        ) : (
          <div className="overflow-x-auto rounded-xl border border-white/10">
            <table className="w-full min-w-[56rem] text-left text-sm">
              <thead>
                <tr className="border-b border-white/10 text-[11px] uppercase tracking-widest text-slate-500">
                  <th className="px-3 py-2">#</th>
                  <th className="px-3 py-2">Type</th>
                  <th className="px-3 py-2">Amount</th>
                  <th className="px-3 py-2">Source → Destination</th>
                  <th className="px-3 py-2">Reference</th>
                  <th className="px-3 py-2">Status</th>
                  <th className="px-3 py-2">When</th>
                </tr>
              </thead>
              <tbody>
                {ledger.data.entries.map((entry: EntryType) => (
                  <tr key={entry.id} className="border-b border-white/5 last:border-0 hover:bg-white/5">
                    <td className="px-3 py-2 text-slate-500">{entry.id}</td>
                    <td className="px-3 py-2">
                      <Badge tone={entryTone(entry.type)}>{entry.type}</Badge>
                    </td>
                    <td className="mono-num px-3 py-2 text-slate-100">
                      {entry.amount_formatted}
                    </td>
                    <td className="px-3 py-2 text-xs text-slate-400">
                      {entry.source}
                      {entry.destination && <> → {entry.destination}</>}
                    </td>
                    <td className="mono-num px-3 py-2 text-xs text-slate-500">
                      {entry.reference ?? '—'}
                    </td>
                    <td className="px-3 py-2 text-xs text-slate-300">{entry.status}</td>
                    <td className="mono-num px-3 py-2 text-xs text-slate-500">
                      {new Date(entry.created_at).toLocaleString()}
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

function Chip({
  label,
  value,
  tone = 'default',
}: {
  label: string;
  value: string;
  tone?: 'default' | 'good' | 'bad' | 'warn';
}) {
  const color =
    tone === 'good'
      ? 'text-emerald-300'
      : tone === 'bad'
        ? 'text-rose-300'
        : tone === 'warn'
          ? 'text-amber-300'
          : 'text-slate-100';
  return (
    <span className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-2 py-1">
      <span className="text-[10px] uppercase tracking-wider text-slate-500">{label}</span>
      <span className={`mono-num ${color}`}>{value}</span>
    </span>
  );
}