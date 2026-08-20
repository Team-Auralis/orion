"use client";

import { useState } from "react";

export default function HavenApp() {
  const [message, setMessage] = useState("");
  const [status, setStatus] = useState<"IDLE" | "SENDING" | "SENT" | "ERROR">("IDLE");
  const [errorMsg, setErrorMsg] = useState("");

  const handleSOS = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!message.trim()) return;

    setStatus("SENDING");
    try {
      const payload = {
        type: "SOS",
        location: {
          latitude: 34.0522 + (Math.random() - 0.5) * 0.1,
          longitude: -118.2437 + (Math.random() - 0.5) * 0.1
        },
        message: message,
        source: "haven_web_pwa"
      };

      const tokenParams = new URLSearchParams();
      tokenParams.append("client_id", "orion-api");
      tokenParams.append("grant_type", "password");
      tokenParams.append("username", "citizen1");
      tokenParams.append("password", "citizenpass");
      
      const kcRes = await fetch("http://localhost:8080/realms/orion/protocol/openid-connect/token", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: tokenParams
      });
      const kcData = await kcRes.json();

      const res = await fetch("http://localhost:8001/v1/incidents", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${kcData.access_token}`
        },
        body: JSON.stringify(payload)
      });

      if (!res.ok) {
        throw new Error("Failed to transmit to ORION Nexus");
      }

      setStatus("SENT");
      setMessage("");
      setTimeout(() => setStatus("IDLE"), 5000);
    } catch (err: any) {
      setStatus("ERROR");
      setErrorMsg(err.message);
      setTimeout(() => setStatus("IDLE"), 5000);
    }
  };

  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-slate-950 text-white font-sans p-4">
      <div className="w-full max-w-md bg-slate-900 border border-slate-700 rounded-3xl p-8 shadow-2xl relative overflow-hidden">
        
        {/* Network Status Header */}
        <div className="flex justify-between items-center mb-10 text-xs font-bold text-slate-400">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse shadow-[0_0_8px_#22c55e]"></div>
            HAVEN UPLINK
          </div>
          <div>MOCK-GPS: LOCKED</div>
        </div>

        <h1 className="text-3xl font-black tracking-tight mb-2 text-center text-slate-100">Emergency SOS</h1>
        <p className="text-slate-400 text-sm text-center mb-8">
          Describe the situation. AI will automatically dispatch the closest responder.
        </p>

        <form onSubmit={handleSOS} className="flex flex-col gap-6">
          <textarea
            className="w-full bg-slate-800 border border-slate-600 rounded-xl p-4 text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-red-500 resize-none h-32 transition-all"
            placeholder="E.g. House is flooding, water rising fast..."
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            disabled={status !== "IDLE"}
            required
          />

          <button
            type="submit"
            disabled={status !== "IDLE" || !message.trim()}
            className={`w-full py-4 rounded-full font-black text-lg transition-all shadow-lg flex items-center justify-center gap-2 ${
              status === "IDLE" && message.trim() 
                ? "bg-red-600 hover:bg-red-500 text-white hover:shadow-[0_0_20px_#dc2626] cursor-pointer" 
                : status === "SENDING"
                ? "bg-slate-700 text-slate-400 cursor-wait"
                : status === "SENT"
                ? "bg-green-600 text-white shadow-[0_0_20px_#16a34a]"
                : status === "ERROR"
                ? "bg-red-900 text-red-400"
                : "bg-slate-800 text-slate-500 cursor-not-allowed"
            }`}
          >
            {status === "IDLE" && "SLIDE TO TRANSMIT"}
            {status === "SENDING" && "TRANSMITTING..."}
            {status === "SENT" && "SOS ACCEPTED"}
            {status === "ERROR" && "TRANSMISSION FAILED"}
          </button>
        </form>

        {status === "ERROR" && (
          <p className="text-red-400 text-xs text-center mt-4">{errorMsg}</p>
        )}

        <div className="mt-8 pt-6 border-t border-slate-800 text-center">
           <p className="text-[10px] text-slate-600 uppercase tracking-widest font-mono">
             Orion Civilian Edge Client v0.6
           </p>
        </div>
      </div>
    </main>
  );
}
