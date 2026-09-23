import { useEffect, useState, type ComponentType } from 'react';
import { api } from './lib/api';
import Badge from './components/Badge';
import ErrorNote from './components/ErrorNote';
import type { StatusResponse } from './types';
import Overview from './tabs/Overview';
import Activity from './tabs/Activity';
import Opportunities from './tabs/Opportunities';
import Strategies from './tabs/Strategies';
import Experiments from './tabs/Experiments';
import Approvals from './tabs/Approvals';
import Ledger from './tabs/Ledger';
import Settings from './tabs/Settings';

const TABS: { key: string; label: string; component: ComponentType }[] = [
  { key: 'overview', label: 'Overview', component: Overview },
  { key: 'activity', label: 'Activity', component: Activity },
  { key: 'opportunities', label: 'Opportunities', component: Opportunities },
  { key: 'strategies', label: 'Strategies', component: Strategies },
  { key: 'experiments', label: 'Experiments', component: Experiments },
  { key: 'approvals', label: 'Approvals', component: Approvals },
  { key: 'ledger', label: 'Ledger', component: Ledger },
  { key: 'settings', label: 'Settings', component: Settings },
];

export default function App() {
  const [tab, setTab] = useState('overview');
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);

  // Poll /api/status — a single shared source for mode / kill switch /
  // model health / autonomy used by the header, banner, Overview and Settings.
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const s = await api.get<StatusResponse>('/status');
        if (!cancelled) {
          setStatus(s);
          setStatusError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setStatusError(err instanceof Error ? err.message : String(err));
        }
      }
    };
    void load();
    const id = window.setInterval(load, 10_000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  const Active = TABS.find((t) => t.key === tab)?.component ?? Overview;

  return (
    <div className="min-h-screen text-slate-200">
      <div className="mx-auto max-w-7xl px-4 py-6">
        <header className="mb-6 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-slate-50">
              ORION <span className="font-light text-cyan-300">economic agent</span>
            </h1>
            <p className="text-xs text-slate-400">
              every figure comes live from <span className="font-mono">/api</span> — no
              client-side mock data
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {status ? (
              <>
                <Badge tone={status.mode === 'dry_run' ? 'amber' : 'cyan'}>
                  mode: {status.mode}
                </Badge>
                <Badge tone={status.kill_switch_active ? 'red' : 'green'}>
                  {status.kill_switch_active ? 'KILL SWITCH ACTIVE' : 'kill switch off'}
                </Badge>
                <Badge tone={status.model_status === 'OK' ? 'green' : 'amber'}>
                  model: {status.model_status}
                </Badge>
                {!status.db_ok && <Badge tone="red">db: DOWN</Badge>}
              </>
            ) : (
              <Badge tone="slate">{statusError ? 'api unreachable' : '…'}</Badge>
            )}
          </div>
        </header>

        {status?.mode === 'dry_run' && (
          <div className="mb-6 rounded-xl border border-amber-400/30 bg-amber-500/10 px-4 py-3 text-center text-sm font-semibold tracking-wide text-amber-300">
            SIMULATION ONLY — NO REAL MONEY MOVEMENT
          </div>
        )}

        {statusError && (
          <div className="mb-6">
            <ErrorNote message={statusError} />
          </div>
        )}

        <nav className="mb-6 flex flex-wrap gap-1 rounded-2xl border border-white/10 bg-white/5 p-1 backdrop-blur">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`rounded-xl px-3 py-1.5 text-sm font-medium transition ${
                tab === t.key
                  ? 'bg-cyan-400/15 text-cyan-200 shadow-glow'
                  : 'text-slate-400 hover:bg-white/5 hover:text-slate-200'
              }`}
            >
              {t.label}
            </button>
          ))}
        </nav>

        <main>
          <Active />
        </main>

        <footer className="mt-10 border-t border-white/10 pt-4 text-center text-[11px] text-slate-500">
          ORION dashboard · integer-paise ledger — money is displayed via the API's
          <span className="font-mono"> formatted ₹</span> strings, never recomputed client-side
        </footer>
      </div>
    </div>
  );
}