import React, { useState } from 'react';
import {
  Sun,
  Lock,
  Unlock,
  Folder,
  Mic,
  Crosshair,
  Sliders,
  VolumeX,
} from 'lucide-react';
import { sfx } from '../utils/audio';

interface MetallicTopHeaderProps {
  isStandby: boolean;
  onToggleStandby: () => void;
  brightness: number;
  onChangeBrightness: (val: number) => void;
  onVoiceClick: () => void;
  soundEnabled: boolean;
  onToggleSound: () => void;
}

export const MetallicTopHeader: React.FC<MetallicTopHeaderProps> = ({
  isStandby,
  onToggleStandby,
  brightness,
  onChangeBrightness,
  onVoiceClick,
  soundEnabled,
  onToggleSound,
}) => {
  const [knob1Rot, setKnob1Rot] = useState(45);
  const [knob2Rot, setKnob2Rot] = useState(120);
  const [masterRot, setMasterRot] = useState(210);
  const [isLocked, setIsLocked] = useState(true);
  const [rocker1, setRocker1] = useState(true);
  const [rocker2, setRocker2] = useState(false);
  const [showFolderTooltip, setShowFolderTooltip] = useState(false);

  const handleRotateKnob = (
    setter: React.Dispatch<React.SetStateAction<number>>,
    delta: number
  ) => {
    sfx.click();
    setter((prev) => (prev + delta) % 360);
  };

  return (
    <div className="relative w-full max-w-5xl mx-auto z-40 select-none">
      {/* Brushed Metallic Chassis Container */}
      <div
        className="relative rounded-full px-5 py-3 md:px-7 md:py-3.5 flex items-center justify-between shadow-[0_15px_35px_rgba(0,0,0,0.9),inset_0_1px_1px_rgba(255,255,255,0.4),inset_0_-2px_4px_rgba(0,0,0,0.8)] border border-slate-600/60"
        style={{
          background:
            'linear-gradient(180deg, #475569 0%, #334155 12%, #1e293b 50%, #0f172a 88%, #334155 100%)',
        }}
      >
        {/* Subtle metallic brushed sheen texture */}
        <div className="absolute inset-0 rounded-full bg-gradient-to-r from-transparent via-white/10 to-transparent pointer-events-none" />

        {/* ========================================================== */}
        {/* LEFT SECTION: Logo, ORION Title, and Dual Rotary Knobs    */}
        {/* ========================================================== */}
        <div className="flex items-center space-x-3 md:space-x-4">
          {/* Glowing Amber Core Indicator */}
          <div className="relative flex items-center justify-center w-5 h-5 rounded-full bg-black/80 border border-slate-500 shadow-inner">
            <span className="w-2.5 h-2.5 rounded-full bg-amber-400 shadow-[0_0_10px_#fbbf24] animate-pulse" />
          </div>

          <div className="flex flex-col">
            <h1 className="font-['Orbitron'] font-extrabold text-sm md:text-base tracking-[0.28em] text-slate-100 uppercase drop-shadow-md">
              O R I O N
            </h1>
            <span className="text-[9px] md:text-[10px] font-['Rajdhani'] font-bold tracking-[0.2em] text-slate-400 -mt-0.5">
              DEEP SPACE INTELLIGENCE
            </span>
          </div>

          {/* Dual Knurled Metallic Knobs */}
          <div className="hidden sm:flex items-center space-x-2 pl-2 border-l border-slate-700/60">
            {/* Knob 1: Gain */}
            <div
              onClick={() => handleRotateKnob(setKnob1Rot, 30)}
              title="Input Gain (Click to rotate)"
              className="relative w-7 h-7 rounded-full bg-gradient-to-b from-slate-400 to-slate-800 border border-slate-400/80 shadow-md cursor-pointer active:scale-95 transition-transform"
            >
              {/* Knurled notch */}
              <div
                className="absolute top-1 left-1/2 w-0.5 h-2 bg-cyan-400 rounded-full -translate-x-1/2 transition-transform duration-200"
                style={{ transform: `rotate(${knob1Rot}deg) translateY(-2px)` }}
              />
            </div>

            {/* Knob 2: Frequency */}
            <div
              onClick={() => handleRotateKnob(setKnob2Rot, 30)}
              title="Resonance Frequency (Click to rotate)"
              className="relative w-7 h-7 rounded-full bg-gradient-to-b from-slate-400 to-slate-800 border border-slate-400/80 shadow-md cursor-pointer active:scale-95 transition-transform"
            >
              <div
                className="absolute top-1 left-1/2 w-0.5 h-2 bg-amber-400 rounded-full -translate-x-1/2 transition-transform duration-200"
                style={{ transform: `rotate(${knob2Rot}deg) translateY(-2px)` }}
              />
            </div>
          </div>
        </div>

        {/* ========================================================== */}
        {/* CENTER SECTION: Standby, Sliders, Folder, Hey Orion, EQ   */}
        {/* ========================================================== */}
        <div className="flex items-center space-x-2 md:space-x-3 bg-black/50 border border-slate-700/70 rounded-full px-3 py-1.5 shadow-inner">
          {/* + Standby Pill Button */}
          <button
            onClick={onToggleStandby}
            title={isStandby ? 'Wake System' : 'Engage Standby Mode'}
            className={`px-3 py-1 rounded-full text-[10px] md:text-xs font-['Orbitron'] font-bold tracking-wider cursor-pointer transition-all ${
              isStandby
                ? 'bg-cyan-500 text-black shadow-[0_0_12px_#00ffff]'
                : 'bg-slate-800/90 text-slate-200 hover:bg-slate-700 border border-slate-600/70'
            }`}
          >
            + Standby
          </button>

          {/* Brightness Slider with Sun Icon */}
          <div className="hidden lg:flex items-center space-x-1.5 px-2">
            <Sun className="w-3.5 h-3.5 text-slate-400" />
            <input
              type="range"
              min="30"
              max="130"
              value={brightness}
              onChange={(e) => onChangeBrightness(Number(e.target.value))}
              title={`Nebula Brightness: ${brightness}%`}
              className="w-16 h-1 bg-slate-700 rounded-full appearance-none cursor-pointer accent-cyan-400"
            />
          </div>

          {/* Security Lock Toggle */}
          <button
            onClick={() => {
              sfx.click();
              setIsLocked(!isLocked);
            }}
            title={isLocked ? 'Zero-Trust Policy: LOCKED' : 'Zero-Trust Policy: UNLOCKED'}
            className="p-1 rounded text-slate-400 hover:text-cyan-300 transition-colors cursor-pointer"
          >
            {isLocked ? <Lock className="w-3.5 h-3.5 text-cyan-400" /> : <Unlock className="w-3.5 h-3.5 text-amber-400" />}
          </button>

          {/* Folder 138K Button */}
          <div className="relative">
            <button
              onClick={() => {
                sfx.click();
                setShowFolderTooltip(!showFolderTooltip);
              }}
              title="138K Synaptic Memory Vectors"
              className="hidden sm:flex items-center space-x-1 px-2 py-0.5 bg-slate-800/80 border border-slate-600/60 rounded text-[10px] font-mono text-slate-300 hover:text-cyan-300 cursor-pointer"
            >
              <Folder className="w-3 h-3 text-cyan-400" />
              <span>138K</span>
            </button>
            {showFolderTooltip && (
              <div className="absolute top-8 left-0 w-44 bg-black/90 border border-cyan-500/50 p-2 rounded shadow-lg text-[9px] font-mono text-cyan-300 z-50">
                <div>NECTAR ATLAS STORAGE:</div>
                <div className="text-white font-bold">138,420 VECTORS</div>
                <div className="text-slate-400 mt-1">CAPACITY: 48.2% FULL</div>
              </div>
            )}
          </div>

          {/* ((•)) Hey Orion Voice Button */}
          <button
            onClick={() => {
              sfx.chime();
              onVoiceClick();
            }}
            title="Trigger Subspace Voice Listener"
            className="flex items-center space-x-1.5 px-3 py-1 rounded-full bg-cyan-950/50 border border-cyan-400/60 text-[10px] md:text-xs font-['Rajdhani'] font-bold text-cyan-300 hover:bg-cyan-500 hover:text-black hover:shadow-[0_0_15px_rgba(0,255,255,0.6)] cursor-pointer transition-all"
          >
            <Mic className="w-3.5 h-3.5 text-cyan-400 animate-pulse" />
            <span>Hey orion</span>
          </button>

          {/* Reticle / Compass */}
          <button
            onClick={() => sfx.click()}
            title="Recenter Star Chart"
            className="p-1 rounded text-slate-400 hover:text-cyan-300 transition-colors cursor-pointer hidden md:block"
          >
            <Crosshair className="w-3.5 h-3.5" />
          </button>

          {/* Audio Equalizer */}
          <button
            onClick={() => {
              sfx.click();
              onToggleSound();
            }}
            title={soundEnabled ? 'Interface Sound Active' : 'Sound Muted'}
            className="p-1 rounded text-slate-400 hover:text-cyan-300 transition-colors cursor-pointer"
          >
            {soundEnabled ? <Sliders className="w-3.5 h-3.5 text-cyan-400" /> : <VolumeX className="w-3.5 h-3.5 text-slate-500" />}
          </button>
        </div>

        {/* ========================================================== */}
        {/* RIGHT SECTION: Master Knurled Dial & Rocker Switches      */}
        {/* ========================================================== */}
        <div className="flex items-center space-x-3">
          {/* Dual Horizontal Rocker Switches */}
          <div className="hidden sm:flex flex-col space-y-1">
            <button
              onClick={() => {
                sfx.click();
                setRocker1(!rocker1);
              }}
              title="Auxiliary Bus Switch"
              className={`w-9 h-3 rounded-sm border cursor-pointer transition-colors ${
                rocker1
                  ? 'bg-cyan-950 border-cyan-400/80 shadow-[0_0_8px_rgba(0,255,255,0.4)]'
                  : 'bg-slate-800 border-slate-600'
              }`}
            />
            <button
              onClick={() => {
                sfx.click();
                setRocker2(!rocker2);
              }}
              title="Telemetry Beacon Switch"
              className={`w-9 h-3 rounded-sm border cursor-pointer transition-colors ${
                rocker2
                  ? 'bg-amber-950 border-amber-400/80 shadow-[0_0_8px_rgba(251,146,60,0.4)]'
                  : 'bg-slate-800 border-slate-600'
              }`}
            />
          </div>

          {/* Large Master Rotary Dial */}
          <div
            onClick={() => handleRotateKnob(setMasterRot, 45)}
            title="Master Celestial Tuner (Click to rotate)"
            className="relative w-9 h-9 md:w-11 md:h-11 rounded-full bg-gradient-to-tr from-slate-900 via-slate-500 to-slate-200 border-2 border-slate-400 shadow-[0_4px_10px_rgba(0,0,0,0.8)] cursor-pointer active:scale-95 transition-transform"
          >
            {/* Dial knurled rim */}
            <div className="absolute inset-1 rounded-full bg-slate-800 border border-slate-600 flex items-center justify-center">
              {/* Position Indicator dot */}
              <div
                className="w-1.5 h-1.5 rounded-full bg-cyan-400 shadow-[0_0_6px_#00ffff] transition-transform duration-200"
                style={{ transform: `rotate(${masterRot}deg) translateY(-11px)` }}
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
