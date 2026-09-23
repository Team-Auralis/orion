import { useState, type ChangeEvent, type FormEvent } from 'react';
import { api, ApiError } from '../lib/api';
import { useFetch } from '../hooks/useFetch';
import Panel from '../components/Panel';
import Badge from '../components/Badge';
import Field from '../components/Field';
import ErrorNote from '../components/ErrorNote';
import Spinner from '../components/Spinner';
import type { StrategiesResponse, Strategy } from '../types';

function toList(value: string): string[] {
  return value
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
}

function statusTone(status: string) {
  switch (status) {
    case 'ACTIVE':
      return 'green' as const;
    case 'PROPOSED':
      return 'slate' as const;
    case 'PAUSED':
      return 'amber' as const;
    case 'RETIRED':
      return 'red' as const;
    default:
      return 'slate' as const;
  }
}

export default function Strategies() {
  const strategies = useFetch(() => api.get<StrategiesResponse>('/strategies'));

  const [form, setForm] = useState({
    name: '',
    description: '',
    required_capital_paise: '0',
    required_skills: '',
    automation_level: 'manual',
    risk_level: 'L2',
    min_opportunity_score: '40',
    max_spend_paise: '500',
    allowed_risk_levels: 'L0, L1, L2',
  });
  const [submitting, setSubmitting] = useState(false);
  const [created, setCreated] = useState<Strategy | null>(null);
  const [error, setError] = useState<string | null>(null);

  const set =
    (key: keyof typeof form) =>
    (e: ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
      setForm((f) => ({ ...f, [key]: e.target.value }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    setCreated(null);
    try {
      const strategy = await api.post<Strategy>('/strategies', {
        name: form.name,
        description: form.description,
        required_capital_paise: Number(form.required_capital_paise) || 0,
        required_skills: toList(form.required_skills),
        automation_level: form.automation_level,
        risk_level: form.risk_level,
        min_opportunity_score: Number(form.min_opportunity_score) || 0,
        max_spend_paise: Number(form.max_spend_paise) || 0,
        allowed_risk_levels: toList(form.allowed_risk_levels),
      });
      setCreated(strategy);
      setForm((f) => ({ ...f, name: '', description: '' }));
      strategies.reload();
    } catch (err) {
      setError(err instanceof ApiError ? `${err.message} ${err.reasons.join('; ')}` : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      <Panel
        title="Propose a strategy"
        actions={<Badge tone="cyan">POST /api/strategies</Badge>}
      >
        <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Name *" value={form.name} onChange={set('name')} required />
          <Field label="Description" value={form.description} onChange={set('description')} />
          <Field
            label="Required capital (paise)"
            type="number"
            min={0}
            value={form.required_capital_paise}
            onChange={set('required_capital_paise')}
          />
          <Field
            label="Required skills (comma separated)"
            value={form.required_skills}
            onChange={set('required_skills')}
          />
          <label className="block">
            <span className="mb-1 block text-[11px] uppercase tracking-widest text-slate-400">
              Automation level
            </span>
            <select
              value={form.automation_level}
              onChange={set('automation_level')}
              className="w-full rounded-lg border border-white/10 bg-deep px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-400/60"
            >
              <option value="manual">manual</option>
              <option value="semi">semi</option>
              <option value="auto">auto</option>
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-[11px] uppercase tracking-widest text-slate-400">
              Risk level
            </span>
            <select
              value={form.risk_level}
              onChange={set('risk_level')}
              className="w-full rounded-lg border border-white/10 bg-deep px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-400/60"
            >
              <option value="L0">L0</option>
              <option value="L1">L1</option>
              <option value="L2">L2</option>
              <option value="L3">L3</option>
              <option value="L4">L4</option>
            </select>
          </label>
          <Field
            label="Min opportunity score (0–100)"
            type="number"
            min={0}
            max={100}
            step={0.1}
            value={form.min_opportunity_score}
            onChange={set('min_opportunity_score')}
          />
          <Field
            label="Max spend (paise)"
            type="number"
            min={0}
            value={form.max_spend_paise}
            onChange={set('max_spend_paise')}
          />
          <Field
            label="Allowed risk levels (comma separated)"
            value={form.allowed_risk_levels}
            onChange={set('allowed_risk_levels')}
          />
          <div className="flex items-end">
            <button
              type="submit"
              disabled={submitting}
              className="w-full rounded-lg bg-cyan-400/15 px-4 py-2 text-sm font-semibold text-cyan-200 transition hover:bg-cyan-400/25 disabled:opacity-50"
            >
              {submitting ? 'proposing…' : 'Propose strategy'}
            </button>
          </div>
        </form>
        {error && (
          <div className="mt-3">
            <ErrorNote message={error} />
          </div>
        )}
        {created && (
          <div className="mt-3 rounded-xl border border-emerald-400/20 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200">
            proposed #{created.id} {created.name} → status{' '}
            <span className="font-mono">{created.status}</span> (activation reasons:{' '}
            {created.activation_reasons.length ? created.activation_reasons.join('; ') : 'none yet'})
          </div>
        )}
      </Panel>

      <Panel title="Strategies" actions={<Badge tone="cyan">GET /api/strategies</Badge>}>
        {strategies.error ? (
          <ErrorNote message={strategies.error} />
        ) : !strategies.data ? (
          <Spinner />
        ) : strategies.data.count === 0 ? (
          <div className="text-sm text-slate-500">no strategies proposed yet</div>
        ) : (
          <div className="grid gap-3 lg:grid-cols-2">
            {strategies.data.strategies.map((s) => {
              const perf = s.performance_summary;
              return (
                <div
                  key={s.id}
                  className="rounded-xl border border-white/10 bg-deep/60 p-4"
                >
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <span className="font-medium text-slate-100">{s.name}</span>
                    <Badge tone={statusTone(s.status)}>{s.status}</Badge>
                  </div>
                  {s.description && (
                    <p className="mb-2 text-xs text-slate-400">{s.description}</p>
                  )}
                  <div className="mb-2 flex flex-wrap gap-1.5 text-[11px] text-slate-400">
                    <span className="rounded-md bg-white/5 px-1.5 py-0.5">risk {s.risk_level ?? '—'}</span>
                    <span className="rounded-md bg-white/5 px-1.5 py-0.5">auto {s.automation_level ?? '—'}</span>
                    <span className="rounded-md bg-white/5 px-1.5 py-0.5">min score {s.min_opportunity_score ?? 0}</span>
                    <span className="rounded-md bg-white/5 px-1.5 py-0.5">max spend {s.max_spend_formatted}</span>
                    <span className="rounded-md bg-white/5 px-1.5 py-0.5">capital {s.required_capital_formatted}</span>
                  </div>
                  {s.required_skills.length > 0 && (
                    <div className="mb-2 text-[11px] text-slate-500">
                      skills: {s.required_skills.join(', ')}
                    </div>
                  )}
                  <div className="grid grid-cols-3 gap-2 rounded-lg border border-white/10 bg-white/5 p-2 text-center">
                    <div>
                      <div className="mono-num text-sm text-slate-100">
                        {perf.total_profit_paise_formatted}
                      </div>
                      <div className="text-[10px] uppercase tracking-wider text-slate-500">profit</div>
                    </div>
                    <div>
                      <div className="mono-num text-sm text-slate-100">
                        {perf.avg_profit_per_hour_paise_formatted}
                      </div>
                      <div className="text-[10px] uppercase tracking-wider text-slate-500">profit/hr</div>
                    </div>
                    <div>
                      <div className="mono-num text-sm text-slate-100">
                        {(perf.win_rate * 100).toFixed(0)}%
                      </div>
                      <div className="text-[10px] uppercase tracking-wider text-slate-500">
                        win rate ({perf.wins}W/{perf.losses}L · {perf.run_count} runs)
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Panel>
    </div>
  );
}