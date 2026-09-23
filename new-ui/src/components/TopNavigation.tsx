import React from 'react';
import { User, Volume2, VolumeX } from 'lucide-react';
import { sfx } from '../utils/audio';

interface TopNavigationProps {
  isStandby: boolean;
  onToggleStandby: () => void;
  soundEnabled: boolean;
  onToggleSound: () => void;
}

export const TopNavigation: React.FC<TopNavigationProps> = ({
  isStandby,
  onToggleStandby,
  soundEnabled,
  onToggleSound,
}) => {
  return (
    <>
      {/* Top Outer Screen Corner Tactical HUD Indicators */}
      <div className="fixed top-2 left-6 z-30 hidden sm:flex items-center space-x-2 text-[10px] font-mono text-cyan-400/80 bg-black/60 px-3 py-1 border border-cyan-500/40 rounded">
        <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse" />
        <span>NEURAL NETWORK SYNC:</span>
        <span className="text-cyan-300 font-bold">CALIBRATING...</span>
      </div>

      <div className="fixed top-2 right-6 z-30 hidden sm:flex items-center space-x-2 text-[10px] font-mono text-cyan-400/80 bg-black/60 px-3 py-1 border border-cyan-500/40 rounded">
        <span>STAR CHART INDEX:</span>
        <span className="text-cyan-300 font-bold">[ORION-LMC] ACTIVE</span>
      </div>

      {/* Thin Horizontal Pill-Shaped Header Centered at the Top */}
      <header className="fixed top-3 sm:top-5 left-1/2 -translate-x-1/2 z-40 w-[94%] max-w-4xl">
        <div className="rounded-full bg-black/75 border border-cyan-500/40 px-5 py-2.5 sm:px-7 sm:py-2.5 flex items-center justify-between shadow-[0_0_15px_rgba(0,0,0,0.8)] glow-cyan-hover transition-all">
          {/* Left: ORION DEEP SPACE INTELLIGENCE & Small Status Text 'CORE: ONLINE' */}
          <div className="flex items-center space-x-3 sm:space-x-4 min-w-0">
            {/* Glowing Amber/Cyan Status Orb */}
            <div className="relative flex items-center justify-center w-6 h-6 rounded-full bg-black border border-cyan-500/50 shrink-0">
              <span className="w-2 h-2 rounded-full bg-orange-400 shadow-[0_0_8px_#fb923c] animate-pulse" />
            </div>

            <div className="flex flex-col sm:flex-row sm:items-baseline sm:space-x-3">
              <div className="flex items-center space-x-2">
                <span className="font-['Orbitron'] font-bold text-xs sm:text-sm tracking-[0.25em] text-cyan-300 uppercase whitespace-nowrap">
                  ORION
                </span>
                <span className="hidden md:inline font-mono text-xs tracking-wider text-cyan-400/90 whitespace-nowrap">
                  DEEP SPACE INTELLIGENCE
                </span>
              </div>

              {/* Small status text ('CORE: ONLINE') */}
              <div className="flex items-center space-x-1.5 text-[10px] font-mono text-cyan-400/90 mt-0.5 sm:mt-0">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shadow-[0_0_5px_#34d399]" />
                <span className="text-emerald-400 font-semibold tracking-wider">
                  CORE: {isStandby ? 'STANDBY' : 'ONLINE'}
                </span>
              </div>
            </div>
          </div>

          {/* Right: STANDBY Toggle & User Icon */}
          <div className="flex items-center space-x-2 sm:space-x-4 shrink-0">
            {/* Audio Toggle */}
            <button
              onClick={() => {
                onToggleSound();
                sfx.click();
              }}
              title={soundEnabled ? 'Mute Audio' : 'Unmute Audio'}
              className="p-1 rounded text-cyan-400/70 hover:text-cyan-300 transition-colors cursor-pointer"
            >
              {soundEnabled ? <Volume2 className="w-3.5 h-3.5" /> : <VolumeX className="w-3.5 h-3.5 text-slate-500" />}
            </button>

            {/* STANDBY Toggle */}
            <div className="flex items-center space-x-2 bg-black/60 border border-cyan-500/40 rounded-full px-2.5 py-1">
              <span className="text-[10px] font-mono font-bold tracking-wider text-cyan-300/90">
                STANDBY
              </span>
              <button
                onClick={() => {
                  sfx.click();
                  onToggleStandby();
                }}
                role="switch"
                aria-checked={isStandby}
                className={`w-7 h-3.5 flex items-center rounded-full p-0.5 cursor-pointer transition-colors duration-200 ${
                  isStandby ? 'bg-cyan-500' : 'bg-slate-800 border border-cyan-500/40'
                }`}
              >
                <div
                  className={`bg-black w-2.5 h-2.5 rounded-full transform transition-transform duration-200 border border-cyan-400 ${
                    isStandby ? 'translate-x-3.5 bg-cyan-200' : 'translate-x-0'
                  }`}
                />
              </button>
            </div>

            {/* User Icon */}
            <div
              className="flex items-center justify-center w-7 h-7 rounded-full bg-black/70 border border-cyan-500/40 hover:border-cyan-300 hover:shadow-[0_0_10px_rgba(0,255,255,0.5)] transition-all cursor-pointer group"
              onClick={() => sfx.click()}
              title="Commander Profile // Level 05"
            >
              <User className="w-3.5 h-3.5 text-cyan-400 group-hover:text-cyan-200" />
            </div>
          </div>
        </div>
      </header>
    </>
  );
};
