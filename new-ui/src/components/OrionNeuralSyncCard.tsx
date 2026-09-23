import React from 'react';
import { Globe2 } from 'lucide-react';

interface OrionNeuralSyncCardProps {
  corePercentages: number[];
  onClick?: () => void;
}

export const OrionNeuralSyncCard: React.FC<OrionNeuralSyncCardProps> = ({
  corePercentages,
  onClick,
}) => {
  return (
    <div
      role="region"
      aria-label="Neural Network Sync Status"
      onClick={onClick}
      className="w-56 lg:w-60 p-4 rounded-2xl bg-slate-950/60 backdrop-blur-xl border border-cyan-500/25 shadow-[0_0_30px_rgba(0,0,0,0.85),inset_0_0_15px_rgba(0,255,255,0.04)] select-none z-30 cursor-pointer hover:border-cyan-400/60 focus-visible:ring-2 focus-visible:ring-cyan-300 focus-visible:outline-none transition-all group"
      tabIndex={0}
      onKeyDown={(e) => {
        if ((e.key === 'Enter' || e.key === ' ') && onClick) {
          e.preventDefault();
          onClick();
        }
      }}
    >
      {/* Header */}
      <div className="flex items-center justify-between pb-2 border-b border-slate-800/80">
        <div>
          <div className="font-['Orbitron'] font-bold text-xs text-white tracking-wider">
            NEURAL NETWORK SYNC
          </div>
          <div className="flex items-center space-x-1.5 mt-0.5">
            <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 shadow-[0_0_6px_#00ffff] animate-pulse" />
            <span className="font-mono text-[9px] font-bold text-cyan-400 tracking-widest uppercase">
              ONLINE
            </span>
          </div>
        </div>
      </div>

      {/* Visualizer: Waveform Graph + Rotating Globe */}
      <div className="flex items-center justify-between py-2.5 px-1">
        {/* Pulsing SVG EEG / Waveform */}
        <div className="flex-1 pr-2" aria-hidden="true">
          <svg viewBox="0 0 100 25" className="w-full h-7 overflow-visible">
            <polyline
              fill="none"
              stroke="#00ffff"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              points="0,12 15,12 22,5 28,20 34,2 40,22 46,12 60,12 66,7 72,17 78,12 100,12"
              className="drop-shadow-[0_0_6px_#00ffff]"
            />
          </svg>
        </div>

        {/* Wireframe Rotating Globe */}
        <div className="relative w-8 h-8 rounded-full border border-cyan-500/40 flex items-center justify-center bg-cyan-950/30 shrink-0" aria-hidden="true">
          <Globe2 className="w-5 h-5 text-cyan-300 animate-spin-slow" />
        </div>
      </div>

      {/* 6 Core Progress Bars with aria-valuenow */}
      <div className="space-y-1.5 pt-1" aria-live="polite">
        {corePercentages.map((pct, idx) => (
          <div
            key={idx}
            className="flex items-center justify-between font-mono text-[9px] text-slate-300"
            role="progressbar"
            aria-label={`Core ${idx + 1}`}
            aria-valuenow={pct}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <span className="w-14 shrink-0 text-slate-400">
              CORE 0{idx + 1}
            </span>

            {/* Horizontal Track Bar */}
            <div className="flex-1 mx-2 h-1 bg-black/60 rounded-full border border-cyan-500/20 overflow-hidden">
              <div
                className="h-full bg-cyan-400 rounded-full shadow-[0_0_6px_#00ffff] transition-all duration-500"
                style={{ width: `${pct}%` }}
              />
            </div>

            <span className="w-8 text-right font-bold text-cyan-300">
              {pct}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
};
