import React, { useState, useEffect, useRef } from 'react';
import { OrionTopBar } from './components/OrionTopBar';
import { OrionSidebar } from './components/OrionSidebar';
import { OrionNeuralSyncCard } from './components/OrionNeuralSyncCard';
import { OrionCenterCore } from './components/OrionCenterCore';
import { OrionRightPanels } from './components/OrionRightPanels';
import { OrionActionDock } from './components/OrionActionDock';
import { OrionBottomCommandBar } from './components/OrionBottomCommandBar';
import { ActionModal } from './components/ActionModal';
import {
  Volume2,
  VolumeX,
  Maximize2,
  Minimize2,
  X,
  Terminal,
} from 'lucide-react';
import { sfx } from './utils/audio';

const TABS = ['HOME', 'CHAT', 'RESEARCH', 'DEV STUDIO', 'MEMORY', 'SYSTEM', 'GALAXY MAP', 'TOOLS'];
const ACTION_KEYS: Record<string, string> = {
  F1: 'debug',
  F2: 'clipboard',
  F3: 'memory',
  F4: 'dev',
  F5: 'voice',
  F6: 'purge',
};

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<string>('HOME');
  const [activeModalId, setActiveModalId] = useState<string | null>(null);
  const [soundEnabled, setSoundEnabled] = useState(true);
  const [isFullscreen, setIsFullscreen] = useState(false);

  // Live clock and date
  const [currentTime, setCurrentTime] = useState('16:49');
  const [currentDate, setCurrentDate] = useState('MON, 22 SEP 2026');

  // Live hardware telemetry
  const [cpu, setCpu] = useState(12);
  const [gpu, setGpu] = useState(38);
  const [mem, setMem] = useState(56);
  const [net, setNet] = useState(21);

  // Live core percentages for Neural Network Sync
  const [corePercentages, setCorePercentages] = useState([100, 99, 98, 100, 97, 100]);

  // AI Response Floating Panel
  const [aiResponse, setAiResponse] = useState<{ query: string; answer: string; timestamp: string } | null>(null);

  const bottomInputRef = useRef<HTMLInputElement>(null);

  // Global Keyboard Shortcuts (F1-F6, 1-8, Ctrl+Space, Escape)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ignore if user is currently typing in an input
      const isInput = document.activeElement instanceof HTMLInputElement || document.activeElement instanceof HTMLTextAreaElement;

      // Escape key to close modal or AI response
      if (e.key === 'Escape') {
        if (activeModalId) {
          sfx.click();
          setActiveModalId(null);
        } else if (aiResponse) {
          sfx.click();
          setAiResponse(null);
        }
        return;
      }

      // Ctrl+Space to focus bottom command bar
      if (e.ctrlKey && e.code === 'Space') {
        e.preventDefault();
        bottomInputRef.current?.focus();
        sfx.click();
        return;
      }

      if (isInput) return;

      // F1 through F6 for Action Cards
      if (ACTION_KEYS[e.key]) {
        e.preventDefault();
        const actionId = ACTION_KEYS[e.key];
        if (actionId === 'purge') {
          sfx.alert();
        } else {
          sfx.chime();
        }
        setActiveModalId(actionId);
        return;
      }

      // 1 through 8 for Left Sidebar Tabs
      const num = parseInt(e.key, 10);
      if (num >= 1 && num <= 8) {
        e.preventDefault();
        const tab = TABS[num - 1];
        sfx.click();
        setActiveTab(tab);
        if (tab !== 'HOME') {
          setActiveModalId(tab.toLowerCase());
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [activeModalId, aiResponse]);

  // Live clock and dynamic hardware telemetry
  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      const hours = now.getHours().toString().padStart(2, '0');
      const mins = now.getMinutes().toString().padStart(2, '0');
      setCurrentTime(`${hours}:${mins}`);

      const days = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'];
      const months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
      setCurrentDate(`${days[now.getDay()]}, ${now.getDate()} ${months[now.getMonth()]} ${now.getFullYear()}`);
    };

    updateTime();
    const clockInterval = setInterval(updateTime, 10000);

    const telemetryInterval = setInterval(() => {
      setCpu(+(12 + (Math.random() * 4 - 2)).toFixed(0));
      setGpu(+(38 + (Math.random() * 6 - 3)).toFixed(0));
      setMem(+(56 + (Math.random() * 2 - 1)).toFixed(0));
      setNet(+(21 + (Math.random() * 4 - 2)).toFixed(0));

      setCorePercentages([
        100,
        Math.random() > 0.5 ? 99 : 100,
        Math.random() > 0.5 ? 98 : 99,
        100,
        Math.random() > 0.5 ? 97 : 98,
        100,
      ]);
    }, 3000);

    return () => {
      clearInterval(clockInterval);
      clearInterval(telemetryInterval);
    };
  }, []);

  const handleToggleSound = () => {
    const next = !soundEnabled;
    setSoundEnabled(next);
    sfx.enabled = next;
  };

  const handleToggleFullscreen = () => {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen().catch(() => {});
      setIsFullscreen(true);
    } else {
      document.exitFullscreen().catch(() => {});
      setIsFullscreen(false);
    }
  };

  const handleTabSelect = (tab: string) => {
    setActiveTab(tab);
    if (tab === 'CHAT' || tab === 'RESEARCH' || tab === 'DEV STUDIO' || tab === 'MEMORY' || tab === 'SYSTEM' || tab === 'GALAXY MAP' || tab === 'TOOLS') {
      setActiveModalId(tab.toLowerCase());
    }
  };

  const handleExecuteQuery = (queryText: string) => {
    if (!queryText.trim()) return;
    sfx.chime();
    const timestamp = new Date().toTimeString().split(' ')[0];
    const qLower = queryText.toLowerCase();

    let answer = `Cosmic Engine Core processed query: "${queryText}". Neural network synchronized at 98.7% across Sector 09. Orion v31.0 runtime nominal.`;

    if (qLower.includes('ngc') || qLower.includes('1300') || qLower.includes('galaxy') || qLower.includes('star')) {
      answer = `[STAR CHART] NGC 1300 barred spiral galaxy selected. Distance: 320 million light-years. Constellation: Eridanus.`;
    } else if (qLower.includes('debug') || qLower.includes('kernel') || qLower.includes('system')) {
      answer = `[DEBUG ENGINE] All 6 quantum cores online (100% resonance). CPU: ${cpu}% | GPU: ${gpu}% | Memory: ${mem}% | Network: ${net}%.`;
    } else if (qLower.includes('purge') || qLower.includes('clean') || qLower.includes('cache')) {
      answer = `[SYSTEM PURGE] Volatile cache ready for decontamination flush. Launching safety protocol in Action Dock.`;
    } else if (qLower.includes('jarvis') || qLower.includes('ultron') || qLower.includes('origin')) {
      answer = `"Intelligence Beyond Origins." Orion is the sovereign intelligence platform engineered for deep space autonomous stewardship.`;
    }

    setAiResponse({ query: queryText, answer, timestamp });
  };

  return (
    <div className="relative w-screen h-screen bg-[#020617] text-slate-100 overflow-hidden flex flex-col justify-between select-none font-sans">
      {/* Keyboard Accessibility Skip Link */}
      <a href="#main-stage" className="skip-link">
        Skip to Main Cockpit Dashboard
      </a>

      {/* ============================================================ */}
      {/* 1. PHOTOREALISTIC SPACESHIP COCKPIT & EARTH BACKDROP         */}
      {/* ============================================================ */}
      <div className="fixed inset-0 w-full h-full pointer-events-none -z-10 overflow-hidden" aria-hidden="true">
        <img
          src="/orion_assets/exact_orion_v31.png"
          alt="Observation Deck"
          className="w-full h-full object-cover filter brightness-95"
        />
        {/* Ambient radial contrast vignette */}
        <div className="absolute inset-0 bg-gradient-to-t from-[#020617]/80 via-transparent to-[#020617]/50" />
      </div>

      {/* ============================================================ */}
      {/* 2. TOP BAR                                                   */}
      {/* ============================================================ */}
      <OrionTopBar
        currentTime={currentTime}
        currentDate={currentDate}
        onSearch={handleExecuteQuery}
        onVoiceClick={() => setActiveModalId('voice')}
        onScanClick={() => setActiveModalId('star chart')}
      />

      {/* ============================================================ */}
      {/* 3. MAIN COCKPIT DASHBOARD VIEWPORT                           */}
      {/* ============================================================ */}
      <div
        id="main-stage"
        role="main"
        aria-label="Orion Tactical Cockpit"
        className="relative flex-1 flex items-stretch justify-between px-6 pb-2 min-h-0 z-20"
      >
        {/* Left Column: Floating Sidebar */}
        <div className="flex items-start shrink-0 mr-4">
          <OrionSidebar
            activeTab={activeTab}
            onTabSelect={handleTabSelect}
          />
        </div>

        {/* Center Main Stage */}
        <div className="relative flex-1 flex flex-col items-center justify-between min-w-0">
          {/* Floating Left HUD Card (Neural Network Sync) */}
          <div className="absolute left-2 lg:left-6 top-6 z-30">
            <OrionNeuralSyncCard
              corePercentages={corePercentages}
              onClick={() => setActiveModalId('sync')}
            />
          </div>

          {/* Centerpiece: Armillary Sphere & Core */}
          <div className="relative flex-1 flex items-center justify-center w-full min-h-0 my-auto">
            <OrionCenterCore
              onInspectCore={() => setActiveModalId('core')}
            />
          </div>

          {/* AI Query Floating Speech Response Panel */}
          {aiResponse && (
            <div
              role="dialog"
              aria-modal="true"
              aria-label="Orion Reasoning Engine Response"
              className="absolute left-1/2 -translate-x-1/2 top-4 w-full max-w-xl p-3.5 bg-black/90 border border-cyan-400 rounded-2xl shadow-[0_0_35px_rgba(0,255,255,0.5)] z-50 backdrop-blur-md animate-in fade-in slide-in-from-top-2"
            >
              <div className="flex items-start justify-between">
                <div className="flex items-start space-x-2.5">
                  <Terminal className="w-4 h-4 text-cyan-400 shrink-0 mt-0.5" />
                  <div>
                    <div className="flex items-center space-x-2 text-[10px] font-mono text-cyan-400/80">
                      <span className="font-bold text-cyan-300">ORION REASONING ENGINE</span>
                      <span>•</span>
                      <span>{aiResponse.timestamp}</span>
                      <span>•</span>
                      <span className="text-slate-400 truncate">"{aiResponse.query}"</span>
                    </div>
                    <div className="text-xs font-mono text-cyan-200 mt-1 leading-relaxed">
                      {aiResponse.answer}
                    </div>
                  </div>
                </div>
                <button
                  onClick={() => setAiResponse(null)}
                  aria-label="Dismiss response"
                  className="text-cyan-500/70 hover:text-cyan-300 p-0.5 cursor-pointer focus-visible:ring-2 focus-visible:ring-cyan-300 rounded"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>
          )}

          {/* Action Dock (6 Glass Cards on the Pedestal) */}
          <div className="w-full z-30 mb-2">
            <OrionActionDock
              onCardClick={(id) => setActiveModalId(id)}
              activeCardId={activeModalId}
            />
          </div>

          {/* Bottom Command Input Bar */}
          <div className="w-full z-30 mb-2">
            <OrionBottomCommandBar
              inputRef={bottomInputRef}
              onSearch={handleExecuteQuery}
              onPortalClick={() => setActiveModalId('core')}
            />
          </div>
        </div>

        {/* Right Column: Floating HUD Panels */}
        <div className="flex items-start shrink-0 ml-4">
          <OrionRightPanels
            cpu={cpu}
            gpu={gpu}
            mem={mem}
            net={net}
            onOpenStarChart={() => setActiveModalId('star chart')}
            onOpenMissionLog={() => setActiveModalId('mission log')}
            onOpenStation={() => setActiveModalId('station')}
          />
        </div>
      </div>

      {/* ============================================================ */}
      {/* 4. UTILITY CONTROLS (Sound & Fullscreen in bottom corner)     */}
      {/* ============================================================ */}
      <div className="fixed left-6 bottom-3 flex items-center space-x-2 z-40 text-xs">
        <button
          onClick={handleToggleSound}
          aria-label={soundEnabled ? 'Mute Interface Sound' : 'Enable Interface Sound'}
          title={soundEnabled ? 'Mute Interface Sound' : 'Enable Sound'}
          className="p-1 rounded bg-black/60 border border-cyan-500/30 text-cyan-400 hover:text-cyan-200 focus-visible:ring-2 focus-visible:ring-cyan-300 transition-colors cursor-pointer"
        >
          {soundEnabled ? <Volume2 className="w-3.5 h-3.5" /> : <VolumeX className="w-3.5 h-3.5 text-slate-500" />}
        </button>
        <button
          onClick={handleToggleFullscreen}
          aria-label={isFullscreen ? 'Exit Fullscreen' : 'Enter Fullscreen'}
          title={isFullscreen ? 'Exit Fullscreen' : 'Enter Fullscreen'}
          className="p-1 rounded bg-black/60 border border-cyan-500/30 text-cyan-400 hover:text-cyan-200 focus-visible:ring-2 focus-visible:ring-cyan-300 transition-colors cursor-pointer"
        >
          {isFullscreen ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}
        </button>
      </div>

      {/* Interactive Subsystem Modal */}
      <ActionModal
        actionId={activeModalId}
        onClose={() => setActiveModalId(null)}
      />
    </div>
  );
};

export default App;
