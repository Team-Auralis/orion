import React, { useState } from 'react';
import { ChevronRight } from 'lucide-react';
import { sfx } from '../utils/audio';

interface OrionBottomCommandBarProps {
  onSearch: (query: string) => void;
  inputRef?: React.RefObject<HTMLInputElement | null>;
  onPortalClick?: () => void;
}

export const OrionBottomCommandBar: React.FC<OrionBottomCommandBarProps> = ({
  onSearch,
  inputRef,
  onPortalClick,
}) => {
  const [query, setQuery] = useState('');
  const [isFocused, setIsFocused] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    sfx.chime();
    onSearch(query.trim());
    setQuery('');
  };

  return (
    <div
      role="search"
      aria-label="Pedestal Command Input"
      className="w-full max-w-lg mx-auto z-40 select-none"
    >
      <form
        onSubmit={handleSubmit}
        className={`
          w-full h-11 sm:h-12 flex items-center justify-between rounded-full px-2
          bg-slate-950/85 backdrop-blur-xl border transition-all duration-300
          shadow-[0_10px_30px_rgba(0,0,0,0.9)]
          ${
            isFocused
              ? 'border-cyan-400 shadow-[0_0_25px_rgba(0,255,255,0.6)] ring-1 ring-cyan-400/50'
              : 'border-cyan-500/40 hover:border-cyan-400/70'
          }
        `}
      >
        {/* Left: Glowing Blue Cosmic Portal Orb */}
        <button
          type="button"
          onClick={() => {
            sfx.click();
            if (onPortalClick) onPortalClick();
          }}
          aria-label="Open Cosmic Portal Diagnostics"
          title="Cosmic Portal Link"
          className="w-8 h-8 rounded-full overflow-hidden border border-cyan-400/60 shadow-[0_0_10px_rgba(0,255,255,0.5)] cursor-pointer hover:scale-110 focus-visible:ring-2 focus-visible:ring-cyan-300 transition-transform shrink-0"
        >
          <img
            src="/orion_assets/portal_orb.png"
            alt="Portal"
            className="w-full h-full object-cover"
          />
        </button>

        {/* Input Field with exact placeholder */}
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => setIsFocused(true)}
          onBlur={() => setIsFocused(false)}
          placeholder="Ask Orion anything..."
          aria-label="Ask Orion anything"
          className="w-full bg-transparent text-slate-100 placeholder-slate-400/60 text-xs md:text-sm font-['Rajdhani'] font-medium tracking-wide focus:outline-none px-3 selection:bg-cyan-500 selection:text-black"
        />

        {/* Right: Miniature Spiral Galaxy Oval Pill & Arrow */}
        <button
          type="submit"
          aria-label="Execute Orion Prompt"
          title="Execute Inquiry"
          className="flex items-center space-x-1 pr-1.5 cursor-pointer group shrink-0 focus-visible:ring-2 focus-visible:ring-cyan-300 rounded-full"
        >
          <div className="w-14 h-6 rounded-full overflow-hidden border border-cyan-500/50 group-hover:border-cyan-300 transition-colors shadow-inner">
            <img
              src="/orion_assets/galaxy_pill.png"
              alt="Galaxy"
              className="w-full h-full object-cover"
            />
          </div>
          <ChevronRight className="w-4 h-4 text-cyan-400 group-hover:text-cyan-200 group-hover:translate-x-0.5 transition-all" />
        </button>
      </form>
    </div>
  );
};
