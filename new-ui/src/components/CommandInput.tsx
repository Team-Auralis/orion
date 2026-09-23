import React, { useState } from 'react';
import { Sparkles, CornerDownLeft } from 'lucide-react';
import { sfx } from '../utils/audio';

interface CommandInputProps {
  onExecuteCommand: (query: string) => void;
}

export const CommandInput: React.FC<CommandInputProps> = ({ onExecuteCommand }) => {
  const [query, setQuery] = useState('');
  const [isFocused, setIsFocused] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    sfx.chime();
    onExecuteCommand(query.trim());
    setQuery('');
  };

  const handleQuickInquiry = (text: string) => {
    sfx.click();
    onExecuteCommand(text);
  };

  const quickInquiries = [
    'System Diagnostics',
    'Sector 9 Anomaly',
    'Quantum Flux Rate',
    'Purge Buffer Cache',
    'Neural Net Sync',
  ];

  return (
    <div className="w-full max-w-3xl mx-auto px-4 mt-4 z-30 select-none">
      <form onSubmit={handleSubmit} className="flex flex-col items-center">
        {/* Simple thin-bordered input field */}
        <div
          className={`
            w-full flex items-center justify-between px-4 py-2 sm:py-2.5
            bg-black/60 border transition-all duration-200
            corner-bracket
            ${
              isFocused
                ? 'border-cyan-400 shadow-[0_0_15px_rgba(0,255,255,0.5)] ring-0'
                : 'border-cyan-500/40 hover:border-cyan-400/80'
            }
          `}
        >
          {/* Input field with placeholder '> Ask Orion anything...' */}
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => setIsFocused(true)}
            onBlur={() => setIsFocused(false)}
            placeholder="> Ask Orion anything..."
            className="w-full bg-transparent text-cyan-300 placeholder-cyan-500/50 text-xs sm:text-sm font-mono tracking-wider focus:outline-none focus:ring-0 selection:bg-cyan-500 selection:text-black"
          />

          {/* Right Action Icons */}
          <div className="flex items-center space-x-2 shrink-0 ml-2">
            {query.trim() && (
              <button
                type="submit"
                className="flex items-center space-x-1 px-2 py-0.5 bg-black border border-cyan-500/40 text-[9px] font-mono text-cyan-300 hover:bg-cyan-950 transition-colors cursor-pointer"
              >
                <span>SEND</span>
                <CornerDownLeft className="w-2.5 h-2.5" />
              </button>
            )}

            <button
              type="submit"
              aria-label="Submit query"
              className="p-1 text-cyan-400 hover:text-cyan-200 transition-colors cursor-pointer"
            >
              <Sparkles className="w-4 h-4 text-cyan-400" />
            </button>
          </div>
        </div>

        {/* Row of very small 'QUICK INQUIRY' text links separated by bullet points */}
        <div className="flex items-center flex-wrap justify-center gap-1.5 sm:gap-2 mt-2 text-[10px] font-mono text-cyan-400/80">
          <span className="text-cyan-300 font-bold uppercase tracking-wider">
            QUICK INQUIRY:
          </span>
          {quickInquiries.map((item, idx) => (
            <React.Fragment key={item}>
              {idx > 0 && <span className="text-cyan-500/50">•</span>}
              <button
                type="button"
                onClick={() => handleQuickInquiry(item)}
                className="text-cyan-400 hover:text-cyan-200 hover:underline transition-colors cursor-pointer"
              >
                {item}
              </button>
            </React.Fragment>
          ))}
        </div>
      </form>
    </div>
  );
};
