import React, { useState } from 'react';
import { Sparkles, CornerDownLeft } from 'lucide-react';
import { sfx } from '../utils/audio';

interface CommandPedestalInputProps {
  onExecuteQuery: (query: string) => void;
  inputRef?: React.RefObject<HTMLInputElement | null>;
}

export const CommandPedestalInput: React.FC<CommandPedestalInputProps> = ({
  onExecuteQuery,
  inputRef,
}) => {
  const [query, setQuery] = useState('');
  const [isFocused, setIsFocused] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    sfx.chime();
    onExecuteQuery(query.trim());
    setQuery('');
  };

  const handleQuickPrompt = (prompt: string) => {
    sfx.click();
    onExecuteQuery(prompt);
  };

  return (
    <div className="w-full max-w-2xl mx-auto px-4 z-30 select-none">
      <form onSubmit={handleSubmit} className="flex flex-col items-center">
        {/* Pill-shaped glass search input container */}
        <div
          className={`
            w-full flex items-center justify-between px-5 py-2.5 sm:py-3 rounded-full
            bg-black/60 backdrop-blur-md border transition-all duration-300
            ${
              isFocused
                ? 'border-cyan-300 shadow-[0_0_25px_rgba(0,255,255,0.6)] ring-1 ring-cyan-300'
                : 'border-cyan-500/40 hover:border-cyan-300/80 shadow-[0_0_15px_rgba(0,0,0,0.8)]'
            }
          `}
        >
          {/* Left: Curved Return Arrow ↵ */}
          <div className="flex items-center text-cyan-400 mr-2 shrink-0">
            <span className="text-base font-mono">↵</span>
          </div>

          {/* Search Input Field */}
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => setIsFocused(true)}
            onBlur={() => setIsFocused(false)}
            placeholder="Ask Orion anything..."
            className="w-full bg-transparent text-slate-100 placeholder-slate-400/60 text-sm md:text-base font-['Rajdhani'] font-medium tracking-wide focus:outline-none focus:ring-0 selection:bg-cyan-500 selection:text-black"
          />

          {/* Right: Sparkle Submit Button */}
          <div className="flex items-center space-x-2 shrink-0 ml-3">
            {query.trim() && (
              <button
                type="submit"
                className="hidden sm:flex items-center space-x-1 px-2.5 py-0.5 rounded-full bg-cyan-950 border border-cyan-400/50 text-[10px] font-mono text-cyan-300 hover:bg-cyan-500 hover:text-black transition-all cursor-pointer"
              >
                <span>SEND</span>
                <CornerDownLeft className="w-2.5 h-2.5" />
              </button>
            )}

            <button
              type="submit"
              title="Execute with Orion AI"
              className="p-1 text-cyan-400 hover:text-cyan-200 hover:scale-110 transition-transform cursor-pointer"
            >
              <Sparkles className="w-5 h-5 drop-shadow-[0_0_6px_#00ffff]" />
            </button>
          </div>
        </div>

        {/* Quick Suggestion Prompts */}
        <div className="flex items-center flex-wrap justify-center gap-1.5 mt-2 text-[10px] font-mono">
          {['Sector 9 Star Chart', 'Cosmic Core Frequency', 'Purge Volatile Cache', 'Sync Neural Net'].map(
            (item) => (
              <button
                key={item}
                type="button"
                onClick={() => handleQuickPrompt(item)}
                className="px-2 py-0.5 rounded-full bg-black/40 border border-cyan-500/25 text-cyan-400/80 hover:text-cyan-200 hover:border-cyan-400 transition-colors cursor-pointer"
              >
                ✦ {item}
              </button>
            )
          )}
        </div>
      </form>
    </div>
  );
};
