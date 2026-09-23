import { useState, type ChangeEvent, type FormEvent } from 'react';
import { api, ApiError } from '../lib/api';
import { useFetch } from '../hooks/useFetch';
import Panel from '../components/Panel';
import Badge from '../components/Badge';
import Field from '../components/Field';
import ErrorNote from '../components/ErrorNote';
import Spinner from '../components/Spinner';
import type { Experiment, ExperimentsResponse } from '../types';

function statusTone(status: string) {
  switch (status) {
    case 'RUNNING':
      return 'cyan' as const;
    case 'COMPLETED':
      return 'green' as const;
    case 'FAILED':
      return 'red' as const;
    default:
      return 'slate' as const;
  }
}

export default function Experiments() {
  const experiments = useFetch(() => api.get<ExperimentsResponse>('/experiments'));

  const [form, setForm] = useState({
    hypothesis: '',
    strategy_id: '',
    params_paise: '',
    expected_result: '',
  });
  const [submitting, setSubmitting] = useState(false);
  const [created, setCreated] = useState<Experiment | null>(null);
  const [error, setError] = useState<string | null>(null);

  const set =
    (key: keyof typeof form) =>
    (e: ChangeEvent<HTMLInputElement>) =>
      setForm((f) => ({ ...f, [key]: e.target.value }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    setCreated(null);
    try {
      const experiment = await api.post<Experiment>('/experiments', {
        hypothesis: form.hypothesis,
        strategy_id: form.strategy_id ? Number(form.strategy_id) : null,
        params_paise: form.params_paise ? Number(form.params_paise) : null,
        expected_result: form.expected_result,
      });
      setCreated(experiment);
      setForm((f) => ({ ...f, hypothesis: '', expected_result: '' }));
      experiments.reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      <Panel title="Start an experiment" actions={<Badge tone="cyan">POST /api/experiments</Badge>}>
        <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Field
            label="Hypothesis *"
            value={form.hypothesis}
            onChange={set('hypothesis')}
            required
          />
          <Field
            label="Strategy id (optional)"
            type="number"
            min={1}
            value={form.strategy_id}
            onChange={set('strategy_id')}
          />
          <Field
            label="Params (paise, optional)"
            type="number"
            min={0}
            value={form.params_paise}
            onChange={set('params_paise')}
          />
          <Field
            label="Expected result"
            value={form.expected_result}
            onChange={set('expected_result')}
            className="sm:col-span-2 lg:col-span-2"
          />
          <div className="flex items-end">
            <button
              type="submit"
              disabled={submitting}
              className="w-full rounded-lg bg-cyan-400/15 px-4 py-2 text-sm font-semibold text-cyan-200 transition hover:bg-cyan-400/25 disabled:opacity-50"
            >
              {submitting ? 'starting…' : 'Start experiment'}
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
            started #{created.id} — {created.hypothesis ?? created.name} (
            <span className="font-mono">{created.status}</span>)
          </div>
        )}
      </Panel>

      <Panel title="Experiments" actions={<Badge tone="cyan">GET /api/experiments</Badge>}>
        {experiments.error ? (
          <ErrorNote message={experiments.error} />
        ) : !experiments.data ? (
          <Spinner />
        ) : experiments.data.count === 0 ? (
          <div className="text-sm text-slate-500">no experiments started yet</div>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-white/10">
            <table className="w-full min-w-[48rem] text-left text-sm">
              <thead>
                <tr className="border-b border-white/10 text-[11px] uppercase tracking-widest text-slate-500">
                  <th className="px-3 py-2">Hypothesis</th>
                  <th className="px-3 py-2">Strategy</th>
                  <th className="px-3 py-2">Params</th>
                  <th className="px-3 py-2">Expected</th>
                  <th className="px-3 py-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {experiments.data.experiments.map((x) => (
                  <tr key={x.id} className="border-b border-white/5 last:border-0 hover:bg-white/5">
                    <td className="px-3 py-2 text-slate-200">
                      {x.hypothesis ?? x.name}
                    </td>
                    <td className="px-3 py-2 text-slate-400">
                      {x.strategy_id != null ? `#${x.strategy_id}` : '—'}
                    </td>
                    <td className="mono-num px-3 py-2 text-slate-300">
                      {x.params_formatted ?? '—'}
                    </td>
                    <td className="max-w-[24rem] truncate px-3 py-2 text-slate-400">
                      {x.expected_result || '—'}
                    </td>
                    <td className="px-3 py-2">
                      <Badge tone={statusTone(x.status)}>{x.status}</Badge>
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