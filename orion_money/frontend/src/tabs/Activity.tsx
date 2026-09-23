import { useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';
import Panel from '../components/Panel';
import Badge from '../components/Badge';
import ErrorNote from '../components/ErrorNote';
import type { ActivityEvent, ActivityRecentResponse } from '../types';

const MAX_EVENTS = 200;

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleTimeString();
}

function fmtMeta(metadata: Record<string, unknown>): string {
  const keys = Object.keys(metadata ?? {});
  if (keys.length === 0) return '';
  return keys
    .slice(0, 3)
    .map((k) => `${k}=${String(metadata[k])}`)
    .join(' ');
}

/**
 * Live SSE activity stream (GET /api/activity). If the EventSource errors
 * (backend down, proxy hiccup) it falls back to polling GET /api/activity/recent.
 */
export default function Activity() {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [mode, setMode] = useState<'live' | 'fallback'>('live');
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    let es: EventSource | null = null;
    let pollId: number | undefined;

    const loadRecent = async () => {
      try {
        const r = await api.get<ActivityRecentResponse>('/activity/recent');
        if (!cancelled) {
          // recent() is newest-first; reverse to chronological for the log view.
          setEvents(r.events.slice().reverse().slice(-MAX_EVENTS));
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      }
    };

    const goFallback = () => {
      if (cancelled || pollId !== undefined) return;
      setMode('fallback');
      es?.close();
      void loadRecent();
      pollId = window.setInterval(loadRecent, 4000);
    };

    try {
      es = new EventSource('/api/activity');
      es.onmessage = (msg) => {
        if (cancelled) return;
        try {
          const ev = JSON.parse(msg.data as string) as ActivityEvent;
          setMode('live');
          setError(null);
          setEvents((prev) => [...prev, ev].slice(-MAX_EVENTS));
        } catch {
          // malformed frame — ignore, keep stream open
        }
      };
      es.onerror = goFallback;
    } catch {
      goFallback();
    }

    return () => {
      cancelled = true;
      es?.close();
      if (pollId !== undefined) window.clearInterval(pollId);
    };
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: 'nearest' });
  }, [events]);

  return (
    <Panel
      title="Activity stream"
      actions={<Badge tone={mode === 'live' ? 'green' : 'amber'}>{mode === 'live' ? 'live SSE' : 'polling /api/activity/recent'}</Badge>}
    >
      {error && (
        <div className="mb-3">
          <ErrorNote message={error} />
        </div>
      )}
      <div className="h-[28rem] overflow-y-auto rounded-xl border border-white/10 bg-deep/60 p-3 font-mono text-xs">
        {events.length === 0 ? (
          <div className="text-slate-500">no events yet — they appear here live</div>
        ) : (
          <ul className="space-y-1.5">
            {events.map((ev, i) => (
              <li
                key={`${ev.timestamp}-${i}`}
                className="flex flex-wrap items-baseline gap-x-2 text-slate-300"
              >
                <span className="text-slate-500">{fmtTime(ev.timestamp)}</span>
                <span className="text-cyan-300">{ev.event}</span>
                <span className="text-slate-500">agent={ev.agent}</span>
                {ev.entity_id != null && <span className="text-slate-400">id={String(ev.entity_id)}</span>}
                {fmtMeta(ev.metadata) && <span className="text-slate-400">{fmtMeta(ev.metadata)}</span>}
              </li>
            ))}
          </ul>
        )}
        <div ref={bottomRef} />
      </div>
    </Panel>
  );
}