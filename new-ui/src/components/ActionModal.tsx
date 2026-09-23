import React, { useState, useEffect } from 'react';
import {
  X,
  AlertTriangle,
  CheckCircle2,
  RefreshCw,
  Terminal,
  Clipboard,
  Cpu,
  Code,
  Mic,
  Play,
} from 'lucide-react';
import { sfx } from '../utils/audio';

interface ActionModalProps {
  actionId: string | null;
  onClose: () => void;
}

export const ActionModal: React.FC<ActionModalProps> = ({ actionId, onClose }) => {
  const [purgeCountdown, setPurgeCountdown] = useState<number | null>(null);
  const [isPurging, setIsPurging] = useState(false);
  const [purgeCompleted, setPurgeCompleted] = useState(false);
  const [copiedSnippet, setCopiedSnippet] = useState<string | null>(null);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    if (purgeCountdown !== null && purgeCountdown > 0) {
      timer = setTimeout(() => {
        setPurgeCountdown(purgeCountdown - 1);
        sfx.click();
      }, 1000);
    } else if (purgeCountdown === 0) {
      setIsPurging(true);
      sfx.alert();
      setTimeout(() => {
        setIsPurging(false);
        setPurgeCompleted(true);
        setPurgeCountdown(null);
      }, 2000);
    }
    return () => clearTimeout(timer);
  }, [purgeCountdown]);

  if (!actionId) return null;

  const handleStartPurge = () => {
    sfx.alert();
    setPurgeCountdown(3);
    setPurgeCompleted(false);
  };

  const handleCancelPurge = () => {
    sfx.click();
    setPurgeCountdown(null);
  };

  const handleCopySnippet = (text: string) => {
    sfx.click();
    setCopiedSnippet(text);
    setTimeout(() => setCopiedSnippet(null), 1500);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-in fade-in duration-200">
      {/* Modal Dialog Container */}
      <div className="relative w-full max-w-2xl bg-black/90 rounded-2xl border-2 border-cyan-400 shadow-[0_0_50px_rgba(0,255,255,0.4)] overflow-hidden">
        {/* Holographic Header Bar */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-cyan-500/40 bg-cyan-950/30">
          <div className="flex items-center space-x-3">
            <span className="w-2 h-2 rounded-full bg-cyan-400 animate-ping" />
            <h2 className="font-['Orbitron'] font-bold text-base md:text-lg text-slate-100 tracking-wider">
              {actionId === 'debug' && 'SYSTEM DEBUGGER // KERNEL V4'}
              {actionId === 'clipboard' && 'CLIPBOARD COPILOT // CONTEXT BUFFER'}
              {actionId === 'memory' && 'NEURAL MEMORY RECALL // NECTAR'}
              {actionId === 'dev' && 'DEV WORKSPACE // SUB-ETHER CLI'}
              {actionId === 'voice' && 'VOICE MEMO // SUBSPACE TRANSCEIVER'}
              {actionId === 'purge' && 'CRITICAL DIRECTIVE // SYSTEM PURGE'}
              {actionId === 'core' && 'COSMIC ENGINE CORE // QUANTUM DIAGNOSTICS'}
            </h2>
          </div>
          <button
            onClick={() => {
              sfx.click();
              onClose();
            }}
            className="p-1 rounded-full text-slate-400 hover:text-cyan-300 hover:bg-cyan-950/60 transition-colors cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Body Content */}
        <div className="p-6 max-h-[75vh] overflow-y-auto font-mono text-xs text-cyan-300">
          {/* 1. DEBUG SCREEN */}
          {actionId === 'debug' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between text-cyan-300 border-b border-cyan-500/30 pb-2">
                <div className="flex items-center space-x-2">
                  <Terminal className="w-4 h-4 text-cyan-400" />
                  <span>RUNTIME: ORION-KERNEL (X86_64-POSIX)</span>
                </div>
                <span className="text-emerald-400 font-bold">ALL SYSTEMS NOMINAL</span>
              </div>
              <div className="bg-black/90 rounded-xl p-4 border border-cyan-500/40 space-y-2 text-cyan-300/90 font-mono">
                <div className="text-slate-400">// STACK TRACE & MEMORY ALLOCATION:</div>
                <div className="text-cyan-400">0x00007FF728A1: allocate_tensor_pool(size=4096MB) -&gt; SUCCESS</div>
                <div className="text-cyan-400">0x00007FF728C9: initialize_subspace_transceiver(freq=14.8THz) -&gt; LOCKED</div>
                <div className="text-cyan-400">0x00007FF7291F: nectar_flymemory_atlas_mount(nodes=1024) -&gt; VERIFIED</div>
                <div className="text-emerald-400">0x00007FF7298B: zero_trust_policy_daemon() -&gt; ENFORCING (0 VIOLATIONS)</div>
                <div className="text-cyan-400">0x00007FF72A02: telemetry_stream_daemon() -&gt; 4.88 Gbps STEADY</div>
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div className="p-3 rounded-lg bg-black border border-cyan-500/30 text-center">
                  <div className="text-[10px] text-slate-400">THREAD POOL</div>
                  <div className="text-cyan-300 font-bold text-sm">64 CORES</div>
                </div>
                <div className="p-3 rounded-lg bg-black border border-cyan-500/30 text-center">
                  <div className="text-[10px] text-slate-400">PAGE FAULTS</div>
                  <div className="text-emerald-400 font-bold text-sm">0 / SEC</div>
                </div>
                <div className="p-3 rounded-lg bg-black border border-cyan-500/30 text-center">
                  <div className="text-[10px] text-slate-400">ENTROPY DRIFT</div>
                  <div className="text-cyan-300 font-bold text-sm">+0.00012%</div>
                </div>
              </div>
            </div>
          )}

          {/* 2. CLIPBOARD COPILOT */}
          {actionId === 'clipboard' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between text-cyan-300 border-b border-cyan-500/30 pb-2">
                <div className="flex items-center space-x-2">
                  <Clipboard className="w-4 h-4 text-cyan-400" />
                  <span>ACTIVE CLIPBOARD SNIPPETS</span>
                </div>
                <span className="text-cyan-400">3 ITEMS SYNCED</span>
              </div>
              <div className="space-y-2.5">
                {[
                  {
                    title: 'ORION_GATEWAY_TOKEN',
                    content: 'bearer eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCJ9...',
                    time: '2 mins ago',
                  },
                  {
                    title: 'SECTOR_9_ORBITAL_VECTORS',
                    content: '{"ra": "05h 35m", "dec": "-05° 23\'", "dist_ly": 1344}',
                    time: '12 mins ago',
                  },
                  {
                    title: 'COSMIC_CORE_FREQUENCY',
                    content: 'freq_thz: 14.82, resonance: 0.998, entropy: 0.002',
                    time: '24 mins ago',
                  },
                ].map((item, idx) => (
                  <div
                    key={idx}
                    className="p-3 bg-black/80 border border-cyan-500/30 rounded-xl flex items-center justify-between hover:border-cyan-400 transition-colors"
                  >
                    <div>
                      <div className="font-bold text-cyan-200">{item.title}</div>
                      <div className="text-slate-400 text-[11px] font-mono truncate max-w-md mt-0.5">
                        {item.content}
                      </div>
                      <div className="text-[9px] text-cyan-500/70 mt-1">{item.time}</div>
                    </div>
                    <button
                      onClick={() => handleCopySnippet(item.title)}
                      className="px-3 py-1 rounded bg-cyan-950 border border-cyan-500/50 text-cyan-300 hover:bg-cyan-500 hover:text-black transition-all cursor-pointer"
                    >
                      {copiedSnippet === item.title ? 'COPIED!' : 'COPY'}
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 3. RECALL MEMORY */}
          {actionId === 'memory' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between text-cyan-300 border-b border-cyan-500/30 pb-2">
                <div className="flex items-center space-x-2">
                  <Cpu className="w-4 h-4 text-cyan-400" />
                  <span>SYNAPTIC VECTOR EMBEDDINGS (NECTAR)</span>
                </div>
                <span className="text-emerald-400 font-bold">1,024 NODES READY</span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {[
                  { title: 'ORION PART 01', desc: 'Core Vision & Planetary Intelligence Network', dims: '1,536 dims' },
                  { title: 'ORION PART 02', desc: 'Zero-Trust Distributed Sovereign Architecture', dims: '1,536 dims' },
                  { title: 'AEGIS SATELLITE', desc: 'Subspace Comm Layer & Orbital Constellations', dims: '768 dims' },
                  { title: 'DIGITAL TWIN', desc: 'Mirror Twin Physics Engine & Telemetry Sim', dims: '2,048 dims' },
                ].map((item, idx) => (
                  <div key={idx} className="p-3 rounded-xl bg-black/80 border border-cyan-500/30 hover:border-cyan-300 transition-all">
                    <div className="flex justify-between items-center text-cyan-300 font-bold">
                      <span>{item.title}</span>
                      <span className="text-[10px] text-cyan-400/70">{item.dims}</span>
                    </div>
                    <div className="text-slate-300 text-[11px] mt-1">{item.desc}</div>
                    <div className="mt-2 text-emerald-400 text-[10px] flex items-center space-x-1">
                      <CheckCircle2 className="w-3 h-3" />
                      <span>COGNITIVE EMBEDDING READY</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 4. DEV WORKSPACE */}
          {actionId === 'dev' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between text-cyan-300 border-b border-cyan-500/30 pb-2">
                <div className="flex items-center space-x-2">
                  <Code className="w-4 h-4 text-cyan-400" />
                  <span>ORION CODE ENGINE // REPL</span>
                </div>
                <span className="text-cyan-400 font-mono">NODE 24.16 | REACT 19</span>
              </div>
              <div className="p-4 bg-black/90 rounded-xl border border-cyan-500/40 font-mono text-[11px] space-y-2">
                <div className="text-slate-400">// Execute quantum telemetry query:</div>
                <div className="text-cyan-300">
                  <span className="text-purple-400">const</span> core = <span className="text-purple-400">await</span> Orion.<span className="text-blue-400">connect</span>({'{'}
                  <br />&nbsp;&nbsp;node: <span className="text-emerald-300">'ORION-09-LMC-NODE'</span>,
                  <br />&nbsp;&nbsp;frequency: <span className="text-amber-300">14.82</span>,
                  <br />&nbsp;&nbsp;zeroTrust: <span className="text-purple-400">true</span>
                  <br />{'}'});
                </div>
                <div className="text-slate-500">// Returns: [Promise&lt;TelemetryStream&gt;]</div>
              </div>
              <div className="flex justify-end space-x-2">
                <button
                  onClick={() => sfx.chime()}
                  className="px-4 py-1.5 rounded-full bg-cyan-950 border border-cyan-400/60 text-cyan-300 hover:bg-cyan-500 hover:text-black flex items-center space-x-1.5 cursor-pointer transition-colors"
                >
                  <Play className="w-3.5 h-3.5" />
                  <span>RUN REPL QUERY</span>
                </button>
              </div>
            </div>
          )}

          {/* 5. VOICE MEMO */}
          {actionId === 'voice' && (
            <div className="space-y-4 text-center">
              <div className="flex flex-col items-center justify-center p-4 bg-cyan-950/30 border border-cyan-500/40 rounded-xl">
                <Mic className="w-10 h-10 text-cyan-400 animate-pulse mb-2" />
                <h3 className="font-['Orbitron'] text-sm font-bold text-cyan-300 uppercase tracking-widest">
                  VOICE MEMO & TRANSCRIPTION
                </h3>
                <p className="text-slate-300 text-xs mt-1 max-w-md">
                  Active audio uplink listening for keyword: <span className="text-cyan-300 font-bold">'HEY ORION'</span>
                </p>
                {/* Audio spectrogram bars */}
                <div className="flex items-center justify-center space-x-1 h-8 mt-3">
                  {[20, 60, 90, 40, 80, 100, 75, 45, 95, 30, 85, 50, 70, 40, 60].map((h, i) => (
                    <div
                      key={i}
                      className="w-1.5 bg-cyan-400 rounded-full animate-pulse"
                      style={{ height: `${h}%`, animationDelay: `${i * 80}ms` }}
                    />
                  ))}
                </div>
              </div>
              <div className="p-3 bg-black/80 rounded-xl border border-cyan-500/30 text-left font-mono text-[11px] text-cyan-400">
                <div className="text-slate-400 mb-1">// RECENT TRANSCRIPTS:</div>
                <div>[16:49:12] "Orion, synchronize deep space star chart to LMC coordinates."</div>
                <div>[16:48:30] "Calibrate neural network sync rate to 98.7%."</div>
              </div>
            </div>
          )}

          {/* 6. SYSTEM PURGE */}
          {actionId === 'purge' && (
            <div className="space-y-4 text-center">
              <div className="flex flex-col items-center justify-center p-4 bg-orange-950/30 border border-orange-500/50 rounded-xl">
                <AlertTriangle className="w-12 h-12 text-orange-400 animate-bounce mb-2" />
                <h3 className="font-['Orbitron'] text-base font-bold text-orange-300 uppercase tracking-widest">
                  DECONTAMINATION & VOLATILE CACHE PURGE
                </h3>
                <p className="text-slate-300 text-xs mt-1 max-w-md">
                  This directive flushes all temporary memory buffers, re-indexes the quantum key matrix, and resets neural cache registers to baseline state.
                </p>
              </div>

              {purgeCountdown !== null && (
                <div className="p-4 bg-black/80 rounded-xl border border-orange-500/60">
                  <div className="text-xs text-orange-400 mb-1">PURGE INITIATION IN:</div>
                  <div className="text-4xl font-bold font-['Orbitron'] text-orange-400 animate-pulse">
                    0{purgeCountdown}
                  </div>
                  <button
                    onClick={handleCancelPurge}
                    className="mt-3 px-4 py-1.5 rounded-full bg-slate-800 text-slate-200 hover:bg-slate-700 border border-slate-600 transition-all cursor-pointer"
                  >
                    ABORT SEQUENCE
                  </button>
                </div>
              )}

              {isPurging && (
                <div className="p-4 bg-black/80 rounded-xl border border-cyan-400 text-cyan-300 flex items-center justify-center space-x-2">
                  <RefreshCw className="w-5 h-5 animate-spin text-cyan-400" />
                  <span>FLUSHING QUANTUM CACHE REGISTERS...</span>
                </div>
              )}

              {purgeCompleted && (
                <div className="p-4 bg-emerald-950/40 rounded-xl border border-emerald-500/60 text-emerald-300 flex items-center justify-center space-x-2">
                  <CheckCircle2 className="w-5 h-5 text-emerald-400" />
                  <span>CACHE REGISTERS PURGED & RE-ALIGNED</span>
                </div>
              )}

              {purgeCountdown === null && !isPurging && (
                <div className="flex justify-center space-x-3 pt-2">
                  <button
                    onClick={handleStartPurge}
                    className="px-6 py-2.5 rounded-full bg-gradient-to-r from-orange-600 to-amber-600 hover:from-orange-500 hover:to-amber-500 text-white font-bold font-['Orbitron'] tracking-wider shadow-[0_0_20px_rgba(249,115,22,0.5)] transition-all cursor-pointer"
                  >
                    AUTHORIZE SYSTEM PURGE
                  </button>
                </div>
              )}
            </div>
          )}

          {/* 7. COSMIC ENGINE CORE */}
          {actionId === 'core' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between text-cyan-300 border-b border-cyan-500/30 pb-2">
                <span>COSMIC ENGINE CORE // QUANTUM ARMS</span>
                <span className="text-emerald-400 font-bold">RESONANCE: 99.8%</span>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="p-3 bg-black/80 border border-cyan-500/30 rounded-xl">
                  <div className="text-[10px] text-slate-400">FREQUENCY</div>
                  <div className="text-base font-bold text-cyan-300">14.82 THz</div>
                </div>
                <div className="p-3 bg-black/80 border border-cyan-500/30 rounded-xl">
                  <div className="text-[10px] text-slate-400">ENTROPY DRIFT</div>
                  <div className="text-base font-bold text-emerald-400">+0.002%</div>
                </div>
                <div className="p-3 bg-black/80 border border-cyan-500/30 rounded-xl">
                  <div className="text-[10px] text-slate-400">STAR CHART</div>
                  <div className="text-base font-bold text-cyan-300">ORION-LMC ACTIVE</div>
                </div>
                <div className="p-3 bg-black/80 border border-cyan-500/30 rounded-xl">
                  <div className="text-[10px] text-slate-400">SUBSPACE LINK</div>
                  <div className="text-base font-bold text-cyan-300">4.88 Gbps</div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end px-6 py-3 border-t border-cyan-500/40 bg-black/60">
          <button
            onClick={() => {
              sfx.click();
              onClose();
            }}
            className="px-5 py-1.5 rounded-full bg-cyan-950 border border-cyan-400/60 text-cyan-300 hover:bg-cyan-500 hover:text-black text-xs font-['Orbitron'] tracking-wider transition-all cursor-pointer"
          >
            DISMISS
          </button>
        </div>
      </div>
    </div>
  );
};
