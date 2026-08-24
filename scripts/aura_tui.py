import os
import re
import random
import asyncio
import subprocess
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Header, Footer, Static, Input, Label
from textual.binding import Binding

try:
    import google.generativeai as genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

# --- CONVERSATIONAL ENGINE (FALLBACK) ---
class AuraNLP:
    def __init__(self):
        self.greetings = ["Hey! AURA here.", "Hello! I'm online.", "Hi there.", "Hey Operator, AURA standing by."]
    def parse(self, text):
        text_lower = text.lower()
        if re.search(r'\b(hello|hi|hey|sup|morning|afternoon)\b', text_lower) and len(text_lower.split()) < 4:
            return random.choice(self.greetings)
        if "who are you" in text_lower:
            return "I'm AURA! I can execute shell commands (!), read files (@), and search the ORION codebase."
        if any(word in text_lower for word in ["status", "health"]):
            return "Cloud Node is OFFLINE. Edge Node is OFFLINE. Satellite Link is ONLINE."
        return None

# --- LOCAL CODEBASE SEARCH ENGINE ---
class LocalCodebaseAgent:
    def __init__(self, root_dir):
        self.root_dir = root_dir
        self.index = {}
        self.raw_context = ""
        self.build_index()

    def build_index(self):
        context_chunks = []
        for root, _, files in os.walk(self.root_dir):
            if '.git' in root or '__pycache__' in root or 'node_modules' in root:
                continue
            for file in files:
                if file.endswith(('.py', '.md')):
                    path = os.path.join(root, file)
                    try:
                        with open(path, 'r', encoding='utf-8') as f:
                            content = f.read()
                            if len(content) < 5000: # Only index smaller files for context
                                context_chunks.append(f"--- FILE: {file} ---\n{content}\n")
                            content_lower = content.lower()
                            words = set(re.findall(r'\b\w+\b', content_lower))
                            for word in words:
                                if len(word) > 3:
                                    if word not in self.index:
                                        self.index[word] = []
                                    self.index[word].append((path, content_lower))
                    except Exception:
                        pass
        # Build a mega-context string for the real LLM
        self.raw_context = "".join(context_chunks)[:20000] # cap at 20k chars

    def query_local(self, text):
        keywords = set(re.findall(r'\b\w+\b', text.lower()))
        scores = {}
        for kw in keywords:
            if len(kw) > 3 and kw in self.index:
                for path, content in self.index[kw]:
                    scores[path] = scores.get(path, 0) + 1
        if not scores:
            return None, "I searched the local codebase but found no matches."
        best_match = max(scores, key=scores.get)
        rel_path = os.path.relpath(best_match, self.root_dir)
        try:
            with open(best_match, 'r', encoding='utf-8') as f:
                snippet = "".join(f.readlines()[:10])
        except:
            snippet = "Could not read file."
        return rel_path, f"Found relevant context in '{rel_path}'.\n\n[dim]Snippet:[/dim]\n{snippet}..."

# --- UI COMPONENTS ---
class ChatMessage(Static):
    def __init__(self, role: str, content: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.role = role
        self.content = content

    def compose(self) -> ComposeResult:
        if self.role == "You":
            yield Label("[b]You[/b]", classes="chat-label-you")
            yield Label(f"{self.content}\n", classes="chat-content")
        elif self.role == "AURA":
            yield Label("[b]AURA[/b]", classes="chat-label-aura")
            yield Label(f"{self.content}\n", classes="chat-content-aura")
        elif self.role == "Tool":
            yield Label(f"[dim]> {self.content}[/dim]\n", classes="chat-tool")
        elif self.role == "Error":
            yield Label(f"[red][X] {self.content}[/red]\n", classes="chat-error")

class AuraTUI(App):
    CSS = """
    Screen { background: #000000; color: #dddddd; }
    Header { background: #111111; color: #888888; height: 1; border-bottom: solid #222222; }
    Footer { background: #111111; color: #888888; }
    #chat-container { padding: 1 2; }
    .chat-label-you { color: #ffffff; margin-top: 1; }
    .chat-label-aura { color: #00ffff; margin-top: 1; }
    .chat-content { margin-bottom: 1; }
    .chat-content-aura { color: #cccccc; margin-bottom: 1; }
    .chat-tool { color: #666666; margin-left: 2; border-left: solid #333333; padding-left: 1; }
    .chat-error { color: #ff5555; margin-left: 2; border-left: solid #ff0000; padding-left: 1; }
    #input-box { border: round #333333; background: #000000; height: 3; margin: 1; }
    """
    
    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+l", "clear", "Clear", show=True),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="chat-container"):
            yield ChatMessage("AURA", "ORION Agent Initialized.")
        yield Input(placeholder="Ask anything... (! shell, @ file)", id="input-box")
        yield Footer()

    def on_mount(self):
        self.title = "ORION Workspace"
        self.chat_container = self.query_one("#chat-container")
        self.agent = LocalCodebaseAgent(os.getcwd())
        self.nlp = AuraNLP()
        
        self.api_key = os.environ.get("GEMINI_API_KEY")
        if self.api_key and HAS_GENAI:
            self.sub_title = "AURA-Gemini - Online & Active"
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel('gemini-1.5-flash')
            asyncio.create_task(self.append_message("AURA", "[green]Neural Link Established.[/green] I am running on a live Gemini model with full context of the ORION codebase. I am highly talkative. Ask me anything!"))
        else:
            self.sub_title = "AURA-Local - Limited Fallback Mode"
            self.model = None
            asyncio.create_task(self.append_message("AURA", "[yellow]Warning: GEMINI_API_KEY not found in environment.[/yellow] \nI am running in local fallback mode. I can only do basic regex searches and chit-chat. \nTo make me fully intelligent and talkative, set your GEMINI_API_KEY in the terminal before running me:\n> set GEMINI_API_KEY=your_key_here"))

    async def on_input_submitted(self, event: Input.Submitted):
        if not event.value.strip(): return
        user_text = event.value
        event.input.value = ""
        await self.append_message("You", user_text)
        
        if user_text.lower() in ["clear"]:
            self.action_clear()
            return
        if user_text.startswith("!"):
            await self.process_shell(user_text[1:].strip())
            return
        if user_text.startswith("@"):
            await self.process_file(user_text[1:].strip())
            return
        
        # 1. LIVE LLM MODE (Highly Talkative)
        if self.model:
            await self.process_live_llm(user_text)
        # 2. LOCAL FALLBACK MODE
        else:
            chat_response = self.nlp.parse(user_text)
            if chat_response:
                await self.append_message("AURA", chat_response)
            else:
                await self.process_search(user_text)

    async def append_message(self, role: str, content: str):
        msg = ChatMessage(role, content)
        await self.chat_container.mount(msg)
        self.chat_container.scroll_end(animate=False)
        
    async def process_live_llm(self, text: str):
        self.sub_title = "AURA-Gemini - Thinking..."
        try:
            prompt = f"You are AURA, an advanced AI coding assistant built for Project ORION. \nYou are highly talkative, intelligent, and human-like. \nUse the following codebase context to answer the user's questions accurately. If they just say hi, chat with them normally.\n\nCODEBASE CONTEXT:\n{self.agent.raw_context}\n\nUSER PROMPT: {text}"
            
            # Since this is an async UI, we use asyncio.to_thread to prevent blocking the UI
            response = await asyncio.to_thread(self.model.generate_content, prompt)
            await self.append_message("AURA", response.text.strip())
        except Exception as e:
            await self.append_message("Error", f"LLM Generation Failed: {str(e)}")
        self.sub_title = "AURA-Gemini - Online & Active"

    async def process_shell(self, command: str):
        self.sub_title = "Executing command..."
        await self.append_message("Tool", f"Shell\n$ {command}")
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=10)
            output = result.stdout.strip() if result.returncode == 0 else result.stderr.strip()
            await self.append_message("Tool", output or "Command completed with no output.")
        except Exception as e:
            await self.append_message("Error", str(e))
        self.sub_title = "AURA-Gemini - Online & Active" if self.model else "AURA-Local - Limited Fallback Mode"
            
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
        if path: await self.append_message("Tool", f"Found match in {path}")
        await self.append_message("AURA", response)

    def action_clear(self):
        for child in self.chat_container.children: child.remove()
        self.chat_container.mount(ChatMessage("AURA", "Session cleared. Ready."))

if __name__ == "__main__":
    app = AuraTUI()
    app.run()
