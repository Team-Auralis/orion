import React from 'react';
import {
  Bug,
  Clipboard,
  Brain,
  Terminal,
  Mic,
  Cpu,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { sfx } from '../utils/audio';

export interface ActionCardItem {
  id: string;
  tag: string;
  title: string;
  icon: LucideIcon;
  transform: string;
  isAmber?: boolean;
}

const CARDS: ActionCardItem[] = [
  {
    id: 'debug',
    tag: 'F1',
    title: 'DEBUG SCREEN',
    icon: Bug,
    transform: 'rotateY(-14deg) translateZ(-10px) translateY(8px)',
  },
  {
    id: 'clipboard',
    tag: 'F2',
    title: 'CLIPBOARD COPILOT',
    icon: Clipboard,
    transform: 'rotateY(-7deg) translateZ(6px) translateY(2px)',
  },
  {
    id: 'memory',
    tag: 'F3',
    title: 'RECALL MEMORY',
    icon: Brain,
    transform: 'rotateY(-2deg) translateZ(18px) translateY(-4px)',
  },
  {
    id: 'dev',
    tag: 'F4',
    title: 'DEV WORKSPACE',
    icon: Terminal,
    transform: 'rotateY(2deg) translateZ(18px) translateY(-4px)',
  },
  {
    id: 'voice',
    tag: 'F5',
    title: 'VOICE MEMO',
    icon: Mic,
    transform: 'rotateY(7deg) translateZ(6px) translateY(2px)',
  },
  {
    id: 'purge',
    tag: 'F6',
    title: 'SYSTEM PURGE',
    icon: Cpu,
    transform: 'rotateY(14deg) translateZ(-10px) translateY(8px)',
    isAmber: true,
  },
];

interface ActionArcCardsProps {
  onSelectAction: (id: string) => void;
  activeActionId?: string | null;
}

export const ActionArcCards: React.FC<ActionArcCardsProps> = ({
  onSelectAction,
  activeActionId,
}) => {
  return (
    <div className="relative w-full max-w-6xl mx-auto px-2 z-30 select-none">
      {/* 3D Curved Perspective Stage Container */}
      <div
        className="flex items-center justify-center space-x-2 md:space-x-3.5 py-4"
        style={{ perspective: '1100px' }}
      >
        {/* Left Arrow Button */}
        <button
          onClick={() => sfx.click()}
          title="Previous Actions"
          className="p-2 md:p-3 rounded-xl bg-black/50 border border-cyan-500/40 text-cyan-400 hover:text-cyan-200 hover:border-cyan-300 hover:shadow-[0_0_15px_#00ffff] transition-all cursor-pointer"
        >
          <ChevronLeft className="w-4 h-4 md:w-5 md:h-5" />
        </button>

        {/* The 6 3D Holographic Glass Cards */}
        {CARDS.map((card) => {
          const IconComponent = card.icon;
          const isActive = activeActionId === card.id;

          return (
            <div
              key={card.id}
              onClick={() => {
                if (card.id === 'purge') {
                  sfx.alert();
                } else {
                  sfx.chime();
                }
                onSelectAction(card.id);
              }}
              onMouseEnter={() => sfx.click()}
              style={{
                transform: card.transform,
              }}
              className={`
                group relative flex flex-col justify-between items-center
                w-24 h-28 sm:w-28 sm:h-32 md:w-36 md:h-38 p-2.5 md:p-3
                rounded-xl cursor-pointer transition-all duration-300 transform-gpu
                backdrop-blur-md
                ${
                  isActive
                    ? 'bg-cyan-950/70 border-2 border-cyan-300 shadow-[0_0_35px_rgba(0,255,255,0.9),inset_0_0_20px_rgba(0,255,255,0.4)] -translate-y-2 scale-105'
                    : card.isAmber
                    ? 'bg-black/55 border border-cyan-500/40 hover:border-orange-400 hover:shadow-[0_0_30px_rgba(249,115,22,0.8),inset_0_0_15px_rgba(249,115,22,0.3)] hover:-translate-y-2 hover:scale-105'
                    : 'bg-black/55 border border-cyan-500/40 hover:border-cyan-300 hover:shadow-[0_0_30px_rgba(0,255,255,0.8),inset_0_0_15px_rgba(0,255,255,0.3)] hover:-translate-y-2 hover:scale-105'
                }
              `}
            >
              {/* Corner holographic ticks */}
              <div className="absolute top-1 left-1 w-2 h-2 border-t border-l border-cyan-400/60 pointer-events-none" />
              <div className="absolute top-1 right-1 w-2 h-2 border-t border-r border-cyan-400/60 pointer-events-none" />
              <div className="absolute bottom-1 left-1 w-2 h-2 border-b border-l border-cyan-400/60 pointer-events-none" />
              <div className="absolute bottom-1 right-1 w-2 h-2 border-b border-r border-cyan-400/60 pointer-events-none" />

              {/* Card Header: Tag & Dot */}
              <div className="w-full flex items-center justify-between text-[9px] font-mono text-cyan-400/70">
                <span className="bg-black/60 px-1 rounded border border-cyan-500/30 text-cyan-300">
                  {card.tag}
                </span>
                <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 group-hover:animate-ping" />
              </div>

              {/* Neon Cyan Icon */}
              <div className="my-auto p-2 rounded-lg bg-cyan-950/40 border border-cyan-500/30 group-hover:border-cyan-300 transition-colors">
                <IconComponent
                  className={`w-6 h-6 md:w-8 md:h-8 ${
                    card.isAmber
                      ? 'text-orange-400 group-hover:text-orange-200'
                      : 'text-cyan-400 group-hover:text-cyan-200'
                  } drop-shadow-[0_0_8px_rgba(0,255,255,0.8)]`}
                />
              </div>

              {/* Tech Label in Orbitron Bold */}
              <div className="w-full text-center mt-1">
                <span className="font-['Orbitron'] font-bold text-[9px] md:text-[11px] text-slate-100 group-hover:text-cyan-200 uppercase tracking-wider block whitespace-nowrap">
                  {card.title}
                </span>
              </div>
            </div>
          );
        })}

        {/* Right Arrow Button */}
        <button
          onClick={() => sfx.click()}
          title="Next Actions"
          className="p-2 md:p-3 rounded-xl bg-black/50 border border-cyan-500/40 text-cyan-400 hover:text-cyan-200 hover:border-cyan-300 hover:shadow-[0_0_15px_#00ffff] transition-all cursor-pointer"
        >
          <ChevronRight className="w-4 h-4 md:w-5 md:h-5" />
        </button>
      </div>
    </div>
  );
};
