import React from 'react';
import { Activity } from 'lucide-react';

interface CenterpieceCoreProps {
  isStandby?: boolean;
  onCoreClick?: () => void;
}

export const CenterpieceCore: React.FC<CenterpieceCoreProps> = ({ isStandby, onCoreClick }) => {
  return (
    <div className="relative flex flex-col items-center justify-center my-3 select-none pointer-events-auto">
      {/* Text directly above center visualization */}
      <div className="flex items-center space-x-2 mb-2 px-3 py-1 rounded bg-black/60 border border-cyan-500/40 text-cyan-400 font-mono text-xs tracking-widest uppercase">
        <span className="w-2 h-2 rounded-full bg-cyan-400 animate-ping" />
        <Activity className="w-3.5 h-3.5 text-cyan-400" />
        <span className="font-semibold text-cyan-300">NEURAL CORE // ACTIVE</span>
      </div>

      {/* Absolutely centered 2D SVG graphic container */}
      <div
        onClick={onCoreClick}
        className="relative w-80 h-80 sm:w-96 sm:h-96 md:w-[440px] md:h-[440px] flex items-center justify-center cursor-pointer group"
      >
        {/* Subtle background circular flat plate */}
        <div className="absolute inset-4 rounded-full bg-black/40 border border-cyan-500/30 group-hover:border-cyan-400 transition-colors pointer-events-none" />

        {/* 2D Flat Vector SVG graphic */}
        <svg
          viewBox="0 0 500 500"
          className="w-full h-full relative z-10 overflow-visible"
        >
          <defs>
            {/* Gradients */}
            <radialGradient id="centerGlow" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor="#00ffff" stopOpacity="0.35" />
              <stop offset="60%" stopColor="#0891b2" stopOpacity="0.1" />
              <stop offset="100%" stopColor="#000000" stopOpacity="0" />
            </radialGradient>
            <radialGradient id="orangeGlow" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor="#f97316" stopOpacity="0.4" />
              <stop offset="70%" stopColor="#ea580c" stopOpacity="0.08" />
              <stop offset="100%" stopColor="#000000" stopOpacity="0" />
            </radialGradient>
          </defs>

          {/* Center ambient glow */}
          <circle cx="250" cy="250" r="140" fill="url(#centerGlow)" />
          <circle cx="250" cy="250" r="80" fill="url(#orangeGlow)" />

          {/* ======================================================== */}
          {/* 1. Geometric Polar Coordinate Grid (Spokes & Axes)        */}
          {/* ======================================================== */}
          <g stroke="currentColor" className="text-cyan-500/25" strokeWidth="0.75">
            {/* Crosshairs */}
            <line x1="20" y1="250" x2="480" y2="250" strokeDasharray="3 3" />
            <line x1="250" y1="20" x2="250" y2="480" strokeDasharray="3 3" />
            {/* Diagonal Spokes */}
            <line x1="87" y1="87" x2="413" y2="413" strokeDasharray="2 4" />
            <line x1="87" y1="413" x2="413" y2="87" strokeDasharray="2 4" />
            <line x1="40" y1="145" x2="460" y2="355" strokeDasharray="1 5" />
            <line x1="40" y1="355" x2="460" y2="145" strokeDasharray="1 5" />
            <line x1="145" y1="40" x2="355" y2="460" strokeDasharray="1 5" />
            <line x1="355" y1="40" x2="145" y2="460" strokeDasharray="1 5" />
          </g>

          {/* ======================================================== */}
          {/* 2. Concentric Wireframe Circles                          */}
          {/* ======================================================== */}
          {/* Outermost Boundary Circle */}
          <circle
            cx="250"
            cy="250"
            r="230"
            fill="none"
            stroke="#06b6d4"
            strokeWidth="0.8"
            strokeOpacity="0.4"
          />

          {/* Azimuth Compass Ticks & Degree Markings */}
          <g className="text-cyan-400 text-[8px] font-mono select-none" fill="currentColor">
            <text x="250" y="14" textAnchor="middle">000°</text>
            <text x="490" y="253" textAnchor="start">090°</text>
            <text x="250" y="494" textAnchor="middle">180°</text>
            <text x="10" y="253" textAnchor="end">270°</text>
            <text x="415" y="85" textAnchor="start">045°</text>
            <text x="415" y="420" textAnchor="start">135°</text>
            <text x="85" y="420" textAnchor="end">225°</text>
            <text x="85" y="85" textAnchor="end">315°</text>
          </g>

          {/* Rotating Dashed Outer Radar Ring */}
          <g className={isStandby ? '' : 'animate-spin-cw-slow'}>
            <circle
              cx="250"
              cy="250"
              r="215"
              fill="none"
              stroke="#22d3ee"
              strokeWidth="1.2"
              strokeDasharray="6 8"
              strokeOpacity="0.6"
            />
            {/* Outer Cardinal Triangles */}
            <polygon points="250,30 246,38 254,38" fill="#22d3ee" />
            <polygon points="250,470 246,462 254,462" fill="#22d3ee" />
            <polygon points="30,250 38,246 38,254" fill="#22d3ee" />
            <polygon points="470,250 462,246 462,254" fill="#22d3ee" />
          </g>

          {/* Reverse Rotating Segmented Ring */}
          <g className={isStandby ? '' : 'animate-spin-ccw-slow'}>
            <circle
              cx="250"
              cy="250"
              r="185"
              fill="none"
              stroke="#06b6d4"
              strokeWidth="1.5"
              strokeDasharray="24 16 8 16"
              strokeOpacity="0.75"
            />
            {/* Orange Segment Accent */}
            <circle
              cx="250"
              cy="250"
              r="185"
              fill="none"
              stroke="#f97316"
              strokeWidth="2"
              strokeDasharray="18 360"
              strokeDashoffset="60"
            />
            <circle
              cx="250"
              cy="250"
              r="185"
              fill="none"
              stroke="#f97316"
              strokeWidth="2"
              strokeDasharray="18 360"
              strokeDashoffset="240"
            />
          </g>

          {/* Concentric Wireframe Circle 3 */}
          <circle
            cx="250"
            cy="250"
            r="150"
            fill="none"
            stroke="#22d3ee"
            strokeWidth="0.8"
            strokeOpacity="0.5"
            strokeDasharray="4 4"
          />

          {/* ======================================================== */}
          {/* 3. Intersecting Orbital Paths (Cyan and Orange)          */}
          {/* ======================================================== */}
          {/* Orbit 1: Angled Cyan Ellipse (-35 deg) */}
          <g transform="rotate(-35 250 250)">
            <ellipse
              cx="250"
              cy="250"
              rx="195"
              ry="75"
              fill="none"
              stroke="#22d3ee"
              strokeWidth="1.4"
              strokeOpacity="0.7"
              strokeDasharray="5 3"
            />
            {/* Orbiting Satellite Node */}
            <circle cx="445" cy="250" r="3.5" fill="#22d3ee" />
            <circle cx="445" cy="250" r="7" fill="none" stroke="#22d3ee" strokeWidth="0.8" opacity="0.6" />
            <circle cx="55" cy="250" r="2.5" fill="#22d3ee" />
          </g>

          {/* Orbit 2: Angled Orange Ellipse (45 deg) */}
          <g transform="rotate(45 250 250)">
            <ellipse
              cx="250"
              cy="250"
              rx="185"
              ry="85"
              fill="none"
              stroke="#f97316"
              strokeWidth="1.6"
              strokeOpacity="0.85"
              strokeDasharray="6 4"
            />
            {/* Orange Orbital Nodes */}
            <circle cx="435" cy="250" r="4" fill="#fb923c" />
            <circle cx="435" cy="250" r="8" fill="none" stroke="#f97316" strokeWidth="0.9" opacity="0.7" />
            <circle cx="65" cy="250" r="3" fill="#f97316" />
          </g>

          {/* Orbit 3: Angled Cyan Ellipse (80 deg) */}
          <g transform="rotate(80 250 250)">
            <ellipse
              cx="250"
              cy="250"
              rx="160"
              ry="65"
              fill="none"
              stroke="#06b6d4"
              strokeWidth="1.2"
              strokeOpacity="0.65"
              strokeDasharray="3 3"
            />
            <circle cx="410" cy="250" r="3" fill="#06b6d4" />
          </g>

          {/* Orbit 4: Counter-angled Orange Ellipse (-70 deg) */}
          <g transform="rotate(-70 250 250)">
            <ellipse
              cx="250"
              cy="250"
              rx="145"
              ry="55"
              fill="none"
              stroke="#fb923c"
              strokeWidth="1.2"
              strokeOpacity="0.7"
              strokeDasharray="4 2"
            />
            <circle cx="395" cy="250" r="3" fill="#ea580c" />
          </g>

          {/* ======================================================== */}
          {/* 4. Geometric Wireframe Polygons (Dodecagon / Hexagon)     */}
          {/* ======================================================== */}
          {/* Cyan Inscribed Hexagon Wireframe */}
          <g className={isStandby ? '' : 'animate-spin-cw-fast'}>
            <polygon
              points="
                250,135
                349.6,192.5
                349.6,307.5
                250,365
                150.4,307.5
                150.4,192.5
              "
              fill="none"
              stroke="#22d3ee"
              strokeWidth="0.9"
              strokeOpacity="0.45"
            />
            {/* Hexagon Vertex Nodes */}
            <circle cx="250" cy="135" r="2.5" fill="#22d3ee" />
            <circle cx="349.6" cy="192.5" r="2.5" fill="#22d3ee" />
            <circle cx="349.6" cy="307.5" r="2.5" fill="#22d3ee" />
            <circle cx="250" cy="365" r="2.5" fill="#22d3ee" />
            <circle cx="150.4" cy="307.5" r="2.5" fill="#22d3ee" />
            <circle cx="150.4" cy="192.5" r="2.5" fill="#22d3ee" />
          </g>

          {/* Orange Nested Star Polygon */}
          <g className={isStandby ? '' : 'animate-spin-ccw-slow'}>
            <polygon
              points="
                250,165
                323.6,207.5
                323.6,292.5
                250,335
                176.4,292.5
                176.4,207.5
              "
              fill="none"
              stroke="#f97316"
              strokeWidth="1"
              strokeOpacity="0.5"
            />
            <polygon
              points="
                250,335
                176.4,292.5
                176.4,207.5
                250,165
                323.6,207.5
                323.6,292.5
              "
              transform="rotate(30 250 250)"
              fill="none"
              stroke="#f97316"
              strokeWidth="0.8"
              strokeOpacity="0.4"
            />
          </g>

          {/* ======================================================== */}
          {/* 5. Center Core Nucleus & Tactical Reticles               */}
          {/* ======================================================== */}
          {/* Inner Circle 1 */}
          <circle
            cx="250"
            cy="250"
            r="60"
            fill="none"
            stroke="#22d3ee"
            strokeWidth="1.2"
            strokeOpacity="0.65"
          />

          {/* Inner Circle 2 (Orange) */}
          <circle
            cx="250"
            cy="250"
            r="38"
            fill="none"
            stroke="#f97316"
            strokeWidth="1.5"
            strokeDasharray="8 6"
          />

          {/* Core Pulsing Center Dot */}
          <circle cx="250" cy="250" r="14" fill="#00ffff" fillOpacity="0.85" className="animate-pulse" />
          <circle cx="250" cy="250" r="5" fill="#ffffff" />

          {/* Callout Indicator Line pointing to Cosmic Engine Core */}
          <g className="text-[9px] font-mono select-none">
            <polyline
              points="190,230 145,230 120,205"
              fill="none"
              stroke="#22d3ee"
              strokeWidth="1"
              strokeOpacity="0.75"
            />
            <circle cx="190" cy="230" r="2" fill="#22d3ee" />
            <text x="115" y="200" fill="#22d3ee" textAnchor="end" className="tracking-wider">
              [-- Cosmic Engine Core
            </text>
            <text x="115" y="212" fill="#06b6d4" textAnchor="end" className="text-[7.5px] opacity-75">
              14.82 THz // RES: 99.8%
            </text>
          </g>
        </svg>

        {/* Tactical Telemetry Corner Labels */}
        <div className="absolute top-1 left-2 text-[9px] font-mono text-cyan-400/80 bg-black/60 px-1.5 py-0.5 border border-cyan-500/30 rounded">
          AZ: 045.2°
        </div>
        <div className="absolute top-1 right-2 text-[9px] font-mono text-cyan-400/80 bg-black/60 px-1.5 py-0.5 border border-cyan-500/30 rounded">
          EL: +18.4°
        </div>
        <div className="absolute bottom-1 left-2 text-[9px] font-mono text-cyan-400/80 bg-black/60 px-1.5 py-0.5 border border-cyan-500/30 rounded">
          GRID: HEX-09
        </div>
        <div className="absolute bottom-1 right-2 text-[9px] font-mono text-orange-400/90 bg-black/60 px-1.5 py-0.5 border border-orange-500/40 rounded">
          SYNC: 98.6%
        </div>
      </div>
    </div>
  );
};
