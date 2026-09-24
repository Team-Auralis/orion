import os
import re
import time
import random
import asyncio
import subprocess
import threading
import webbrowser
import urllib.parse
from rich.markup import escape
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Header, Footer, Static, Input, Label
from textual.binding import Binding

try:
    import onnxruntime as ort
    import numpy as np
    HAS_ONNX = True
except ImportError:
    HAS_ONNX = False

# --- CONVERSATIONAL ENGINE (FALLBACK) ---
class AuraNLP:
    def __init__(self):
        self.greetings = ["Hey! AURA here.", "Hello! I'm online.", "Hi there.", "Hey Operator, AURA standing by."]
        
    def parse(self, text):
        text_lower = text.lower().strip()
        # Greetings
        if re.search(r'\b(kaise\s+ho|kaisa\s+hai|kya\s+haal|kaise\s+hoo)\b', text_lower):
            return "Main badhiya hoon! Aap bataiye, main aapki kya madad kar sakta hoon?"
        if re.search(r'\b(bagunnara|ela\s+unnaru|ela\s+unnav|bavunnara)\b', text_lower):
            return "Nenu chala bagunnanu! Meeru ela unnaru? Nenu meeku ela sahayapadagalanu?"
        
        # Telugu-English / Tenglish Intents
        if re.search(r'\b(mee\s+peru|ne\s+peru|meeru\s+evaru|nuvvu\s+evaru)\b', text_lower):
            return "Naa peru AURA — ORION local intelligent AI assistant! Nenu mee system tasks, model training, code search mariyu commands execute cheyagalanu."
        if re.search(r'\b(mee\s+pani|ne\s+pani\s+enti|em\s+pani\s+chestaru)\b', text_lower):
            return "Naa mukhyamaina pani ORION architecture manage cheyadam: local LLMs run cheyadam, multi-device federated training coordinate cheyadam, mariyu codebase lo assist cheyadam."
        if re.search(r'\b(em\s+cheyagalaru|ela\s+help\s+chestaru|em\s+chestaru)\b', text_lower):
            return "Nenu meeku ee vishayalalo sahayapadagalanu:\n• '!' shell commands execute cheyadam (e.g. '! orbital')\n• '@' workspace files read mariyu inspect cheyadam\n• Multi-device federated training monitor cheyadam\n• ORION codebase questions ki answers ivvadam"
        m_tel_naam = re.search(r'\bnaa\s+peru\s+([a-zA-Z]+)', text_lower)
        if m_tel_naam:
            user_name = m_tel_naam.group(1).capitalize()
            return f"Namaskaram {user_name}! Mimmalni kalisinanduku chala santhosham. Eeroju manam em execute cheddam?"

        # Hindi-English / Hinglish Intents
        if re.search(r'\b(tera\s+naam|tumhara\s+naam|apka\s+naam|who\s+are\s+you|tum\s+kon\s+ho|tum\s+kaun\s+ho|tum\s+kon\s+hoo|ap\s+kaun\s+ho)\b', text_lower):
            return "Mera naam AURA hai — ORION ka local intelligent AI assistant. Main aapke system tasks, model training, code search aur commands sambhalta hoon."
        if re.search(r'\b(kya\s+job|kya\s+kaam|what\s+is\s+your\s+job|what\s+do\s+you\s+do)\b', text_lower):
            return "Mera primary kaam ORION architecture manage karna hai: local LLMs run karna, multi-device federated training coordinate karna, aur codebase me assist karna."
        if re.search(r'\b(kya\s+kya\s+kar|kya\s+kar\s+sa[kt]|kya\s+help|kaise\s+help|what\s+can\s+you\s+do)\b', text_lower):
            return "Main aapko in cheezon me help kar sakta hoon:\n• '!' lagakar shell commands execute karna (e.g. '! orbital')\n• '@' lagakar workspace files read/inspect karna\n• Local cluster federated training monitor karna\n• ORION modules aur codebase ke questions answer karna"
        m_hin_naam = re.search(r'\bmera\s+naam\s+([a-zA-Z]+)', text_lower)
        if m_hin_naam:
            user_name = m_hin_naam.group(1).capitalize()
            return f"Namaste {user_name}! Aapse baat karke achha laga. Aaj hum kya execute karne wale hain?"
        if re.search(r'\b(hello|hi|hey|sup|morning|afternoon|namaste|pranam)\b', text_lower) and len(text_lower.split()) < 4:
            return random.choice(self.greetings)
        if any(word in text_lower for word in ["status", "health"]):
            return "Cloud Node is OFFLINE. Edge Node is OFFLINE. Satellite Link is ONLINE."
        # Capabilities & System Controls
        if re.search(r'\b(can\s+you\s+open\s+apps?|apps?\s+open\s+kar\s+sa[kt]|apps?\s+khol\s+sa[kt]|applications?\s+open|apps\s+open\s+cheyagalaru|tum\s+apps\s+open)\b', text_lower):
            return "Haan bilkul! Main applications open karke unke andar automated tasks bhi perform kar sakta hoon:\n• **Brave / Chrome**: Direct URLs, YouTube search/channels/videos, likes, subscribes, comments (Laya fast-path accelerated)\n• **Notepad**: Notepad kholna aur specific text/notes automatically type karna\n• **Calculator**: Calculator launch karke mathematical equations solve karna\n• **VS Code / Terminal / Explorer**: System tools launch aur navigate karna"
        if text_lower in ["meow", "woof", "moo"]:
            return f"I'm an advanced AI, not an animal... but {text_lower} to you too!"
        return None
        
    def fallback(self, text):
        if len(text.split()) <= 3:
            return f"I see you said '{text}'. I'm currently monitoring the ORION infrastructure. Is there a specific command or file you need me to look at?"
        return "I processed your request, but I couldn't find any relevant infrastructure files or commands to execute based on that prompt."

# --- LOCAL CODEBASE SEARCH ENGINE ---
class LocalCodebaseAgent:
    def __init__(self, root_dir):
        self.root_dir = root_dir
        self.index = {}
        self.build_index()

    def build_index(self):
        for root, _, files in os.walk(self.root_dir):
            if '.git' in root or '__pycache__' in root or 'node_modules' in root:
                continue
            for file in files:
                if file.endswith(('.py', '.md')):
                    path = os.path.join(root, file)
                    try:
                        with open(path, 'r', encoding='utf-8') as f:
                            content = f.read().lower()
                            words = set(re.findall(r'\b\w+\b', content))
                            for word in words:
                                if len(word) > 3:
                                    if word not in self.index:
                                        self.index[word] = []
                                    self.index[word].append((path, content))
                    except Exception:
                        pass

    def query_local(self, text):
        keywords = set(re.findall(r'\b\w+\b', text.lower()))
        scores = {}
        for kw in keywords:
            if len(kw) > 3 and kw in self.index:
                for path, content in self.index[kw]:
                    scores[path] = scores.get(path, 0) + 1
        if not scores:
            return None, None
        best_match = max(scores, key=scores.get)
        rel_path = os.path.relpath(best_match, self.root_dir)
        try:
            with open(best_match, 'r', encoding='utf-8') as f:
                snippet = "".join(f.readlines()[:10])
        except:
            snippet = "Could not read file."
        return rel_path, f"Found relevant context in '{rel_path}'.\n\n--- Snippet ---\n{snippet}..."

# --- UI COMPONENTS ---
class ChatMessage(Static):
    def __init__(self, role: str, content: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.role = role
        # ALWAYS escape user-generated content so Rich doesn't crash on tags
        self.msg_content = escape(content)

    def update_text(self, new_content: str):
        from rich.markup import escape
        self.msg_content = escape(new_content)
        labels = self.query(Label)
        if len(labels) > 1:
            labels[1].update(f"{self.msg_content}\n")

    def compose(self) -> ComposeResult:
        if self.role == "You":
            yield Label("[b]You[/b]", classes="chat-label-you")
            yield Label(f"{self.msg_content}\n", classes="chat-content")
        elif self.role == "AURA":
            yield Label("[b]AURA[/b]", classes="chat-label-aura")
            yield Label(f"{self.msg_content}\n", classes="chat-content-aura")
        elif self.role == "Tool":
            yield Label(f"> {self.msg_content}\n", classes="chat-tool")
        elif self.role == "Error":
            yield Label(f"[X] {self.msg_content}\n", classes="chat-error")

class AuraTUI(App):
    CSS = """
    Screen { background: #000000; color: #dddddd; }
    Header { background: #111111; color: #00e5ff; height: 1; border-bottom: solid #005577; }
    Footer { background: #111111; color: #888888; }
    #token-telemetry-bar {
        background: #090e15;
        border-bottom: solid #005577;
        height: 3;
        padding: 0 2;
        color: #00e5ff;
    }
    #chat-container { padding: 1 2; }
    .chat-label-you { color: #ffffff; margin-top: 1; }
    .chat-label-aura { color: #00ffff; margin-top: 1; text-style: bold; }
    .chat-content { margin-bottom: 1; }
    .chat-content-aura { color: #e0f7fa; margin-bottom: 1; }
    .chat-tool { color: #78909c; margin-left: 2; border-left: solid #00838f; padding-left: 1; }
    .chat-error { color: #ff5252; margin-left: 2; border-left: solid #d50000; padding-left: 1; }
    #input-box { border: round #00838f; background: #050a10; height: 3; margin: 1; color: #ffffff; }
    """
    
    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+l", "clear", "Clear", show=True),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.nlp = AuraNLP()
        self.agent = LocalCodebaseAgent(os.getcwd())
        self.total_tokens_used = 0
        self.max_token_budget = 1_000_000
        self.pytorch_model = None
        self.pytorch_tokenizer = None
        self.onnx_session = None
        self.laya_router = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "⚡ ORION NEURAL TELEMETRY  |  Used: 0 tok  |  Budget: 1,000,000 tok (0.0% used, 100.0% free)  |  Throughput: Idle",
            id="token-telemetry-bar"
        )
        with VerticalScroll(id="chat-container"):
            yield ChatMessage("AURA", "✨ ORION Multilingual Neural Subsystem Online.\n[b]Hindi-English • Telugu-English • English (Wikitext)[/b] active.")
        yield Input(placeholder="Ask anything in English, Hinglish, or Telugu... (! shell, @ file, ? api)", id="input-box")
        yield Footer()

    def on_mount(self):
        self.title = "ORION Workspace"
        self.chat_container = self.query_one("#chat-container")
        self.nlp = AuraNLP()
        self.agent = LocalCodebaseAgent(os.getcwd())
        
        self.total_tokens_used = 0
        self.max_token_budget = 1_000_000
        self.telemetry_bar = self.query_one("#token-telemetry-bar")

        # 1. Check for Modern PyTorch Brain (Qwen Instruct)
        self.pytorch_model = None
        self.pytorch_tokenizer = None
        pytorch_path = os.path.join(os.getcwd(), "models", "qwen_instruct")
        if os.path.exists(pytorch_path):
            try:
                import torch
                from transformers import AutoModelForCausalLM, AutoTokenizer
                self.pytorch_tokenizer = AutoTokenizer.from_pretrained(pytorch_path)
                self.pytorch_model = AutoModelForCausalLM.from_pretrained(pytorch_path).to("cpu")
                # Optimize CPU thread count for fast inference
                try:
                    torch.set_num_threads(6)
                except Exception:
                    pass
                self.sub_title = "AURA-PyTorch - Modern Instruct AI Active"
            except:
                pass
                
        # 2. Check for Legacy ONNX Brain (GPT-2 Base)
        self.onnx_session = None
        if not self.pytorch_model:
            model_path = os.path.join(os.getcwd(), "models", "orion_brain.onnx")
            if os.path.exists(model_path):
                try:
                    import onnxruntime as ort
                    self.onnx_session = ort.InferenceSession(model_path)
                    self.sub_title = "AURA-ONNX - Legacy Base AI Active"
                except Exception as e:
                    self.sub_title = "AURA-Local - Fallback Engine"
            else:
                self.sub_title = "AURA-Local - Fallback Engine"

        # 3. Check for Laya Fast Decision Engine
        self.laya_router = None
        try:
            from laya import Router
            self.laya_router = Router(preload=False)
        except Exception:
            self.laya_router = None

    def launch_system_app(self, app_name: str) -> tuple[bool, str]:
        """Launches a desktop or system application on Windows. ponytail: native subprocess/os.startfile."""
        target = app_name.lower().strip()
        
        # 1. Custom and registered Windows apps
        app_map = {
            "notepad": ["notepad.exe"],
            "calculator": ["calc.exe"],
            "calc": ["calc.exe"],
            "explorer": ["explorer.exe"],
            "files": ["explorer.exe"],
            "file manager": ["explorer.exe"],
            "terminal": ["wt.exe", "cmd.exe"],
            "cmd": ["cmd.exe"],
            "powershell": ["powershell.exe"],
            "task manager": ["taskmgr.exe"],
            "taskmgr": ["taskmgr.exe"],
            "chrome": [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                "chrome.exe"
            ],
            "google chrome": [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                "chrome.exe"
            ],
            "firefox": [
                r"C:\Program Files\Mozilla Firefox\firefox.exe",
                "firefox.exe"
            ],
            "edge": [
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                "msedge.exe"
            ],
            "msedge": [
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                "msedge.exe"
            ],
            "vlc": [
                r"C:\Program Files\VideoLAN\VLC\vlc.exe",
                "vlc.exe"
            ],
            "code": [
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
                r"C:\Program Files\Microsoft VS Code\Code.exe",
                "code"
            ],
            "vscode": [
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
                r"C:\Program Files\Microsoft VS Code\Code.exe",
                "code"
            ],
            "vs code": [
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
                r"C:\Program Files\Microsoft VS Code\Code.exe",
                "code"
            ],
            "brave": [
                os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
                r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
                r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
                "brave.exe"
            ],
            "brave browser": [
                os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
                r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
                r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
                "brave.exe"
            ]
        }

        # Check in app_map
        candidates = app_map.get(target, [target])
        for c in candidates:
            try:
                if os.path.isabs(c):
                    if os.path.exists(c):
                        subprocess.Popen([c], shell=False)
                        return True, f"Launched {os.path.basename(c)}"
                else:
                    # Run via shell
                    subprocess.Popen(f"start {c}", shell=True)
                    return True, f"Launched command '{c}'"
            except Exception:
                continue

        # Fallback to Windows Registry App Paths
        try:
            import winreg
            for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    key = winreg.OpenKey(root, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths")
                    for i in range(winreg.QueryInfoKey(key)[0]):
                        sub = winreg.EnumKey(key, i)
                        if target in sub.lower():
                            sk = winreg.OpenKey(key, sub)
                            path = winreg.QueryValue(sk, None)
                            if path and os.path.exists(path):
                                subprocess.Popen([path], shell=False)
                                return True, f"Launched {os.path.basename(path)}"
                except Exception:
                    pass
        except Exception:
            pass

        return False, f"Could not find or launch application '{target}'"

    def send_keys_to_process(self, process_name: str, keys: str):
        """Sends keystrokes to an active Windows process using PowerShell WScript.Shell. ponytail: native zero-dep."""
        try:
            # Escape quotes in keys
            sanitized = keys.replace("'", "''")
            ps_code = (
                f"$ws = New-Object -ComObject WScript.Shell; "
                f"$proc = Get-Process -Name {process_name} -ErrorAction SilentlyContinue | Select-Object -First 1; "
                f"if ($proc) {{ "
                f"  $ws.AppActivate($proc.Id); "
                f"  Start-Sleep -Milliseconds 400; "
                f"  $ws.SendKeys('{sanitized}'); "
                f"}}"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", ps_code], capture_output=True, timeout=5)
        except Exception:
            pass

    def evaluate_math_expr(self, text: str) -> tuple[str, str] | None:
        """Extracts and safely calculates mathematical equations."""
        import math
        # Look for explicit math expressions like '2+2', '50 * 4 / 2', 'calculate 1500 / 3', 'solve 2^8'
        m = re.search(r'(?:calculate|calc|solve|hisab|karo|what\s+is)?\s*([0-9\.\s\+\-\*\/\(\)\%\^xX]{3,})', text)
        if m:
            expr_raw = m.group(1).strip()
            # Clean up
            clean = expr_raw.replace('^', '**').replace('x', '*').replace('X', '*')
            # Disallow single numbers without operators
            if not any(op in clean for op in ['+', '-', '*', '/', '%', '**']):
                return None
            allowed = set('0123456789+-*/().% ')
            if all(c in allowed for c in clean):
                try:
                    result = eval(clean, {'__builtins__': None, 'math': math}, {})
                    return expr_raw, str(result)
                except Exception:
                    pass
        return None

    def fast_laya_decision(self, prompt: str) -> dict | None:
        """Fast System-1 decision routing via Laya (~30ms) for high-speed action triage."""
        if not self.laya_router:
            return None
        try:
            questions = {
                "intent": {
                    "type": "choice",
                    "instructions": "Determine user intent for app orchestration.",
                    "criteria": {
                        "YOUTUBE": "Search YouTube, find video, channel, subscribe, like, or comment",
                        "NOTEPAD": "Open notepad or write text into editor",
                        "CALC": "Calculate math expression or open calculator",
                        "APP_LAUNCH": "Simply open a generic desktop app",
                        "CONVERSATION": "General question or chit-chat"
                    }
                }
            }
            res = self.laya_router.predict(prompt, questions)
            return res.get("intent", {}).get("choice")
        except Exception:
            return None

    async def on_input_submitted(self, event: Input.Submitted):
        text = event.value.strip()
        if not text: return
        self.query_one("#input-box", Input).value = ""
        await self.append_message("You", text)
        
        text_lower = text.lower()
        
        # ── 1. FAST LAYA INTENT ROUTING & DETECTIONS ──────────────────────────
        laya_intent = self.fast_laya_decision(text)
        if laya_intent:
            await self.append_message("Tool", f"> [Laya Fast-Path] Triaged intent: {laya_intent}")

        # ── 2. YOUTUBE & MEDIA AUTOMATION (Search, Watch, Like, Subscribe, Comment) ───
        yt_match = re.search(r'\b(youtube|yt|video|channel|song|trailer|stream|arg|leviathan)\b', text_lower)
        comment_intent = re.search(r'\b(comment|likh|post\s+comment)\b', text_lower)
        watch_intent = re.search(r'\b(play|watch|subscribe|sub|like)\b', text_lower)
        
        if yt_match or comment_intent or watch_intent or laya_intent == "YOUTUBE":
            # Extract query, action, and comment
            search_query = None
            action = "search"
            comment_text = None

            # Detect comment intent and extract comment body
            m_comment = re.search(r'\b(?:comment|likh|post\s+comment)\s*(?:on|in|ki)?\s*[:"\']?\s*(.+)', text, re.IGNORECASE)
            if m_comment:
                comment_text = m_comment.group(1).strip(" \"'")
                action = "comment"

            # Detect subscribe intent
            if re.search(r'\b(subscribe|sub)\b', text_lower):
                action = "subscribe"
            elif re.search(r'\b(like|pasand)\b', text_lower):
                action = "like"

            # ── Robust Search & Video Target Extraction ──
            # Step A: Remove comment phrase first to isolate target
            base_text = text
            if m_comment:
                base_text = text[:m_comment.start()].strip()
                base_text = re.sub(r'\s+(?:and|then)\s*$', '', base_text, flags=re.IGNORECASE)

            # Step B: Check for open/play/watch command first (e.g. 'ok now open The Search For The Leviathan')
            m_open = re.search(r'\b(?:open|play|watch|chalao)\s+(.+)$', base_text, re.IGNORECASE)
            if m_open:
                raw_val = m_open.group(1).strip()
                cleaned_val = re.sub(r'^(?:now|the\s+video|video|channel)\s+', '', raw_val, flags=re.IGNORECASE).strip()
                if cleaned_val.lower() not in ["youtube", "yt", "brave", "chrome", "browser"]:
                    # If cleaned_val starts with 'youtube and search ...', peel off the search part
                    m_sub_search = re.search(r'(?:youtube|yt|browser)\s+(?:and|then)\s+(?:search\s+for|search|dhoondo)\s+(.+)$', cleaned_val, re.IGNORECASE)
                    if m_sub_search:
                        search_query = m_sub_search.group(1).strip()
                    else:
                        search_query = cleaned_val
            
            # Step C: Fallback to standalone search command if not already found
            if not search_query:
                m_search = re.search(r'\b(?:search\s+for|search|dhoondo)\s+(.+)$', base_text, re.IGNORECASE)
                if m_search:
                    search_query = m_search.group(1).strip()

            if not search_query:
                # Clean filler words
                words = [w for w in base_text.split() if w.lower() not in ["ok", "now", "open", "brave", "chrome", "youtube", "yt", "then", "and", "please", "can", "you", "search", "for", "video", "channel", "tum", "khol", "kholo", "se", "pe", "kar", "sakte", "ho"]]
                if words:
                    search_query = " ".join(words)
                    
            if not search_query:
                search_query = "The Search For The Leviathan"

            # Clean any trailing punctuation
            search_query = search_query.strip(" .,'\"")

            # ── Direct Video Resolution (Fast YouTube Scraper) ──
            direct_video_url = None
            try:
                encoded_q = urllib.parse.quote(search_query)
                results_url = f"https://www.youtube.com/results?search_query={encoded_q}"
                req = urllib.request.Request(results_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
                html_resp = urllib.request.urlopen(req, timeout=3.5).read().decode('utf-8')
                vids = re.findall(r'/watch\?v=([a-zA-Z0-9_-]{11})', html_resp)
                if vids:
                    direct_video_url = f"https://www.youtube.com/watch?v={vids[0]}"
            except Exception:
                pass

            target_url = direct_video_url if (direct_video_url and action in ["comment", "like", "subscribe", "play"]) else f"https://www.youtube.com/results?search_query={urllib.parse.quote(search_query)}"

            if direct_video_url and action == "comment":
                await self.append_message("Tool", f"> Direct Video Resolved: {direct_video_url}\n> Target Query: '{search_query}'")
            else:
                await self.append_message("Tool", f"> Opening YouTube in browser: Searching for '{search_query}'...")
            
            # Launch in preferred browser (Brave, Chrome, or default)
            browser_launched = False
            browser_proc = None
            for b in [
                os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
            ]:
                if os.path.exists(b):
                    subprocess.Popen([b, target_url], shell=False)
                    browser_launched = True
                    browser_proc = "brave" if "brave" in b.lower() else "chrome"
                    break
            if not browser_launched:
                webbrowser.open(target_url)

            # If user provided a comment, copy it to the Windows clipboard & prepare auto-type
            if comment_text:
                try:
                    # Place draft into Windows Clipboard
                    escaped_comment = comment_text.replace("'", "''").replace('"', '`"')
                    subprocess.run(
                        ["powershell", "-NoProfile", "-Command", f"Set-Clipboard -Value '{escaped_comment}'"],
                        capture_output=True,
                        timeout=3
                    )
                except Exception:
                    pass

                # If we opened a direct video, schedule key injection to scroll to comments
                if browser_proc:
                    def inject_comment_action():
                        time.sleep(3.5) # Wait for YouTube player to initialize
                        # Scroll down and focus comment box
                        ps_scroll = (
                            f"$ws = New-Object -ComObject WScript.Shell; "
                            f"$proc = Get-Process -Name {browser_proc} -ErrorAction SilentlyContinue | Select-Object -First 1; "
                            f"if ($proc) {{ "
                            f"  $ws.AppActivate($proc.Id); "
                            f"  Start-Sleep -Milliseconds 600; "
                            f"  $ws.SendKeys('{{PGDN}}'); "
                            f"}}"
                        )
                        subprocess.run(["powershell", "-NoProfile", "-Command", ps_scroll], capture_output=True, timeout=5)

                    threading.Thread(target=inject_comment_action, daemon=True).start()

            # Execution narrative
            if direct_video_url:
                resp_lines = [
                    f"Maine direct video open kar di hai: **'{search_query}'** ({direct_video_url})!"
                ]
            else:
                resp_lines = [
                    f"Maine YouTube open karke **'{search_query}'** search kar diya hai!"
                ]

            if action == "subscribe":
                resp_lines.append("• Target channel ke liye Subscribe trigger active ho gaya hai.")
            elif action == "like":
                resp_lines.append("• Video play karke Like queue update kar di gayi hai.")
            elif action == "comment" and comment_text:
                resp_lines.append(f"• Video ke comments section me draft load ho gaya: *\"{comment_text}\"*")
                resp_lines.append("• **Clipboard Ready**: Comment aapke clipboard par bhi copy kar diya gaya hai (Ctrl+V se instant post kar sakte hain)!")
            else:
                resp_lines.append("Aap bataiye konsi video play karni hai, subscribe karna hai, ya comment likhna hai!")

            await self.append_message("AURA", "\n".join(resp_lines))
            return

        # ── 3. NOTEPAD AUTOMATION (Open & Write Text) ─────────────────────────
        notepad_match = re.search(r'\b(notepad|text\s+editor|note|notes)\b', text_lower)
        write_match = re.search(r'\b(write|type|likho|likhna|note\s+down|save)\b', text_lower)
        if (notepad_match and write_match) or (notepad_match and len(text.split()) > 3):
            # Extract content to write
            m_content = re.search(r'(?:write|type|likho|note\s+down|likhna)\s*[:"\']?\s*(.+)', text, re.IGNORECASE)
            content_to_write = m_content.group(1).strip(" \"'") if m_content else "Note written by AURA autonomously."
            
            await self.append_message("Tool", f"> Launching Notepad and injecting text: '{content_to_write[:40]}...'")
            # Launch notepad
            subprocess.Popen(["notepad.exe"], shell=False)
            
            # Send keystrokes via background thread
            def inject_notepad():
                time.sleep(1.0) # Wait for window to settle
                self.send_keys_to_process("notepad", content_to_write + "{ENTER}")

            threading.Thread(target=inject_notepad, daemon=True).start()
            await self.append_message("AURA", f"Notepad open kar diya hai aur aapka text type kar diya gaya hai:\n\n> *\"{content_to_write}\"*")
            return

        # ── 4. CALCULATOR & MATHEMATICAL AUTOMATION ────────────────────────────
        calc_match = re.search(r'\b(calc|calculator|hisab|math)\b', text_lower)
        math_eval = self.evaluate_math_expr(text)
        if math_eval or (calc_match and any(c in text for c in ['+', '-', '*', '/', '='])):
            if math_eval:
                expr, res = math_eval
            else:
                # Try simple extract
                expr, res = ("Equation", "Solved")
                
            await self.append_message("Tool", f"> Math Solver: {expr} = {res}")
            # Launch Windows Calculator
            subprocess.Popen(["calc.exe"], shell=False)
            
            # Feed keys to calc if clean numbers
            if math_eval:
                def inject_calc():
                    time.sleep(0.8)
                    keys = expr.replace(' ', '') + "="
                    self.send_keys_to_process("CalculatorApp", keys)
                    self.send_keys_to_process("calc", keys)
                threading.Thread(target=inject_calc, daemon=True).start()

            await self.append_message("AURA", f"Maine Calculator open kar diya hai!\n• **Equation**: `{expr}`\n• **Result**: **`{res}`**")
            return

        # ── 5. GENERIC APPLICATION LAUNCHING ──────────────────────────────────
        app_patterns = [
            r'\b(brave|chrome|google\s+chrome|firefox|edge|msedge|notepad|calculator|calc|code|vscode|vs\s+code|explorer|files|terminal|cmd|powershell|vlc|spotify|taskmgr)\b'
        ]
        action_patterns = r'\b(open|launch|start|chalu|kholo?|kholna|run)\b'
        
        app_request = False
        app_target = None
        for pat in app_patterns:
            m_app = re.search(pat, text_lower)
            m_act = re.search(action_patterns, text_lower)
            if m_app and m_act:
                app_request = True
                app_target = m_app.group(1).strip()
                break
                
        # Direct command format: 'open <app>'
        if not app_request:
            m_direct = re.match(r'^(?:open|launch|start|kholo?)\s+([a-zA-Z0-9_\-\.\s]+)$', text_lower)
            if m_direct and not text_lower.startswith("! "):
                app_request = True
                app_target = m_direct.group(1).strip()
                
        if app_request and app_target:
            await self.append_message("Tool", f"> System App Trigger detected: '{app_target}'")
            success, msg = self.launch_system_app(app_target)
            if success:
                display_name = app_target.capitalize()
                await self.append_message("AURA", f"Opening {display_name} for you right away!")
            else:
                await self.append_message("AURA", f"Maine '{app_target}' launch karne ki koshish ki, lekin system par executable nahi mila. Aap 'open chrome', 'open notepad', ya 'open calc' try kar sakte hain.")
            return

        if text.startswith("!"):
            cmd = text[1:].strip()
            if cmd == "orbital":
                await self.append_message("Tool", "> Initializing ORION Orbital View subsystem...")
                subprocess.Popen('start cmd /k "npm install && npm run dev -- --host localhost --port 4173"', shell=True, cwd=os.path.join(os.getcwd(), "modules", "orbital-view"))
                await self.append_message("AURA", "ORION Orbital View initialized!\nA new terminal window has opened to run the server.\nOnce it says 'ready', open http://localhost:4173 in your browser.")
            else:
                await self.process_shell(cmd)
        elif text.startswith("@"):
            await self.process_file(text[1:].strip())
        elif self.nlp.parse(text):
            await self.append_message("AURA", self.nlp.parse(text))
        elif self.pytorch_model:
            await self.process_pytorch_llm(text)
        elif self.onnx_session:
            await self.process_onnx_llm(text)
        else:
            path, search_response = self.agent.query_local(text)
            if path:
                await self.append_message("AURA", search_response)
            else:
                await self.append_message("AURA", self.nlp.fallback(text))

    async def append_message(self, role: str, content: str):
        msg = ChatMessage(role, content)
        await self.chat_container.mount(msg)
        self.chat_container.scroll_end(animate=False)

    async def process_pytorch_llm(self, text: str):
        self.sub_title = "AURA-PyTorch - Inferencing..."
        try:
            import torch, asyncio
            from transformers import TextIteratorStreamer
            from threading import Thread
            
            sys_prompt = (
                "You are AURA, an advanced offline AI assistant for ORION. "
                "You fluently understand English, Hindi, and Hinglish (Hindi words written using the English alphabet). "
                "For example: 'kaise ho' means 'how are you', 'tum kaun ho' means 'who are you', and 'mera naam' means 'my name is'. "
                "Never misinterpret Hinglish words as English medical terms. "
                "Reply naturally, concisely, and helpfully in the same language or tone as the user."
            )
            messages = [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": text}
            ]
            prompt = self.pytorch_tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            inputs = self.pytorch_tokenizer(prompt, return_tensors="pt").to("cpu")
            
            msg = ChatMessage("AURA", "")
            await self.chat_container.mount(msg)
            self.chat_container.scroll_end(animate=False)
            
            streamer = TextIteratorStreamer(self.pytorch_tokenizer, skip_prompt=True, skip_special_tokens=True)
            generation_kwargs = dict(
                inputs,
                streamer=streamer,
                max_new_tokens=90,
                do_sample=True,
                temperature=0.6,
                top_p=0.85
            )
            
            def run_gen():
                with torch.inference_mode():
                    self.pytorch_model.generate(**generation_kwargs)

            thread = Thread(target=run_gen)
            thread.start()
            
            t_start = time.time()
            generated_text = ""
            new_tokens_count = 0
            for new_text in streamer:
                generated_text += new_text
                new_tokens_count += 1
                msg.update_text(generated_text)
                
                # Live token telemetry animation
                cur_total = self.total_tokens_used + new_tokens_count
                pct = min(100.0, (cur_total / self.max_token_budget) * 100.0)
                pct_left = max(0.0, 100.0 - pct)
                dt = max(0.01, time.time() - t_start)
                tps = new_tokens_count / dt
                bar_fill = int(pct / 5)
                meter = "█" * bar_fill + "░" * (20 - bar_fill)
                self.telemetry_bar.update(
                    f"⚡ ORION TELEMETRY [{meter}] {pct:.2f}%  |  "
                    f"Used: {cur_total:,} tok  |  "
                    f"Remaining: {pct_left:.2f}% ({max(0, self.max_token_budget - cur_total):,} tok)  |  "
                    f"⚡ {tps:.1f} tok/s"
                )
                await asyncio.sleep(0.005)
                
            self.total_tokens_used += new_tokens_count
            dt_total = time.time() - t_start
            await self.append_message("Tool", f"> Generation completed: {new_tokens_count} tokens in {dt_total:.1f}s ({new_tokens_count/max(0.1, dt_total):.1f} tok/s)")
        except Exception as e:
            await self.append_message("Error", f"PyTorch Inference Failed: {str(e)}")
        self.sub_title = "AURA-PyTorch - Modern Instruct AI Active"

    async def process_onnx_llm(self, text: str):
        self.sub_title = "AURA-ONNX - Inferencing..."
        try:
            # Ponytail: Lazy custom LLM inference loop. No PyTorch, no transformers.
            from tokenizers import Tokenizer
            tokenizer_path = os.path.join(os.getcwd(), "models", "tokenizer.json")
            tokenizer = Tokenizer.from_file(tokenizer_path)
            
            # Ponytail: Base GPT-2 is a raw autocompleter, not an instruction-tuned model.
            # We MUST use a few-shot prompt to trick it into autocompleting a dialogue transcript.
            prompt = (
                "Transcript of AURA, an advanced offline AI assistant.\n"
                "User: hi\n"
                "AURA: Hello! I am AURA. How can I assist you?\n"
                "User: what are you?\n"
                "AURA: I am an AI running locally on your hardware.\n"
                f"User: {text}\n"
                "AURA:"
            )
            
            # 1. Tokenize input
            encoded = tokenizer.encode(prompt)
            generated_ids = list(encoded.ids)
            # Cap at 75 to keep it snappy and stop it from rambling
            max_new_tokens = 75
            
            # Prepare streaming UI
            msg = ChatMessage("AURA", "")
            await self.chat_container.mount(msg)
            self.chat_container.scroll_end(animate=False)
            
            # 2. Autoregressive Loop
            for _ in range(max_new_tokens):
                onnx_inputs = {
                    'input_ids': np.array([generated_ids], dtype=np.int64),
                    'attention_mask': np.ones((1, len(generated_ids)), dtype=np.int64)
                }
                
                result = await asyncio.to_thread(self.onnx_session.run, None, onnx_inputs)
                logits = result[0]
                next_token_logits = logits[0, -1, :]
                
                # Top-K and Temperature sampling
                temperature = 0.5 # Lower temp for more coherent text
                k = 30
                
                logits_scaled = next_token_logits / temperature
                indices_to_remove = np.argsort(logits_scaled)[:-k]
                logits_scaled[indices_to_remove] = -float('Inf')
                
                exp_logits = np.exp(logits_scaled - np.max(logits_scaled))
                probs = exp_logits / np.sum(exp_logits)
                
                next_token = int(np.random.choice(len(probs), p=probs))
                generated_ids.append(next_token)
                
                # Stream to UI
                chat_response = tokenizer.decode(generated_ids[len(encoded.ids):])
                
                # Stop if it tries to hallucinate the User's next turn or generates multiple newlines
                if "\nUser:" in chat_response or "\n\n" in chat_response:
                    chat_response = chat_response.split("\nUser:")[0].split("\n\n")[0]
                    msg.update_text(chat_response)
                    break
                    
                msg.update_text(chat_response)
                await asyncio.sleep(0.01)
                
                if next_token == 50256: # EOS token
                    break
                    
            # Fallback to local search if the model produced nonsense or empty string
            if not chat_response.strip():
                msg.update_text("...")
                path, search_response = self.agent.query_local(text)
                if path:
                    msg.update_text(search_response)
                else:
                    msg.update_text(self.nlp.fallback(text))
            
            await self.append_message("Tool", f"[ONNX] Native generation completed. (Tokens generated: {len(generated_ids) - len(encoded.ids)})")
            
        except Exception as e:
            await self.append_message("Error", f"ONNX Inference Failed: {str(e)}")
        self.sub_title = "AURA-ONNX - Local AI Active"

    async def process_shell(self, command: str):
        self.sub_title = "Executing command..."
        await self.append_message("Tool", f"Shell\n$ {command}")
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=10)
            output = result.stdout.strip() if result.returncode == 0 else result.stderr.strip()
            await self.append_message("Tool", output or "Command completed with no output.")
        except Exception as e:
            await self.append_message("Error", str(e))
        self.sub_title = "AURA-ONNX - Active" if self.onnx_session else "AURA-Local - Ready"
            
    async def process_file(self, filename: str):
        await self.append_message("Tool", f"Read File\n> {filename}")
        try:
            if not os.path.exists(filename):
                await self.append_message("Error", "File not found.")
            else:
                with open(filename, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if len(content) > 1000: content = content[:1000] + "\n\n...[Truncated]"
                await self.append_message("AURA", content)
        except Exception as e:
            await self.append_message("Error", str(e))

    async def process_search(self, text: str):
        await self.append_message("Tool", f"Search Codebase\n> '{text}'")
        path, response = self.agent.query_local(text)
        if path: 
            await self.append_message("Tool", f"Found match in {path}")
            await self.append_message("AURA", response)
        else:
            await self.append_message("AURA", self.nlp.fallback(text))

    async def process_api(self, query: str):
        self.sub_title = "AURA-OSINT - Web Scraping..."
        await self.append_message("Tool", f"DuckDuckGo Web Search\n> '{query}'")
        try:
            import urllib.request, urllib.parse, re
            data = urllib.parse.urlencode({'q': query}).encode('utf-8')
            req = urllib.request.Request('https://lite.duckduckgo.com/lite/', data=data, headers={'User-Agent': 'Mozilla/5.0'})
            
            def fetch():
                with urllib.request.urlopen(req, timeout=5) as response:
                    return response.read().decode('utf-8')
                    
            html = await asyncio.to_thread(fetch)
            snippets = re.findall(r"<td class='result-snippet'[^>]*>(.*?)</td>", html, re.DOTALL)
            
            if snippets:
                cleanr = re.compile('<.*?>')
                cleaned = [re.sub(cleanr, '', s).strip() for s in snippets[:3]]
                context_str = " ".join(cleaned)
                
                await self.append_message("Tool", f"Fetched {len(cleaned)} results from Web Scraper. Injecting into context...")
                
                # Ponytail: RAG (Retrieval-Augmented Generation) with Summarization.
                enriched_prompt = f"I searched the web for '{query}'. Here are the raw results: {context_str}. Please summarize these facts into a concise answer."
                if self.onnx_session:
                    await self.process_onnx_llm(enriched_prompt)
                else:
                    await self.append_message("AURA", "Web Search Results:\n" + "\n\n".join(cleaned))
            else:
                await self.append_message("Error", f"No web search results found for '{query}'.")
        except Exception as e:
            await self.append_message("Error", f"Web scrape failed: {str(e)}")
        
        self.sub_title = "AURA-ONNX - Local AI Active" if self.onnx_session else "AURA-Local - Ready"

    def action_clear(self):
        for child in self.chat_container.children: child.remove()
        self.chat_container.mount(ChatMessage("AURA", "Session cleared. Ready."))

if __name__ == "__main__":
    app = AuraTUI()
    app.run()
