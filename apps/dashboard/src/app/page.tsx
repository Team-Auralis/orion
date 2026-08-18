"use client";

import { useEffect, useState } from "react";

export default function Home() {
  const [incidents, setIncidents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    // Poll the incidents every 2 seconds
    const fetchIncidents = async () => {
      try {
        // Ponytail: Simple fetch to our local API. In prod, use react-query and proper auth tokens.
        const res = await fetch("http://localhost:8001/v1/incidents", {
            // This represents an operator logged in.
            // FastAPI currently mocks auth, but requires hitting the policy check.
            headers: { "Authorization": "Bearer MOCK_TOKEN" }
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
        <div className="overflow-x-auto border border-slate-700 rounded-lg bg-slate-800/50 shadow-2xl">
          <table className="w-full text-left text-sm text-slate-300">
            <thead className="bg-slate-800 text-xs uppercase text-slate-400 border-b border-slate-700">
              <tr>
                <th className="px-6 py-4">INCIDENT ID</th>
                <th className="px-6 py-4">TYPE</th>
                <th className="px-6 py-4">STATUS</th>
                <th className="px-6 py-4">MESSAGE</th>
                <th className="px-6 py-4">TIMESTAMP</th>
              </tr>
            </thead>
            <tbody>
              {incidents.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-6 py-8 text-center text-slate-500 italic">
                    NO ACTIVE INCIDENTS. SYSTEM NOMINAL.
                  </td>
                </tr>
              ) : (
                incidents.map((inc: any) => (
                  <tr key={inc.incident_id} className="border-b border-slate-700 hover:bg-slate-700/50 transition-colors">
                    <td className="px-6 py-4 font-medium text-blue-300">{inc.incident_id}</td>
                    <td className="px-6 py-4">
                        <span className="bg-red-900/50 text-red-400 border border-red-500/50 px-2 py-1 rounded text-xs font-bold">
                            {inc.type}
                        </span>
                    </td>
                    <td className="px-6 py-4 text-amber-400">{inc.status}</td>
                    <td className="px-6 py-4 truncate max-w-xs">{inc.message}</td>
                    <td className="px-6 py-4 text-slate-400">{new Date(inc.created_at).toLocaleString()}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
