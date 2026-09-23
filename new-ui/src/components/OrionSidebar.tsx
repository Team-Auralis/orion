import React from 'react';
import {
  Home,
  MessageCircle,
  Search,
  Code2,
  Database,
  Settings,
  Globe,
  Box,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { sfx } from '../utils/audio';

interface NavItem {
  id: string;
  label: string;
  icon: LucideIcon;
  keyNumber: string;
}

const NAV_ITEMS: NavItem[] = [
  { id: 'HOME', label: 'HOME', icon: Home, keyNumber: '1' },
  { id: 'CHAT', label: 'CHAT', icon: MessageCircle, keyNumber: '2' },
  { id: 'RESEARCH', label: 'RESEARCH', icon: Search, keyNumber: '3' },
  { id: 'DEV STUDIO', label: 'DEV STUDIO', icon: Code2, keyNumber: '4' },
  { id: 'MEMORY', label: 'MEMORY', icon: Database, keyNumber: '5' },
  { id: 'SYSTEM', label: 'SYSTEM', icon: Settings, keyNumber: '6' },
  { id: 'GALAXY MAP', label: 'GALAXY MAP', icon: Globe, keyNumber: '7' },
  { id: 'TOOLS', label: 'TOOLS', icon: Box, keyNumber: '8' },
];

interface OrionSidebarProps {
  activeTab: string;
  onTabSelect: (tab: string) => void;
}

export const OrionSidebar: React.FC<OrionSidebarProps> = ({
  activeTab,
  onTabSelect,
}) => {
  return (
    <aside
      aria-label="Orion Core Navigation"
      className="w-44 lg:w-48 flex flex-col justify-between p-3.5 rounded-2xl bg-slate-950/60 backdrop-blur-xl border border-cyan-500/25 shadow-[0_0_30px_rgba(0,0,0,0.85),inset_0_0_15px_rgba(0,255,255,0.03)] select-none z-30"
    >
      {/* Navigation Buttons List */}
      <nav role="tablist" aria-orientation="vertical" className="space-y-1.5">
        {NAV_ITEMS.map((item) => {
          const IconComponent = item.icon;
          const isActive = activeTab === item.id;

          return (
            <button
              key={item.id}
              role="tab"
              id={`tab-${item.id}`}
              aria-selected={isActive}
              aria-controls={`tabpanel-${item.id}`}
              onClick={() => {
                sfx.click();
                onTabSelect(item.id);
              }}
              className={`
                w-full flex items-center justify-between px-3.5 py-2.5 rounded-xl font-['Rajdhani'] font-bold text-xs tracking-wider transition-all duration-200 cursor-pointer
                focus-visible:ring-2 focus-visible:ring-cyan-300 focus-visible:outline-none
                ${
                  isActive
                    ? 'bg-gradient-to-r from-cyan-600/40 via-blue-600/30 to-transparent border border-cyan-400 text-white shadow-[0_0_15px_rgba(0,255,255,0.4)]'
                    : 'text-slate-400 hover:text-cyan-300 hover:bg-white/5 border border-transparent hover:border-cyan-500/20'
                }
              `}
            >
              <div className="flex items-center space-x-3">
                <IconComponent
                  className={`w-4 h-4 shrink-0 ${
                    isActive ? 'text-cyan-300 drop-shadow-[0_0_6px_#00ffff]' : 'text-slate-400'
                  }`}
                />
                <span className="truncate">{item.label}</span>
              </div>
              <span className="text-[9px] font-mono text-cyan-500/40 hidden sm:inline">
                [{item.keyNumber}]
              </span>
            </button>
          );
        })}
      </nav>

      {/* Bottom Quote & Version Stamp */}
      <div className="pt-4 border-t border-slate-800/80 mt-3 font-mono">
        <div className="text-[10px] text-slate-200 tracking-wide leading-tight">
          "INTELLIGENCE BEYOND ORIGINS."
        </div>
        <div className="text-[8px] text-slate-400 tracking-wider mt-1 uppercase leading-tight">
          FATHER OF JARVIS.
          <br />
          SON OF ULTRON.
        </div>

        <div className="w-6 h-[1px] bg-slate-700 my-2" />

        {/* Version Badge */}
        <div className="flex items-center space-x-1.5 text-[10px] font-bold text-slate-200">
          <span className="text-cyan-400">⬡</span>
          <span>ORION v31.0</span>
        </div>
        <div className="text-[8px] font-bold text-cyan-400 tracking-widest uppercase mt-0.5">
          STABLE RELEASE
        </div>
      </div>
    </aside>
  );
};
