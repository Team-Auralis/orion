import React from 'react';

interface OrionCenterCoreProps {
  onInspectCore: () => void;
}

export const OrionCenterCore: React.FC<OrionCenterCoreProps> = ({ onInspectCore }) => {
  return (
    <div className="relative w-full max-w-4xl mx-auto flex items-center justify-center my-0 pointer-events-auto select-none">
      {/* Central Armillary Core & Pedestal Artwork */}
      <div
        onClick={onInspectCore}
        title="Cosmic Engine Core (Click to Inspect)"
        className="relative w-[340px] sm:w-[460px] md:w-[620px] lg:w-[720px] aspect-[990/690] cursor-pointer group"
      >
        <img
          src="/orion_assets/armillary_sphere_pedestal.png"
          alt="Cosmic Engine Core"
          className="w-full h-full object-contain filter drop-shadow-[0_0_40px_rgba(0,0,0,0.9)] transition-transform duration-700 group-hover:scale-[1.02]"
        />

        {/* Dynamic Rotating Holographic Reticles over the Sphere */}
        <div className="absolute left-[20%] top-[8%] w-[60%] h-[65%] pointer-events-none flex items-center justify-center">
          <svg viewBox="0 0 500 500" className="w-full h-full animate-spin-cw-slow opacity-25">
            <circle cx="250" cy="250" r="235" fill="none" stroke="#00ffff" strokeWidth="0.8" strokeDasharray="6 10" />
            <circle cx="250" cy="250" r="190" fill="none" stroke="#f97316" strokeWidth="1" strokeDasharray="4 8" opacity="0.6" />
          </svg>
        </div>

        {/* Ambient Pulsing Core Backlight */}
        <div className="absolute left-[35%] top-[20%] w-[30%] h-[35%] rounded-full bg-cyan-400/10 blur-[45px] pointer-events-none animate-pulse-glow" />
      </div>
    </div>
  );
};
