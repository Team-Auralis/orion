import React, { useState } from 'react';
import { Mic, Sliders, Scan, User, CloudSun } from 'lucide-react';
import { sfx } from '../utils/audio';

interface OrionTopBarProps {
  currentTime: string;
  currentDate: string;
  onSearch: (query: string) => void;
  onVoiceClick: () => void;
  onScanClick: () => void;
}

export const OrionTopBar: React.FC<OrionTopBarProps> = ({
  currentTime,
  currentDate,
  onSearch,
  onVoiceClick,
  onScanClick,
}) => {
  const [searchInput, setSearchInput] = useState('');
  const [isFocused, setIsFocused] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchInput.trim()) return;
    sfx.chime();
    onSearch(searchInput.trim());
    setSearchInput('');
  };

  return (
    <header
      role="banner"
      className="w-full flex items-center justify-between px-6 pt-4 pb-2 z-40 select-none"
    >
      {/* ============================================================ */}
      {/* 1. TOP LEFT BRANDING & LOGO                                  */}
      {/* ============================================================ */}
      <div className="flex items-center space-x-3.5" tabIndex={0} aria-label="Orion Deep Space Intelligence">
        {/* Glowing Cyan/Blue Circular Vortex Logo */}
        <div className="relative w-12 h-12 flex items-center justify-center">
          <img
            src="/orion_assets/logo_vortex.png"
            alt="Orion Logo"
            className="w-full h-full object-contain filter drop-shadow-[0_0_12px_rgba(0,255,255,0.7)]"
          />
        </div>

        {/* Brand Text */}
        <div className="flex flex-col">
          <h1 className="font-['Orbitron'] font-extrabold text-lg tracking-[0.25em] text-white drop-shadow-[0_0_10px_rgba(255,255,255,0.4)]">
            O R I O N
          </h1>
          <span className="text-[10px] font-['Rajdhani'] font-bold tracking-[0.22em] text-cyan-200 uppercase -mt-0.5">
            DEEP SPACE INTELLIGENCE
          </span>
          <span className="text-[8px] font-mono tracking-widest text-slate-400 uppercase">
            BEYOND HUMAN. BEYOND MACHINES.
          </span>
        </div>
      </div>

      {/* ============================================================ */}
      {/* 2. TOP CENTER PILL SEARCH BAR                                */}
      {/* ============================================================ */}
      <div className="w-full max-w-lg mx-4">
        <form
          role="search"
          onSubmit={handleSubmit}
          className={`
            w-full flex items-center justify-between px-3 py-1.5 rounded-full
            bg-slate-950/70 backdrop-blur-xl border transition-all duration-300
            ${
              isFocused
                ? 'border-cyan-400 shadow-[0_0_20px_rgba(0,255,255,0.5)] ring-1 ring-cyan-400/50'
                : 'border-cyan-500/30 hover:border-cyan-400/60 shadow-[0_0_15px_rgba(0,0,0,0.8)]'
            }
          `}
        >
          {/* Left Audio Waveform Icon Bubble */}
          <button
            type="button"
            onClick={() => {
              sfx.chime();
              onVoiceClick();
            }}
            aria-label="Activate Voice Input"
            title="Audio Input"
            className="w-7 h-7 rounded-full bg-gradient-to-tr from-cyan-600 to-blue-600 flex items-center justify-center shadow-[0_0_10px_rgba(0,255,255,0.5)] cursor-pointer hover:scale-105 focus-visible:ring-2 focus-visible:ring-cyan-300 transition-transform shrink-0"
          >
            <div className="flex items-center space-x-0.5 h-3.5" aria-hidden="true">
              <span className="w-0.5 h-2 bg-white rounded-full animate-pulse" />
              <span className="w-0.5 h-3.5 bg-white rounded-full animate-pulse" />
              <span className="w-0.5 h-2 bg-white rounded-full animate-pulse" />
            </div>
          </button>

          {/* Search Input Field */}
          <input
            type="text"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            onFocus={() => setIsFocused(true)}
            onBlur={() => setIsFocused(false)}
            placeholder="Ask Orion anything..."
            aria-label="Ask Orion query input"
            className="w-full bg-transparent text-slate-100 placeholder-slate-400/60 text-xs md:text-sm font-['Rajdhani'] font-medium tracking-wide focus:outline-none px-3 selection:bg-cyan-500 selection:text-black"
          />

          {/* Right Action Icons */}
          <div className="flex items-center space-x-2 shrink-0 text-slate-400">
            <button
              type="button"
              onClick={() => {
                sfx.chime();
                onVoiceClick();
              }}
              aria-label="Voice Command"
              title="Voice Input"
              className="p-1 hover:text-cyan-300 focus-visible:ring-2 focus-visible:ring-cyan-300 rounded transition-colors cursor-pointer"
            >
              <Mic className="w-3.5 h-3.5 text-slate-300" />
            </button>
            <button
              type="button"
              onClick={() => sfx.click()}
              aria-label="Equalizer Settings"
              title="Equalizer / Settings"
              className="p-1 hover:text-cyan-300 focus-visible:ring-2 focus-visible:ring-cyan-300 rounded transition-colors cursor-pointer"
            >
              <Sliders className="w-3.5 h-3.5 text-slate-300" />
            </button>
            <button
              type="button"
              onClick={() => {
                sfx.click();
                onScanClick();
              }}
              aria-label="Scan Star Sector"
              title="Scan Sector"
              className="p-1 hover:text-cyan-300 focus-visible:ring-2 focus-visible:ring-cyan-300 rounded transition-colors cursor-pointer"
            >
              <Scan className="w-3.5 h-3.5 text-slate-300" />
            </button>
          </div>
        </form>
      </div>

      {/* ============================================================ */}
      {/* 3. TOP RIGHT STATUS BADGES & LIVE CLOCK                      */}
      {/* ============================================================ */}
      <div className="flex items-center space-x-4 shrink-0">
        {/* Pill Status Badges */}
        <div className="hidden lg:flex items-center space-x-2 bg-slate-950/70 backdrop-blur-md border border-cyan-500/25 rounded-full px-3 py-1 text-[10px] font-mono text-slate-300 shadow-md">
          {/* Live Badge */}
          <div className="flex items-center space-x-1 pr-2 border-r border-slate-700/60" aria-label="System status: Live">
            <span className="w-1.5 h-1.5 rounded-full bg-red-500 shadow-[0_0_6px_#ef4444] animate-pulse" />
            <span className="font-bold text-white tracking-wider">LIVE</span>
          </div>

          {/* User Count Badge */}
          <div className="flex items-center space-x-1 pr-2 border-r border-slate-700/60" aria-label="2,300 active nodes">
            <User className="w-3 h-3 text-cyan-400" />
            <span>2.3K</span>
          </div>

          {/* Space Weather Badge */}
          <div className="flex items-center space-x-1.5" aria-label="Space weather: stable">
            <CloudSun className="w-3 h-3 text-cyan-400" />
            <span className="text-[9px] uppercase tracking-wider text-cyan-300 font-semibold">
              SPACE WEATHER: STABLE
            </span>
          </div>
        </div>

        {/* Real Live Clock & Date */}
        <div className="text-right font-mono" aria-live="off" aria-label={`Current time: ${currentTime}, ${currentDate}`}>
          <div className="text-base md:text-lg font-bold text-white tracking-widest leading-none drop-shadow-sm">
            {currentTime}
          </div>
          <div className="text-[9px] font-semibold text-cyan-400/90 tracking-wider mt-0.5">
            {currentDate}
          </div>
        </div>
      </div>
    </header>
  );
};
