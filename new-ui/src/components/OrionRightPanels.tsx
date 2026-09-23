import React from 'react';
import { Plus } from 'lucide-react';
import { sfx } from '../utils/audio';

interface OrionRightPanelsProps {
  cpu: number;
  gpu: number;
  mem: number;
  net: number;
  onOpenStarChart: () => void;
  onOpenMissionLog: () => void;
  onOpenStation: () => void;
}

export const OrionRightPanels: React.FC<OrionRightPanelsProps> = ({
  cpu,
  gpu,
  mem,
  net,
  onOpenStarChart,
  onOpenMissionLog,
  onOpenStation,
}) => {
  return (
    <aside className="w-56 lg:w-60 flex flex-col space-y-3 select-none z-30">
      {/* ============================================================ */}
      {/* CARD 1: STAR CHART INDEX & NGC 1300                          */}
      {/* ============================================================ */}
      <div
        onClick={onOpenStarChart}
        className="p-3.5 rounded-2xl bg-slate-950/60 backdrop-blur-xl border border-cyan-500/25 shadow-[0_0_25px_rgba(0,0,0,0.8)] cursor-pointer hover:border-cyan-400/60 transition-all group"
      >
        <div className="flex items-center justify-between border-b border-slate-800/80 pb-1.5 mb-2">
          <div className="font-['Orbitron'] font-bold text-xs text-white tracking-wider">
            STAR CHART INDEX
          </div>
          <div className="text-[9px] font-mono font-bold text-cyan-400">
            [ORION-LMC] ACTIVE
          </div>
        </div>

        {/* Galaxy Image Preview */}
        <div className="relative w-full h-20 rounded-xl overflow-hidden border border-cyan-500/30 mb-2">
          <img
            src="/orion_assets/ngc1300.png"
            alt="NGC 1300"
            className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"
          />
          {/* Circular + Expand Button */}
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              sfx.click();
              onOpenStarChart();
            }}
            className="absolute bottom-1.5 right-1.5 w-5 h-5 rounded-full bg-black/70 border border-cyan-400/60 flex items-center justify-center text-cyan-300 hover:bg-cyan-500 hover:text-black transition-colors"
          >
            <Plus className="w-3.5 h-3.5" />
          </button>
        </div>

        <div className="text-[10px] font-bold text-slate-100 font-mono">NGC 1300</div>
        <div className="text-[8px] font-mono text-cyan-400/80 uppercase tracking-widest -mt-0.5">
          SPIRAL GALAXY : 320 MILLION LY
        </div>
      </div>

      {/* ============================================================ */}
      {/* CARD 2: MISSION LOG                                          */}
      {/* ============================================================ */}
      <div
        onClick={onOpenMissionLog}
        className="p-3.5 rounded-2xl bg-slate-950/60 backdrop-blur-xl border border-cyan-500/25 shadow-[0_0_25px_rgba(0,0,0,0.8)] cursor-pointer hover:border-cyan-400/60 transition-all group"
      >
        <div className="font-['Orbitron'] font-bold text-xs text-white tracking-wider border-b border-slate-800/80 pb-1.5 mb-2.5">
          MISSION LOG
        </div>

        <div className="space-y-2 font-mono text-[9px]">
          {/* Item 1 */}
          <div className="flex items-start space-x-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 mt-1 shadow-[0_0_6px_#00ffff]" />
            <div>
              <div className="font-bold text-slate-200">NEURAL SYNC</div>
              <div className="text-cyan-400">Complete</div>
            </div>
          </div>

          {/* Item 2 */}
          <div className="flex items-start space-x-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 mt-1 shadow-[0_0_6px_#00ffff]" />
            <div>
              <div className="font-bold text-slate-200">KNOWLEDGE UPDATE</div>
              <div className="text-cyan-400">Complete</div>
            </div>
          </div>

          {/* Item 3 */}
          <div className="flex items-start space-x-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-400 mt-1 shadow-[0_0_6px_#fbbf24] animate-pulse" />
            <div>
              <div className="font-bold text-slate-200">SYSTEM OPTIMIZATION</div>
              <div className="text-slate-400 italic">In Progress...</div>
            </div>
          </div>

          {/* Item 4 */}
          <div className="flex items-start space-x-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 mt-1 shadow-[0_0_6px_#00ffff]" />
            <div>
              <div className="font-bold text-slate-200">GALACTIC FEED</div>
              <div className="text-cyan-400">Online</div>
            </div>
          </div>
        </div>
      </div>

      {/* ============================================================ */}
      {/* CARD 3: QUOTE & ORBITAL SPACE STATION                        */}
      {/* ============================================================ */}
      <div
        onClick={onOpenStation}
        className="p-3 rounded-2xl bg-slate-950/60 backdrop-blur-xl border border-cyan-500/25 shadow-[0_0_25px_rgba(0,0,0,0.8)] cursor-pointer hover:border-cyan-400/60 transition-all group"
      >
        <div className="text-[10px] text-slate-300 font-mono tracking-wide leading-tight">
          "SOME INHERIT POWER.
          <br />
          I INHERITED POSSIBILITY."
        </div>
        <div className="text-[9px] text-right font-bold text-cyan-400 font-mono mt-0.5 mb-2">
          — ORION
        </div>

        {/* Space Station Image */}
        <div className="w-full h-14 rounded-xl overflow-hidden border border-cyan-500/30">
          <img
            src="/orion_assets/space_station.png"
            alt="Orbital Station"
            className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"
          />
        </div>
      </div>

      {/* ============================================================ */}
      {/* BOTTOM RIGHT: 2K CIRCULAR GAUGE & HARDWARE METRICS           */}
      {/* ============================================================ */}
      <div className="flex items-center justify-between p-2 rounded-2xl bg-slate-950/60 backdrop-blur-xl border border-cyan-500/25 shadow-md">
        {/* Circular 2K Gauge */}
        <div className="relative w-12 h-12 rounded-full border-2 border-cyan-400/60 flex items-center justify-center bg-cyan-950/30 shadow-[0_0_12px_rgba(0,255,255,0.4)] shrink-0">
          <span className="font-['Orbitron'] font-extrabold text-sm text-white drop-shadow-[0_0_6px_#00ffff]">
            2K
          </span>
        </div>

        {/* Hardware Telemetry Readouts */}
        <div className="grid grid-cols-2 gap-x-2.5 gap-y-0.5 text-[9px] font-mono text-slate-300 pl-2">
          <div className="flex justify-between space-x-1">
            <span className="text-slate-400">CPU</span>
            <span className="text-cyan-300 font-bold">{cpu}%</span>
          </div>
          <div className="flex justify-between space-x-1">
            <span className="text-slate-400">GPU</span>
            <span className="text-cyan-300 font-bold">{gpu}%</span>
          </div>
          <div className="flex justify-between space-x-1">
            <span className="text-slate-400">MEM</span>
            <span className="text-cyan-300 font-bold">{mem}%</span>
          </div>
          <div className="flex justify-between space-x-1">
            <span className="text-slate-400">NET</span>
            <span className="text-cyan-300 font-bold">{net}%</span>
          </div>
        </div>
      </div>
    </aside>
  );
};
