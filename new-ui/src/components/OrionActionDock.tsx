import React from 'react';
import {
  Code,
  Clipboard,
  Brain,
  Terminal,
  Mic,
  Settings,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { sfx } from '../utils/audio';

export interface ActionCardItem {
  id: string;
  tag: string;
  title: string;
  icon: LucideIcon;
  rotation: string;
  isAmber?: boolean;
}

const CARDS: ActionCardItem[] = [
  {
    id: 'debug',
    tag: 'F1',
    title: 'DEBUG SCREEN',
    icon: Code,
    rotation: '-rotate-[6deg] -translate-y-1',
  },
  {
    id: 'clipboard',
    tag: 'F2',
    title: 'CLIPBOARD COPILOT',
    icon: Clipboard,
    rotation: '-rotate-[3deg] translate-y-1',
  },
  {
    id: 'memory',
    tag: 'F3',
    title: 'RECALL MEMORY',
    icon: Brain,
    rotation: 'rotate-0 translate-y-2',
  },
  {
    id: 'dev',
    tag: 'F4',
    title: 'DEV WORKSPACE',
    icon: Terminal,
    rotation: 'rotate-0 translate-y-2',
  },
  {
    id: 'voice',
    tag: 'F5',
    title: 'VOICE MEMO',
    icon: Mic,
    rotation: 'rotate-[3deg] translate-y-1',
  },
  {
    id: 'purge',
    tag: 'F6',
    title: 'SYSTEM PURGE',
    icon: Settings,
    rotation: 'rotate-[6deg] -translate-y-1',
    isAmber: true,
  },
];

interface OrionActionDockProps {
  onCardClick: (id: string) => void;
  activeCardId?: string | null;
}

export const OrionActionDock: React.FC<OrionActionDockProps> = ({
  onCardClick,
  activeCardId,
}) => {
  return (
    <div
      role="toolbar"
      aria-label="Subsystem Action Dock"
      className="w-full max-w-4xl mx-auto z-30 select-none"
    >
      {/* Horizontal Staggered Arc of the 6 Glass Cards */}
      <div className="flex items-center justify-center space-x-2 md:space-x-3.5">
        {CARDS.map((card) => {
          const IconComponent = card.icon;
          const isActive = activeCardId === card.id;

          return (
            <button
              key={card.id}
              onClick={() => {
                if (card.isAmber) {
                  sfx.alert();
                } else {
                  sfx.chime();
                }
                onCardClick(card.id);
              }}
              onMouseEnter={() => sfx.click()}
              aria-label={`${card.title} (Shortcut: ${card.tag})`}
              aria-keyshortcuts={card.tag}
              aria-pressed={isActive}
              style={{
                transformOrigin: 'bottom center',
              }}
              className={`
                group relative flex flex-col justify-between items-center
                w-24 h-20 sm:w-28 sm:h-22 md:w-34 md:h-24 p-2.5 rounded-xl cursor-pointer
                ${card.rotation}
                ${card.isAmber ? 'spring-card-amber' : 'spring-card'}
                hologram-shimmer
                backdrop-blur-xl
                focus-visible:ring-2 focus-visible:ring-cyan-300 focus-visible:outline-none
                ${
                  isActive
                    ? 'bg-cyan-950/90 border-2 border-cyan-300 shadow-[0_0_35px_rgba(0,255,255,0.95),inset_0_0_20px_rgba(0,255,255,0.4)] -translate-y-3 scale-105'
                    : card.isAmber
                    ? 'bg-[#041a2e]/75 border border-orange-500/50 shadow-[0_0_20px_rgba(249,115,22,0.35),inset_0_0_12px_rgba(249,115,22,0.15)]'
                    : 'bg-[#041a2e]/75 border border-cyan-400/70 shadow-[0_0_20px_rgba(0,255,255,0.35),inset_0_0_12px_rgba(0,255,255,0.15)]'
                }
              `}
            >
              {/* Corner holographic tick marks */}
              <div className="absolute top-1 left-1 w-1.5 h-1.5 border-t border-l border-cyan-300/80 pointer-events-none" />
              <div className="absolute top-1 right-1 w-1.5 h-1.5 border-t border-r border-cyan-300/80 pointer-events-none" />
              <div className="absolute bottom-1 left-1 w-1.5 h-1.5 border-b border-l border-cyan-300/80 pointer-events-none" />
              <div className="absolute bottom-1 right-1 w-1.5 h-1.5 border-b border-r border-cyan-300/80 pointer-events-none" />

              {/* Tag header */}
              <div className="w-full flex items-center justify-between text-[9px] font-mono text-cyan-400/70">
                <span className="bg-black/60 px-1 rounded border border-cyan-500/30 text-cyan-300">
                  {card.tag}
                </span>
                <span className={`w-1.5 h-1.5 rounded-full ${card.isAmber ? 'bg-orange-400' : 'bg-cyan-400'} group-hover:animate-ping`} />
              </div>

              {/* Neon Cyan Icon */}
              <div className="my-auto">
                <IconComponent
                  className={`w-5 h-5 md:w-6 md:h-6 ${
                    card.isAmber
                      ? 'text-orange-400 group-hover:text-orange-200'
                      : 'text-cyan-300 group-hover:text-cyan-100'
                  } group-hover:scale-110 transition-all drop-shadow-[0_0_8px_rgba(0,255,255,0.9)]`}
                />
              </div>

              {/* Card Title Label in high contrast */}
              <div className="w-full text-center">
                <span className="font-['Orbitron'] font-bold text-[8px] md:text-[9.5px] tracking-wider text-slate-100 group-hover:text-cyan-200 uppercase whitespace-nowrap block drop-shadow-sm">
                  {card.title}
                </span>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
};
