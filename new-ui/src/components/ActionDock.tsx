import React from 'react';
import {
  Terminal,
  Cpu,
  ShieldAlert,
  Network,
  Scan,
  Grid,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { sfx } from '../utils/audio';

export interface FlatActionButton {
  id: string;
  tag: string;
  title: string;
  icon: LucideIcon;
  color?: string;
}

const ACTION_BUTTONS: FlatActionButton[] = [
  {
    id: 'debug',
    tag: 'F1',
    title: 'DEBUG SCREEN',
    icon: Terminal,
  },
  {
    id: 'memory',
    tag: 'F2',
    title: 'RECALL MEMORY',
    icon: Cpu,
  },
  {
    id: 'purge',
    tag: 'F3',
    title: 'SYSTEM PURGE',
    icon: ShieldAlert,
    color: 'text-orange-400',
  },
  {
    id: 'neural',
    tag: 'F4',
    title: 'NEURAL LINK',
    icon: Network,
  },
  {
    id: 'scan',
    tag: 'F5',
    title: 'DEEP SCAN',
    icon: Scan,
  },
  {
    id: 'matrix',
    tag: 'F6',
    title: 'QUANTUM MATRIX',
    icon: Grid,
  },
];

interface ActionDockProps {
  onSelectAction: (cardId: string) => void;
  activeActionId?: string | null;
}

export const ActionDock: React.FC<ActionDockProps> = ({ onSelectAction, activeActionId }) => {
  return (
    <div className="w-full max-w-4xl mx-auto px-4 z-30 select-none">
      {/* Precise Horizontal Row of Exactly Six Square, Flat Buttons */}
      <div className="grid grid-cols-3 sm:grid-cols-6 gap-2.5 md:gap-3.5 items-center justify-center">
        {ACTION_BUTTONS.map((btn) => {
          const IconComponent = btn.icon;
          const isActive = activeActionId === btn.id;

          return (
            <button
              key={btn.id}
              onClick={() => {
                if (btn.id === 'purge') {
                  sfx.alert();
                } else {
                  sfx.chime();
                }
                onSelectAction(btn.id);
              }}
              className={`
                relative aspect-square flex flex-col justify-between items-center p-2.5 md:p-3
                bg-black/60 border rounded-none cursor-pointer transition-all duration-200
                corner-bracket
                ${
                  isActive
                    ? 'border-cyan-300 shadow-[0_0_20px_rgba(0,255,255,0.7)] bg-cyan-950/40 text-cyan-200'
                    : 'border-cyan-500/40 text-cyan-400 hover:border-cyan-300 hover:shadow-[0_0_20px_rgba(0,255,255,0.65)] hover:bg-black/80 hover:text-cyan-200'
                }
              `}
              title={`${btn.title} [${btn.tag}]`}
            >
              {/* Small 'F1' through 'F6' tags in the top left corner */}
              <div className="w-full flex items-center justify-between">
                <span className="text-[10px] font-mono font-bold text-cyan-400/90 tracking-wider">
                  {btn.tag}
                </span>
                <span className="w-1 h-1 rounded-full bg-cyan-400/70" />
              </div>

              {/* Vector Icon */}
              <div className="my-auto py-1">
                <IconComponent
                  className={`w-6 h-6 md:w-7 md:h-7 ${btn.color || 'text-cyan-400'} transition-transform group-hover:scale-105`}
                />
              </div>

              {/* Bottom Label in Monospaced Cyan Text */}
              <div className="w-full text-center">
                <span className="font-['Orbitron'] font-bold text-[9px] md:text-[10px] tracking-wider uppercase block leading-tight">
                  {btn.title}
                </span>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
};
