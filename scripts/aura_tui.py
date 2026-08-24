import os
import re
import asyncio
import subprocess
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Header, Footer, Static, Input, Label
from textual.binding import Binding

# --- LOCAL CODEBASE SEARCH ENGINE (No Pretrained Models) ---
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
                if file.endswith(('.py', '.md', '.json', '.yml')):
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

    def query(self, text):
        keywords = set(re.findall(r'\b\w+\b', text.lower()))
        scores = {}
        for kw in keywords:
            if kw in self.index:
                for path, content in self.index[kw]:
                    scores[path] = scores.get(path, 0) + 1
        
        if not scores:
            return None, "I searched the local ORION codebase but couldn't find any files matching your keywords."
            
        best_match = max(scores, key=scores.get)
        rel_path = os.path.relpath(best_match, self.root_dir)
        
        try:
            with open(best_match, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                snippet = "".join(lines[:10])
        except:
            snippet = "Could not read file."
            
        response = f"Based on the current codebase, I found relevant context in '{rel_path}'.\n\n[dim]Snippet:[/dim]\n{snippet}..."
        return rel_path, response

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
            yield ChatMessage("AURA", "ORION Agent Initialized. I am running locally without external models. \nTry: '!dir' to run a command, '@README.md' to read a file, or ask a question to search the repo.")
        yield Input(placeholder="Ask anything... (! shell, @ file)", id="input-box")
        yield Footer()

    def on_mount(self):
        self.title = "ORION Workspace"
        self.sub_title = "AURA-Local - indexing codebase..."
        self.chat_container = self.query_one("#chat-container")
        self.agent = LocalCodebaseAgent(os.getcwd())
        self.sub_title = "AURA-Local - ready"

    async def on_input_submitted(self, event: Input.Submitted):
        if not event.value.strip():
            return
            
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
        
        await self.process_search(user_text)

    async def append_message(self, role: str, content: str):
        msg = ChatMessage(role, content)
        await self.chat_container.mount(msg)
        self.chat_container.scroll_end(animate=False)
        
    async def process_shell(self, command: str):
        self.sub_title = "AURA-Local - running command..."
        await self.append_message("Tool", f"Shell\n$ {command}")
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                output = result.stdout.strip()
                if not output: output = "Command completed with no output."
                await self.append_message("Tool", output)
            else:
                await self.append_message("Error", result.stderr.strip())
        except Exception as e:
            await self.append_message("Error", str(e))
        self.sub_title = "AURA-Local - ready"
            
    async def process_file(self, filename: str):
        self.sub_title = "AURA-Local - reading file..."
        await self.append_message("Tool", f"Read File\n> {filename}")
        try:
            if not os.path.exists(filename):
                await self.append_message("Error", "File not found.")
            else:
                with open(filename, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if len(content) > 1000:
                        content = content[:1000] + "\n\n...[Truncated]"
                await self.append_message("AURA", content)
        except Exception as e:
            await self.append_message("Error", str(e))
        self.sub_title = "AURA-Local - ready"

    async def process_search(self, text: str):
        self.sub_title = "AURA-Local - searching..."
        await self.append_message("Tool", f"Search Codebase\n> '{text}'")
        
        path, response = self.agent.query(text)
        if path:
            await self.append_message("Tool", f"Found match in {path}")
            
        await self.append_message("AURA", response)
        self.sub_title = "AURA-Local - ready"

    def action_clear(self):
        for child in self.chat_container.children:
            child.remove()
        self.chat_container.mount(ChatMessage("AURA", "Session cleared. Ready."))

if __name__ == "__main__":
    app = AuraTUI()
    app.run()
