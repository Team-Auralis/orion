"""ORION-HIVE Web Dashboard & Fleet Control Server.

Provides a clean browser dashboard on http://<ip>:8080 where you and your team can:
1. View live cluster status, registered devices, CPU/RAM, and role allocations.
2. Select model tier: phone (0.7M), tiny (1.4M), 10m (13.6M), 30m (31.8M).
3. Configure dataset source:
   - Built-in ORION 63.8M curated corpus
   - Hugging Face dataset (e.g. wikitext, imdb, or custom HF repo)
   - Custom SQLite database (.db / .sqlite)
4. Trigger federated training runs directly from the browser or inspect worker connection commands.
5. REST API endpoints for workers, CLI scripts, and web UI.
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (
    str(REPO_ROOT),
    str(REPO_ROOT / "scripts"),
    str(REPO_ROOT / "scripts" / "training"),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import psutil
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

app = FastAPI(title="ORION-HIVE Cluster Coordinator & Dashboard")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global active training run state
STATE = {
    "status": "IDLE",  # IDLE, TRAINING, COMPLETED, ERROR
    "active_run_id": None,
    "current_round": 0,
    "total_rounds": 0,
    "model_size": "10m",
    "dataset": "builtin-corpus",
    "tokens_trained": 0,
    "loss": None,
    "val_loss": None,
    "registered_devices": [],
    "recent_logs": [],
    "error_message": None,
}

LOCK = threading.Lock()
ACTIVE_PROC = None


def get_lan_ips():
    ips = []
    try:
        host = socket.gethostname()
        for ip in socket.gethostbyname_ex(host)[2]:
            if not ip.startswith("127.") and not ip.startswith("169.254."):
                ips.append(ip)
    except Exception:
        pass
    if not ips:
        ips.append("127.0.0.1")
    # Prioritize physical Wi-Fi/Ethernet networks over VirtualBox/VMware host-only adapters (e.g. 192.168.56.*)
    def ip_priority(ip):
        if ip.startswith("192.168.56."):  # VirtualBox default
            return 99
        if ip.startswith("192.168.") or ip.startswith("10.") or ip.startswith("172."):
            return 1
        return 50
    ips.sort(key=ip_priority)
    return ips


PRIMARY_LAN_IP = get_lan_ips()[0] if get_lan_ips() else "127.0.0.1"


class TrainRequest(BaseModel):
    model: str = "10m"
    workers: int = 2
    network_workers: int = 1
    rounds: int = 4
    tokens: int = 40000
    hf_dataset: Optional[str] = None
    sqlite_db: Optional[str] = None
    batch: int = 4
    worker_lr: float = 0.005


@app.get("/api/status")
def api_status():
    with LOCK:
        hw = {
            "cpu_cores": psutil.cpu_count(logical=False),
            "cpu_threads": psutil.cpu_count(logical=True),
            "ram_total_gb": round(psutil.virtual_memory().total / (1024**3), 2),
            "ram_available_gb": round(psutil.virtual_memory().available / (1024**3), 2),
            "disk_free_gb": round(psutil.disk_usage(str(REPO_ROOT)).free / (1024**3), 2),
            "lan_ip": PRIMARY_LAN_IP,
            "all_ips": get_lan_ips(),
        }
        return {
            "state": STATE,
            "hardware": hw,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }


@app.get("/api/runs")
def api_runs():
    ledger = REPO_ROOT / "logs" / "training_runs.jsonl"
    runs = []
    if ledger.exists():
        with open(ledger, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    if "hive" in row.get("experiment_name", ""):
                        runs.append(row)
                except Exception:
                    pass
    return {"runs": runs[-10:]}


def _run_training_thread(req: TrainRequest):
    global ACTIVE_PROC
    with LOCK:
        STATE["status"] = "TRAINING"
        STATE["model_size"] = req.model
        STATE["total_rounds"] = req.rounds
        STATE["current_round"] = 0
        STATE["dataset"] = req.hf_dataset or req.sqlite_db or "builtin-corpus"
        STATE["error_message"] = None
        STATE["recent_logs"] = [f"Starting federated run with model={req.model}, rounds={req.rounds}..."]

    cmd = [
        sys.executable,
        "-m",
        "hive.run",
        "--model",
        req.model,
        "--workers",
        str(req.workers),
        "--network-workers",
        str(req.network_workers),
        "--listen-host",
        "0.0.0.0",
        "--listen-port",
        "8765",
        "--rounds",
        str(req.rounds),
        "--tokens",
        str(req.tokens),
        "--batch",
        str(req.batch),
        "--worker-lr",
        str(req.worker_lr),
        "--scope",
        "web-dashboard-run",
    ]
    if req.hf_dataset:
        cmd.extend(["--hf-dataset", req.hf_dataset])
    if req.sqlite_db:
        cmd.extend(["--sqlite-db", req.sqlite_db])

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=str(REPO_ROOT),
            env=env,
        )
        ACTIVE_PROC = proc
        for line in proc.stdout:
            line_str = line.strip()
            if not line_str:
                continue
            with LOCK:
                STATE["recent_logs"].append(line_str)
                if len(STATE["recent_logs"]) > 100:
                    STATE["recent_logs"].pop(0)
                if "[ROUND " in line_str:
                    try:
                        r_part = line_str.split("[ROUND ")[1].split("]")[0]
                        STATE["current_round"] = int(r_part)
                    except Exception:
                        pass
                if "loss=" in line_str and "val_loss=" in line_str:
                    try:
                        parts = line_str.split()
                        for p in parts:
                            if p.startswith("loss="):
                                STATE["loss"] = float(p.split("=")[1])
                            elif p.startswith("val_loss="):
                                STATE["val_loss"] = float(p.split("=")[1])
                            elif p.startswith("tokens="):
                                STATE["tokens_trained"] = int(p.split("=")[1].replace(",", ""))
                    except Exception:
                        pass

        proc.wait()
        with LOCK:
            if proc.returncode == 0:
                STATE["status"] = "COMPLETED"
                STATE["recent_logs"].append("Federated training completed successfully!")
            else:
                STATE["status"] = "ERROR"
                STATE["error_message"] = f"Process exited with code {proc.returncode}"
    except Exception as e:
        with LOCK:
            STATE["status"] = "ERROR"
            STATE["error_message"] = str(e)
    finally:
        ACTIVE_PROC = None


@app.post("/api/start")
def api_start(req: TrainRequest):
    global ACTIVE_PROC
    with LOCK:
        if STATE["status"] == "TRAINING":
            raise HTTPException(status_code=400, detail="Training run is already active")
    t = threading.Thread(target=_run_training_thread, args=(req,), daemon=True)
    t.start()
    return {"message": "Federated training initiated", "params": req.dict()}


@app.post("/api/stop")
def api_stop():
    global ACTIVE_PROC
    if ACTIVE_PROC:
        try:
            ACTIVE_PROC.terminate()
        except Exception:
            pass
    with LOCK:
        STATE["status"] = "IDLE"
        STATE["recent_logs"].append("[USER] Stopped active training.")
    return {"message": "Training stopped"}


HTML_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ORION-HIVE — Multi-Device AI Training Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #0b0f19;
            --surface: #111827;
            --border: #1f2937;
            --accent: #38bdf8;
            --accent-glow: rgba(56, 189, 248, 0.15);
            --green: #34d399;
            --yellow: #fbbf24;
            --red: #f87171;
            --text: #f3f4f6;
            --text-dim: #9ca3af;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: 'Inter', sans-serif;
            background: var(--bg);
            color: var(--text);
            padding: 24px;
            min-height: 100vh;
        }
        .container { max-width: 1200px; margin: 0 auto; }
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-bottom: 20px;
            border-bottom: 1px solid var(--border);
            margin-bottom: 24px;
        }
        .logo-group h1 {
            font-size: 24px;
            font-weight: 700;
            letter-spacing: -0.5px;
            color: var(--text);
        }
        .logo-group h1 span { color: var(--accent); }
        .logo-group p { font-size: 13px; color: var(--text-dim); margin-top: 4px; }
        .status-pill {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 6px 14px;
            border-radius: 9999px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 12px;
            font-weight: 600;
            background: var(--surface);
            border: 1px solid var(--border);
        }
        .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--green); }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 20px; margin-bottom: 24px; }
        .card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
        }
        .card h2 {
            font-size: 14px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-dim);
            margin-bottom: 16px;
            display: flex;
            justify-content: space-between;
        }
        .stat-val { font-size: 28px; font-weight: 700; color: var(--text); font-family: 'JetBrains Mono', monospace; }
        .stat-sub { font-size: 12px; color: var(--text-dim); margin-top: 4px; }
        .form-group { margin-bottom: 14px; }
        label { display: block; font-size: 12px; font-weight: 600; color: var(--text-dim); margin-bottom: 6px; }
        select, input {
            width: 100%;
            padding: 10px 12px;
            background: #0f172a;
            border: 1px solid var(--border);
            border-radius: 8px;
            color: var(--text);
            font-family: inherit;
            font-size: 13px;
        }
        select:focus, input:focus { outline: none; border-color: var(--accent); }
        .btn-group { display: flex; gap: 10px; margin-top: 16px; }
        button {
            flex: 1;
            padding: 11px 16px;
            border-radius: 8px;
            font-weight: 600;
            font-size: 13px;
            cursor: pointer;
            border: none;
            transition: all 0.15s ease;
        }
        .btn-primary { background: var(--accent); color: #0b0f19; }
        .btn-primary:hover { opacity: 0.9; }
        .btn-danger { background: #ef4444; color: white; }
        .btn-danger:hover { opacity: 0.9; }
        .code-box {
            background: #060911;
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 14px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 12px;
            color: #38bdf8;
            overflow-x: auto;
            position: relative;
            margin-top: 8px;
            user-select: all;
        }
        .console-logs {
            background: #060911;
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 14px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 12px;
            color: #d1d5db;
            height: 240px;
            overflow-y: auto;
            white-space: pre-wrap;
            line-height: 1.5;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo-group">
                <h1>ORION <span>HIVE</span></h1>
                <p>Distributed Edge AI Training — Phone to Multi-Laptop Fleet</p>
            </div>
            <div class="status-pill" id="status-badge">
                <span class="dot" id="status-dot"></span>
                <span id="status-text">COORDINATOR ONLINE</span>
            </div>
        </header>

        <div class="grid">
            <!-- Hardware & Node Profile -->
            <div class="card">
                <h2>Cluster Host <span id="lan-ip-tag" style="color:var(--accent);">IP: LOADING</span></h2>
                <div class="stat-val" id="cpu-stat">-- Cores</div>
                <div class="stat-sub" id="ram-stat">RAM: -- GB free | Disk: -- GB</div>
                <div style="margin-top: 16px;">
                    <label>Join Token / Remote Connection Command</label>
                    <div class="code-box" id="join-cmd">python join_hive.py --host <span class="ip-placeholder">...</span> --role worker</div>
                </div>
            </div>

            <!-- Run Progress -->
            <div class="card">
                <h2>Training Progress <span id="run-status" style="color:var(--green);">IDLE</span></h2>
                <div class="stat-val" id="loss-stat">--</div>
                <div class="stat-sub" id="progress-sub">Round: 0 / 0 | Tokens Trained: 0</div>
                <div style="margin-top: 16px;">
                    <label>Mobile Join Command (Android Termux / Phone)</label>
                    <div class="code-box" id="phone-cmd">python join_hive.py --host <span class="ip-placeholder">...</span> --model phone --threads 2</div>
                </div>
            </div>
        </div>

        <div class="grid">
            <!-- Start Run Controls -->
            <div class="card">
                <h2>Launch Federated Session</h2>
                <div class="form-group">
                    <label>Model Architecture Tier (Optimized for Device Type)</label>
                    <select id="model-select">
                        <option value="phone">phone (0.7M params) — Ultra-lightweight for Android / Mobile</option>
                        <option value="tiny">tiny (1.4M params) — High-speed test & mechanics</option>
                        <option value="10m" selected>10m (13.6M params) — Standard for Laptops & Desktops</option>
                        <option value="30m">30m (31.8M params) — Higher Capacity Heterogeneous Nodes</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Dataset Source</label>
                    <select id="dataset-source" onchange="toggleDatasetInput()">
                        <option value="builtin">Built-in ORION 63.8M Curated Corpus</option>
                        <option value="hf">Hugging Face Dataset (e.g. wikitext, imdb, openwebtext)</option>
                        <option value="sqlite">Custom SQLite Database File (.db / .sqlite)</option>
                    </select>
                </div>
                <div class="form-group" id="hf-group" style="display:none;">
                    <label>Hugging Face Dataset Name / Repo</label>
                    <input type="text" id="hf-input" placeholder="e.g. wikitext or imdb">
                </div>
                <div class="form-group" id="sqlite-group" style="display:none;">
                    <label>SQLite Database Path</label>
                    <input type="text" id="sqlite-input" placeholder="e.g. data/my_database.db">
                </div>
                <div style="display: flex; gap: 12px;">
                    <div class="form-group" style="flex:1;">
                        <label>Aggregation Rounds</label>
                        <input type="number" id="rounds-input" value="4">
                    </div>
                    <div class="form-group" style="flex:1;">
                        <label>Tokens Per Round</label>
                        <input type="number" id="tokens-input" value="40000">
                    </div>
                </div>
                <div style="display: flex; gap: 12px;">
                    <div class="form-group" style="flex:1;">
                        <label>Total Workers</label>
                        <input type="number" id="workers-input" value="2">
                    </div>
                    <div class="form-group" style="flex:1;">
                        <label>Remote Network Workers</label>
                        <input type="number" id="net-workers-input" value="1">
                    </div>
                </div>
                <div class="btn-group">
                    <button class="btn-primary" onclick="startTraining()">START TRAINING</button>
                    <button class="btn-danger" onclick="stopTraining()">STOP</button>
                </div>
            </div>

            <!-- Real-time Cluster Activity Logs -->
            <div class="card">
                <h2>Real-time Fleet Console</h2>
                <div class="console-logs" id="console-logs">Waiting for training session...</div>
            </div>
        </div>
    </div>

    <script>
        function toggleDatasetInput() {
            const val = document.getElementById('dataset-source').value;
            document.getElementById('hf-group').style.display = val === 'hf' ? 'block' : 'none';
            document.getElementById('sqlite-group').style.display = val === 'sqlite' ? 'block' : 'none';
        }

        async function fetchStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                const hw = data.hardware;
                const state = data.state;

                document.getElementById('lan-ip-tag').innerText = 'IP: ' + hw.lan_ip;
                document.getElementById('cpu-stat').innerText = hw.cpu_cores + ' Cores (' + hw.cpu_threads + ' Threads)';
                document.getElementById('ram-stat').innerText = 'RAM: ' + hw.ram_available_gb + ' GB free / ' + hw.ram_total_gb + ' GB | Disk: ' + hw.disk_free_gb + ' GB free';

                document.querySelectorAll('.ip-placeholder').forEach(el => el.innerText = hw.lan_ip);
                document.getElementById('join-cmd').innerText = 'python join_hive.py --host ' + hw.lan_ip + ' --role worker';
                document.getElementById('phone-cmd').innerText = 'python join_hive.py --host ' + hw.lan_ip + ' --model phone --threads 2';

                document.getElementById('run-status').innerText = state.status;
                if (state.loss !== null) {
                    document.getElementById('loss-stat').innerText = 'Loss: ' + state.loss.toFixed(4);
                } else {
                    document.getElementById('loss-stat').innerText = state.status;
                }
                document.getElementById('progress-sub').innerText = 'Round: ' + state.current_round + ' / ' + state.total_rounds + ' | Tokens: ' + (state.tokens_trained || 0).toLocaleString();

                if (state.recent_logs && state.recent_logs.length > 0) {
                    const box = document.getElementById('console-logs');
                    box.innerText = state.recent_logs.join('\\n');
                    box.scrollTop = box.scrollHeight;
                }
            } catch (e) {
                console.error(e);
            }
        }

        async function startTraining() {
            const model = document.getElementById('model-select').value;
            const dsType = document.getElementById('dataset-source').value;
            const rounds = parseInt(document.getElementById('rounds-input').value);
            const tokens = parseInt(document.getElementById('tokens-input').value);
            const workers = parseInt(document.getElementById('workers-input').value);
            const netWorkers = parseInt(document.getElementById('net-workers-input').value);

            let hf_dataset = null;
            let sqlite_db = null;
            if (dsType === 'hf') hf_dataset = document.getElementById('hf-input').value.trim();
            if (dsType === 'sqlite') sqlite_db = document.getElementById('sqlite-input').value.trim();

            const payload = {
                model: model,
                workers: workers,
                network_workers: netWorkers,
                rounds: rounds,
                tokens: tokens,
                hf_dataset: hf_dataset,
                sqlite_db: sqlite_db
            };

            await fetch('/api/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            fetchStatus();
        }

        async function stopTraining() {
            await fetch('/api/stop', { method: 'POST' });
            fetchStatus();
        }

        setInterval(fetchStatus, 2000);
        fetchStatus();
    </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(content=HTML_CONTENT)


def main():
    import uvicorn

    parser = argparse.ArgumentParser(description="ORION-HIVE Web Dashboard Server")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host interface to bind")
    parser.add_argument("--port", type=int, default=7860, help="HTTP port (default: 7860)")
    args = parser.parse_args()

    print(f"\n========================================================")
    print(f"  ORION-HIVE WEB DASHBOARD & FLEET COORDINATOR")
    print(f"========================================================")
    print(f"  Local Browser Dashboard : http://localhost:{args.port}")
    print(f"  LAN Browser Dashboard   : http://{PRIMARY_LAN_IP}:{args.port}")
    print(f"  Remote Worker Connect   : {PRIMARY_LAN_IP}:8765")
    print(f"========================================================\n")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
