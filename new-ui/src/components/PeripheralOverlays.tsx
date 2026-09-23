import React, { useState, useEffect } from 'react';
import { Activity, Terminal, Network, Radio } from 'lucide-react';

interface ThinBarProps {
  label: string;
  value: number;
  unit?: string;
  color?: string;
}

const ThinProgressBar: React.FC<ThinBarProps> = ({
  label,
  value,
  unit = '%',
  color = 'bg-cyan-400',
}) => (
  <div className="space-y-0.5 font-mono">
    <div className="flex justify-between items-center text-[10px]">
      <span className="text-cyan-300/80 uppercase tracking-wider">{label}</span>
      <span className="text-cyan-400 font-semibold">{value}{unit}</span>
    </div>
    <div className="w-full h-1 bg-black border border-cyan-500/30 overflow-hidden">
      <div
        className={`h-full transition-all duration-700 ${color}`}
        style={{ width: `${value}%` }}
      />
    </div>
  </div>
);

export const PeripheralOverlays: React.FC = () => {
  // Terminal pseudo-code logs
  const [logs, setLogs] = useState<string[]>([
    '[17:54:02.11] NECTAR::ATLAS mounted (1,024 dims)',
    '[17:54:03.45] AEGIS::COMM route established: 0x9f',
    '[17:54:04.88] ZERO_TRUST::CHECK passed: [0_ERR]',
    '[17:54:06.12] MATHSAGE::COPROC freq: 14.82 THz',
    '[17:54:07.95] SPECTRAL_FLUX delta: +0.002%',
    '[17:54:09.30] SATELLITE_DOWNLINK: 4.88 Gbps',
    '[17:54:11.04] FLYMEMORY node cache validated',
  ]);

  // Subsystem progress metrics
  const [metrics, setMetrics] = useState({
    synapse: 94,
    tensor: 82,
    entangle: 99,
    subspace: 96,
    neuralLoad: 46,
    shield: 91,
    positron: 77,
    bandwidth: 98,
    dampener: 86,
  });

  // T-minus counter state for celestial vectors
  const [tMinus, setTMinus] = useState(868);

  useEffect(() => {
    const logPool = [
      'ORION_GATEWAY heartbeat ack [OK]',
      'NECTAR::FLYMEMORY packed 512 nodes',
      'PHOTON_BUS packet rx: 4.88 Gbps',
      'SUBSPACE beacon ping: 12ms',
      'NEURAL_NET weight epoch #491 synced',
      'DEEP_SPACE sensor: 0 anomalies',
      'AEGIS::DOWNLINK checksum: [VALID]',
      'COSMIC_CORE alignment: nominal',
    ];

    const timer = setInterval(() => {
      const d = new Date();
      const timeStr = `${d.toTimeString().split(' ')[0]}.${Math.floor(d.getMilliseconds() / 10).toString().padStart(2, '0')}`;
      const randomLog = logPool[Math.floor(Math.random() * logPool.length)];

      setLogs((prev) => [...prev.slice(1), `[${timeStr}] ${randomLog}`]);
      setTMinus((prev) => (prev > 0 ? prev - 1 : 868));

      setMetrics((prev) => ({
        synapse: Math.min(99, Math.max(90, prev.synapse + (Math.random() > 0.5 ? 1 : -1))),
        tensor: Math.min(88, Math.max(76, prev.tensor + (Math.random() > 0.5 ? 2 : -2))),
        entangle: Math.min(100, Math.max(96, prev.entangle + (Math.random() > 0.6 ? 1 : -1))),
        subspace: Math.min(99, Math.max(92, prev.subspace + (Math.random() > 0.5 ? 1 : -1))),
        neuralLoad: Math.min(55, Math.max(38, prev.neuralLoad + (Math.random() > 0.5 ? 2 : -2))),
        shield: Math.min(96, Math.max(88, prev.shield + (Math.random() > 0.5 ? 1 : -1))),
        positron: Math.min(84, Math.max(72, prev.positron + (Math.random() > 0.5 ? 2 : -2))),
        bandwidth: Math.min(100, Math.max(95, prev.bandwidth + (Math.random() > 0.7 ? 1 : -1))),
        dampener: Math.min(92, Math.max(82, prev.dampener + (Math.random() > 0.5 ? 1 : -1))),
      }));
    }, 2500);

    return () => clearInterval(timer);
  }, []);

  const formatTimer = (secs: number) => {
    const m = Math.floor(secs / 60).toString().padStart(2, '0');
    const s = (secs % 60).toString().padStart(2, '0');
    return `00:${m}:${s}`;
  };

  return (
    <>
      {/* ============================================================ */}
      {/* LEFT SIDEBAR ('CORE TELEMETRY'): Fixed-width vertical panel  */}
      {/* ============================================================ */}
      <aside className="hidden xl:flex fixed left-5 top-18 bottom-16 w-72 flex-col justify-between bg-black/60 border border-cyan-500/40 p-3.5 z-20 pointer-events-auto corner-bracket select-none text-cyan-400 font-mono">
        {/* Panel Header */}
        <div className="flex items-center justify-between border-b border-cyan-500/40 pb-2 mb-2">
          <div className="flex items-center space-x-2">
            <Network className="w-3.5 h-3.5 text-cyan-400 animate-pulse" />
            <span className="font-['Orbitron'] font-bold text-xs text-cyan-300 tracking-wider">
              CORE TELEMETRY
            </span>
          </div>
          <span className="text-[9px] bg-black border border-cyan-500/40 px-1 text-cyan-400">
            [SYS-01]
          </span>
        </div>

        {/* TOP SECTION: NEURAL NETWORK SYNC with 98.6% readout and segmented progress bar */}
        <div className="space-y-2 mb-3 bg-black/50 border border-cyan-500/30 p-2.5">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-bold text-cyan-300 flex items-center space-x-1">
              <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-ping mr-1" />
              NEURAL NETWORK SYNC
            </span>
            <span className="text-xs font-bold text-cyan-300">98.6%</span>
          </div>

          {/* Segmented Progress Bar (18 distinct segment blocks) */}
          <div className="grid grid-cols-18 gap-0.5 h-3 w-full bg-black p-0.5 border border-cyan-500/40">
            {Array.from({ length: 18 }).map((_, idx) => {
              const isFilled = idx < 17; // 17 out of 18 is approx 94.4% ~ 98.6%
              return (
                <div
                  key={idx}
                  className={`h-full transition-colors ${
                    isFilled
                      ? 'bg-cyan-400 shadow-[0_0_3px_#00ffff]'
                      : 'bg-black border border-cyan-500/30 opacity-40'
                  }`}
                />
              );
            })}
          </div>

          <div className="flex justify-between text-[9px] text-cyan-400/80 pt-0.5">
            <span>LATENCY: 1.2ms</span>
            <span>COHERENCE: 99.4%</span>
          </div>
        </div>

        {/* MIDDLE SECTION: List of thin horizontal progress bars for subsystems */}
        <div className="space-y-2 mb-3">
          <div className="text-[9px] text-cyan-400/70 uppercase tracking-widest border-b border-cyan-500/20 pb-1">
            // SUBSYSTEM MONITOR
          </div>
          <ThinProgressBar label="Synapse Matrix" value={metrics.synapse} />
          <ThinProgressBar label="Tensor Buffer" value={metrics.tensor} />
          <ThinProgressBar label="Quantum Entanglement" value={metrics.entangle} />
          <ThinProgressBar label="Subspace Bandwidth" value={metrics.subspace} />
          <ThinProgressBar label="Neural Core Load" value={metrics.neuralLoad} color="bg-emerald-400" />
        </div>

        {/* BOTTOM SECTION: TERMINAL STREAM showing lines of timestamped pseudo-code in small text */}
        <div className="flex-1 flex flex-col min-h-0 border-t border-cyan-500/40 pt-2">
          <div className="flex items-center justify-between text-[10px] text-cyan-300 mb-1.5">
            <div className="flex items-center space-x-1.5">
              <Terminal className="w-3 h-3 text-cyan-400" />
              <span className="font-bold">TERMINAL STREAM</span>
            </div>
            <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse" />
          </div>

          <div className="flex-1 bg-black/80 border border-cyan-500/30 p-2 overflow-y-auto space-y-1 text-[9px] text-cyan-400 leading-tight">
            {logs.map((log, idx) => (
              <div key={idx} className="flex items-start space-x-1">
                <span className="text-cyan-500 shrink-0 font-bold">›</span>
                <span className="break-all">{log}</span>
              </div>
            ))}
          </div>
        </div>
      </aside>

      {/* ============================================================ */}
      {/* RIGHT SIDEBAR ('ORBITAL DYNAMICS'): Fixed-width panel       */}
      {/* ============================================================ */}
      <aside className="hidden xl:flex fixed right-5 top-18 bottom-16 w-72 flex-col justify-between bg-black/60 border border-cyan-500/40 p-3.5 z-20 pointer-events-auto corner-bracket select-none text-cyan-400 font-mono">
        {/* Panel Header */}
        <div className="flex items-center justify-between border-b border-cyan-500/40 pb-2 mb-2">
          <div className="flex items-center space-x-2">
            <Activity className="w-3.5 h-3.5 text-cyan-400 animate-pulse" />
            <span className="font-['Orbitron'] font-bold text-xs text-cyan-300 tracking-wider">
              ORBITAL DYNAMICS
            </span>
          </div>
          <span className="text-[9px] bg-black border border-cyan-500/40 px-1 text-emerald-400">
            [ACTIVE]
          </span>
        </div>

        {/* TOP SECTION: CELESTIAL VECTORS with small boxed timer readouts */}
        <div className="space-y-2 mb-3 bg-black/50 border border-cyan-500/30 p-2.5">
          <div className="text-[10px] font-bold text-cyan-300 uppercase tracking-widest border-b border-cyan-500/20 pb-1">
            CELESTIAL VECTORS
          </div>
          <div className="grid grid-cols-2 gap-1.5">
            <div className="bg-black border border-cyan-500/30 p-1.5 text-center">
              <div className="text-[8px] text-slate-400">RA (α)</div>
              <div className="text-[10px] text-cyan-300 font-bold">05h 35m 17s</div>
            </div>
            <div className="bg-black border border-cyan-500/30 p-1.5 text-center">
              <div className="text-[8px] text-slate-400">DEC (δ)</div>
              <div className="text-[10px] text-cyan-300 font-bold">-05° 23' 28"</div>
            </div>
            <div className="bg-black border border-cyan-500/30 p-1.5 text-center">
              <div className="text-[8px] text-slate-400">DISTANCE</div>
              <div className="text-[10px] text-cyan-300 font-bold">1,344 LY</div>
            </div>
            <div className="bg-black border border-cyan-500/30 p-1.5 text-center">
              <div className="text-[8px] text-slate-400">T-MINUS VECTOR</div>
              <div className="text-[10px] text-orange-400 font-bold">{formatTimer(tMinus)}</div>
            </div>
          </div>
        </div>

        {/* MIDDLE SECTION: DEFENSIVE ENVELOPE with horizontal progress bars */}
        <div className="space-y-2 mb-3">
          <div className="text-[9px] text-cyan-400/70 uppercase tracking-widest border-b border-cyan-500/20 pb-1">
            // DEFENSIVE ENVELOPE
          </div>
          <ThinProgressBar label="Radiation Shield" value={metrics.shield} />
          <ThinProgressBar label="Positron Thrusters" value={metrics.positron} />
          <ThinProgressBar label="Sub-Ether Bandwidth" value={metrics.bandwidth} />
          <ThinProgressBar label="Entropy Dampener" value={metrics.dampener} color="bg-orange-400" />
        </div>

        {/* BOTTOM SECTION: QUANTUM UPLINK table showing hex addresses and aligned status */}
        <div className="flex-1 flex flex-col min-h-0 border-t border-cyan-500/40 pt-2">
          <div className="flex items-center justify-between text-[10px] text-cyan-300 mb-1.5">
            <div className="flex items-center space-x-1.5">
              <Radio className="w-3 h-3 text-cyan-400" />
              <span className="font-bold">QUANTUM UPLINK</span>
            </div>
            <span className="text-[8px] text-cyan-400/70 font-mono">Q-AES-512</span>
          </div>

          <div className="flex-1 bg-black/80 border border-cyan-500/30 p-2 overflow-y-auto font-mono text-[9px]">
            <table className="w-full text-left">
              <thead>
                <tr className="text-slate-400 border-b border-cyan-500/20 text-[8px]">
                  <th className="pb-1 font-normal">NODE / HEX ADDR</th>
                  <th className="pb-1 text-right font-normal">STATUS</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-cyan-500/10">
                <tr>
                  <td className="py-1 text-cyan-300">0x8F92..A4C1</td>
                  <td className="py-1 text-right text-cyan-400 font-semibold">VERIFIED</td>
                </tr>
                <tr>
                  <td className="py-1 text-cyan-300">0x1C44..EE90</td>
                  <td className="py-1 text-right text-cyan-400 font-semibold">LOCKED</td>
                </tr>
                <tr>
                  <td className="py-1 text-cyan-300">0xBB09..77FA</td>
                  <td className="py-1 text-right text-cyan-400 font-semibold">VERIFIED</td>
                </tr>
                <tr>
                  <td className="py-1 text-cyan-300">0x4A11..90CD</td>
                  <td className="py-1 text-right text-orange-400 font-bold animate-pulse">SYNCING</td>
                </tr>
                <tr>
                  <td className="py-1 text-cyan-300">0x2D73..81E9</td>
                  <td className="py-1 text-right text-cyan-400 font-semibold">LOCKED</td>
                </tr>
                <tr>
                  <td className="py-1 text-cyan-300">0xF03B..9A12</td>
                  <td className="py-1 text-right text-orange-400 font-bold animate-pulse">SYNCING</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </aside>
    </>
  );
};
