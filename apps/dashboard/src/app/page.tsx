"use client";

import { useEffect, useState } from "react";

function TacticalMap({ incidents }: { incidents: any[] }) {
  const [hoveredInc, setHoveredInc] = useState<any | null>(null);

  return (
    <div className="w-full bg-slate-900 border border-slate-700 rounded-xl p-4 mb-8 shadow-[0_0_40px_rgba(0,0,0,0.8)] relative overflow-hidden" style={{ height: '400px' }}>
      {/* Grid Background */}
      <div className="absolute inset-0 bg-[linear-gradient(rgba(30,41,59,0.3)_1px,transparent_1px),linear-gradient(90deg,rgba(30,41,59,0.3)_1px,transparent_1px)] bg-[size:40px_40px]"></div>
      
      {/* Target Crosshairs in Center */}
      <div className="absolute inset-0 flex items-center justify-center opacity-30 pointer-events-none">
        <div className="w-[1px] h-full bg-blue-500/50"></div>
        <div className="w-full h-[1px] bg-blue-500/50 absolute"></div>
        <div className="w-[100px] h-[100px] border border-blue-500/50 rounded-full absolute"></div>
        <div className="w-[200px] h-[200px] border border-blue-500/30 rounded-full absolute"></div>
        <div className="w-[300px] h-[300px] border border-blue-500/10 rounded-full absolute"></div>
      </div>

      <div className="absolute top-4 left-4 z-10 flex flex-col gap-1">
        <div className="text-sm font-bold text-blue-400 tracking-[0.2em] drop-shadow-[0_0_5px_rgba(96,165,250,0.8)]">MIRROR // TACTICAL GRID</div>
        <div className="text-[10px] text-slate-500 font-mono uppercase">System: Online | Sync: Real-time</div>
      </div>

      <div className="absolute top-4 right-4 z-10 flex flex-col gap-2 bg-slate-900/80 p-3 rounded border border-slate-700 text-xs text-slate-400 backdrop-blur-sm">
        <div className="flex items-center gap-2"><div className="w-2 h-2 rounded-full bg-red-500 shadow-[0_0_8px_#ef4444]"></div> CRITICAL THREAT</div>
        <div className="flex items-center gap-2"><div className="w-2 h-2 rounded-full bg-amber-400 shadow-[0_0_8px_#fbbf24]"></div> GENERAL ALERT</div>
      </div>
      
      {/* Radar sweeping animation */}
      <div className="absolute top-1/2 left-1/2 w-[800px] h-[800px] -ml-[400px] -mt-[400px] rounded-full flex items-center justify-center pointer-events-none">
          <div className="w-[400px] h-[400px] rounded-full relative animate-[spin_3s_linear_infinite]">
             <div className="w-1/2 h-full absolute right-0 bg-[conic-gradient(from_0deg,transparent_0deg,rgba(59,130,246,0.3)_360deg)] rounded-full origin-left"></div>
          </div>
      </div>

      {/* Plot incidents */}
      <div className="relative w-full h-full">
        {incidents.map((inc) => {
           // Simple mercator projection mock. Map bounds approx: lat 33 to 35, lon -119 to -117
           const x = ((inc.longitude - -118.0) * 50) + 50; // percentage
           const y = ((inc.latitude - 34.0) * -50) + 50; // percentage, inverted y
           
           const clampX = Math.max(2, Math.min(98, x));
           const clampY = Math.max(2, Math.min(98, y));
           
           const isCritical = inc.ai_severity === 'CRITICAL';
           const colorClass = isCritical ? 'bg-red-500' : 'bg-amber-400';
           const shadowClass = isCritical ? 'shadow-[0_0_15px_#ef4444]' : 'shadow-[0_0_10px_#fbbf24]';
           const textClass = isCritical ? 'text-red-400' : 'text-amber-400';
           
           return (
             <div 
                key={inc.incident_id} 
                className="absolute group cursor-crosshair z-20"
                style={{ left: `${clampX}%`, top: `${clampY}%` }}
                onMouseEnter={() => setHoveredInc(inc)}
                onMouseLeave={() => setHoveredInc(null)}
             >
                {/* Blip */}
                <div className={`absolute w-3 h-3 -ml-1.5 -mt-1.5 rounded-full ${colorClass} ${shadowClass} transition-transform group-hover:scale-150`}></div>
                
                {/* Pulse ring for critical */}
                {isCritical && (
                  <div className="absolute w-8 h-8 -ml-4 -mt-4 rounded-full border-2 border-red-500/50 animate-ping pointer-events-none"></div>
                )}
                
                {/* Always-on small label */}
                <div className="absolute top-2 left-2 bg-slate-900/90 border border-slate-700 px-1.5 py-0.5 text-[8px] rounded opacity-70 group-hover:opacity-0 transition-opacity whitespace-nowrap pointer-events-none">
                  <span className={textClass}>{inc.incident_id.split('-')[1]}</span>
                </div>
             </div>
           );
        })}
      </div>

      {/* Hover Tooltip Details */}
      {hoveredInc && (
        <div className="absolute bottom-4 left-4 z-30 bg-slate-900 border border-slate-600 p-4 rounded-lg shadow-2xl max-w-xs backdrop-blur-md animate-in fade-in slide-in-from-bottom-2 duration-200">
          <div className="text-xs text-slate-400 font-bold mb-1">TARGET LOCK: {hoveredInc.incident_id}</div>
          <div className="text-sm text-white mb-2 font-medium">{hoveredInc.message}</div>
          <div className="flex flex-wrap gap-2 text-[10px] uppercase font-bold">
            <span className="bg-slate-800 text-slate-300 px-2 py-1 rounded border border-slate-700">{hoveredInc.type}</span>
            <span className={`px-2 py-1 rounded border ${hoveredInc.ai_severity === 'CRITICAL' ? 'bg-red-900/50 text-red-400 border-red-500/50' : 'bg-amber-900/50 text-amber-400 border-amber-500/50'}`}>
              {hoveredInc.ai_severity || 'PENDING'}
            </span>
          </div>
          {hoveredInc.ai_tags && (
             <div className="mt-2 text-[9px] text-blue-400 flex flex-wrap gap-1">
               {hoveredInc.ai_tags.split(',').map((tag: string) => (
                 <span key={tag}>#{tag.trim()}</span>
               ))}
             </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function Home() {
  const [incidents, setIncidents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    // Poll the incidents every 2 seconds
    const fetchIncidents = async () => {
      try {
        // 1. Get real Keycloak Token (Dev only, production would use NextAuth)
        const tokenParams = new URLSearchParams();
        tokenParams.append("client_id", "orion-api");
        tokenParams.append("grant_type", "password");
        tokenParams.append("username", "operator1");
        tokenParams.append("password", "operatorpass");
        
        const kcRes = await fetch("http://localhost:8080/realms/orion/protocol/openid-connect/token", {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: tokenParams
        });
        const kcData = await kcRes.json();
        const token = kcData.access_token;

        // 2. Fetch incidents with real token
        const res = await fetch("http://localhost:8001/v1/incidents", {
          headers: { "Authorization": `Bearer ${token}` }
        });
        
        if (!res.ok) {
            throw new Error(`HTTP error! status: ${res.status}`);
        }
        
        const data = await res.json();
        setIncidents(data);
        setError("");
      } catch (e: any) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    };

    fetchIncidents();
    const interval = setInterval(fetchIncidents, 2000);
    return () => clearInterval(interval);
  }, []);

  return (
    <main className="flex min-h-screen flex-col p-8 bg-slate-900 text-white font-mono">
      <h1 className="text-3xl font-bold text-blue-400 mb-8 tracking-wider border-b border-blue-900 pb-4">
        ORION // OPERATOR DASHBOARD
      </h1>

      {loading ? (
        <p className="text-slate-400 animate-pulse">Establishing uplink...</p>
      ) : error ? (
        <div className="bg-red-900/30 border border-red-500 p-4 rounded text-red-400">
          <p className="font-bold">CONNECTION FAILED</p>
          <p className="text-sm">{error}</p>
        </div>
      ) : (
        <>
          <TacticalMap incidents={incidents} />
          
          <div className="overflow-x-auto border border-slate-700 rounded-lg bg-slate-800/50 shadow-2xl">
            <table className="w-full text-left text-sm text-slate-300">
              <thead className="bg-slate-800 text-xs uppercase text-slate-400 border-b border-slate-700">
                <tr>
                  <th className="px-6 py-4">INCIDENT ID</th>
                  <th className="px-6 py-4">TYPE</th>
                  <th className="px-6 py-4">AI SEVERITY</th>
                  <th className="px-6 py-4">STATUS</th>
                  <th className="px-6 py-4">AI TAGS</th>
                  <th className="px-6 py-4">MESSAGE</th>
                  <th className="px-6 py-4">TIMESTAMP</th>
                </tr>
              </thead>
              <tbody>
                {incidents.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-6 py-8 text-center text-slate-500 italic">
                      NO ACTIVE INCIDENTS. SYSTEM NOMINAL.
                    </td>
                  </tr>
                ) : (
                  incidents.map((inc: any) => (
                    <tr key={inc.incident_id} className={`border-b border-slate-700 hover:bg-slate-700/50 transition-colors ${inc.ai_severity === 'CRITICAL' ? 'bg-red-950/20' : ''}`}>
                      <td className="px-6 py-4 font-medium text-blue-300">{inc.incident_id}</td>
                      <td className="px-6 py-4">
                          <span className="bg-slate-900 text-slate-300 border border-slate-500/50 px-2 py-1 rounded text-xs font-bold">
                              {inc.type}
                          </span>
                      </td>
                      <td className="px-6 py-4">
                          {inc.ai_severity ? (
                            <span className={`px-2 py-1 rounded text-xs font-bold ${inc.ai_severity === 'CRITICAL' ? 'bg-red-900/80 text-red-100 border border-red-500 animate-pulse' : inc.ai_severity === 'HIGH' ? 'bg-orange-900/50 text-orange-400 border border-orange-500/50' : 'bg-green-900/50 text-green-400 border border-green-500/50'}`}>
                                {inc.ai_severity}
                            </span>
                          ) : (
                            <span className="text-slate-600 text-xs italic">Pending</span>
                          )}
                      </td>
                      <td className="px-6 py-4 text-amber-400">{inc.status}</td>
                      <td className="px-6 py-4">
                          <div className="flex flex-wrap gap-1">
                            {inc.ai_tags ? inc.ai_tags.split(',').map((tag: string) => (
                              <span key={tag} className="bg-blue-900/30 text-blue-300 border border-blue-500/30 px-1.5 py-0.5 rounded text-[10px] font-bold">
                                {tag.trim()}
                              </span>
                            )) : (
                              <span className="text-slate-600 text-xs italic">-</span>
                            )}
                          </div>
                      </td>
                      <td className="px-6 py-4 truncate max-w-xs">{inc.message}</td>
                      <td className="px-6 py-4 text-slate-400">{new Date(inc.created_at).toLocaleString()}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </main>
  );
}
