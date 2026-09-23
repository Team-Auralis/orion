import React from 'react';

interface NebulaBackgroundProps {
  isStandby: boolean;
}

export const NebulaBackground: React.FC<NebulaBackgroundProps> = ({ isStandby }) => {
  return (
    <div className="fixed inset-0 w-full h-full pointer-events-none select-none z-0 overflow-hidden">
      {/* Full-screen Deep Space Nebula Image */}
      <div
        className={`absolute inset-0 bg-cover bg-center transition-all duration-1000 transform ${
          isStandby ? 'scale-105 filter brightness-40 saturate-50' : 'scale-100 filter brightness-90 contrast-110'
        }`}
        style={{
          backgroundImage: "url('/nebula.jpg')",
        }}
      />

      {/* Deep Space Vignette & Ambient Radial Glow (Dark Blues & Amber Accentuation) */}
      <div className="absolute inset-0 bg-gradient-to-t from-[#020617] via-transparent to-[#020617]/80" />
      <div className="absolute inset-0 bg-gradient-to-r from-[#020617]/70 via-transparent to-[#020617]/70" />
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(0,255,255,0.06)_0%,transparent_65%)]" />

      {/* Sci-Fi Subtle Coordinate Grid Mesh */}
      <div 
        className="absolute inset-0 opacity-[0.07]"
        style={{
          backgroundImage: `
            linear-gradient(to right, rgba(0, 255, 255, 0.4) 1px, transparent 1px),
            linear-gradient(to bottom, rgba(0, 255, 255, 0.4) 1px, transparent 1px)
          `,
          backgroundSize: '80px 80px'
        }}
      />

      {/* Holographic Scanline Overlay */}
      <div 
        className="absolute inset-0 pointer-events-none opacity-[0.03]"
        style={{
          backgroundImage: 'repeating-linear-gradient(0deg, #000, #000 2px, transparent 2px, transparent 4px)',
        }}
      />
    </div>
  );
};
