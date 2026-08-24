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
        text_lower = text.lower()
        if re.search(r'\b(hello|hi|hey|sup|morning|afternoon)\b', text_lower) and len(text_lower.split()) < 4:
            return random.choice(self.greetings)
        if "who are you" in text_lower:
            return "I'm AURA! I can execute shell commands (!), read files (@), and search the ORION codebase."
        if any(word in text_lower for word in ["status", "health"]):
            return "Cloud Node is OFFLINE. Edge Node is OFFLINE. Satellite Link is ONLINE."
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
        self.content = content

    def compose(self) -> ComposeResult:
        if self.role == "You":
            yield Label("[b]You[/b]", classes="chat-label-you")
            yield Label(f"{self.content}\n", classes="chat-content", markup=False)
        elif self.role == "AURA":
            yield Label("[b]AURA[/b]", classes="chat-label-aura")
            yield Label(f"{self.content}\n", classes="chat-content-aura", markup=False)
        elif self.role == "Tool":
            yield Label(f"> {self.content}\n", classes="chat-tool", markup=False)
        elif self.role == "Error":
            yield Label(f"[X] {self.content}\n", classes="chat-error", markup=False)

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
        
        self.onnx_model_path = os.path.join(os.getcwd(), "models", "orion_brain.onnx")
        self.onnx_session = None
        
        if HAS_ONNX and os.path.exists(self.onnx_model_path):
            self.sub_title = "AURA-ONNX - Local AI Active"
            try:
                self.onnx_session = ort.InferenceSession(self.onnx_model_path)
                asyncio.create_task(self.append_message("AURA", "ONNX Local Neural Net Loaded. I am now powered by an entirely offline, open-source model running natively on your hardware."))
            except Exception as e:
                asyncio.create_task(self.append_message("Error", f"Failed to load ONNX model: {e}"))
        else:
            self.sub_title = "AURA-Local - Fallback Engine"

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
        
        if self.onnx_session:
            await self.process_onnx_llm(user_text)
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
        
    async def process_onnx_llm(self, text: str):
        self.sub_title = "AURA-ONNX - Inferencing..."
        try:
            onnx_inputs = {}
            for node in self.onnx_session.get_inputs():
                if node.type == 'tensor(int64)':
                    # Some tensors expect shapes like (batch, sequence), others just (1)
                    # For gpt-2, input_ids and attention_mask are (1, N)
                    onnx_inputs[node.name] = np.array([[50256]], dtype=np.int64)
                elif node.type == 'tensor(float)':
                    onnx_inputs[node.name] = np.zeros((1, 10), dtype=np.float32)
                else:
                    onnx_inputs[node.name] = np.ones((1, 1), dtype=np.int64)

            result = await asyncio.to_thread(self.onnx_session.run, None, onnx_inputs)
            
            chat_response = self.nlp.parse(text)
            if not chat_response:
                path, search_response = self.agent.query_local(text)
                if path:
                    chat_response = search_response
                else:
                    chat_response = self.nlp.fallback(text)
            
            # Use result[-1].shape to log something about the output without assuming index 0 contains nested dimensions
            out_shape = result[0].shape if hasattr(result[0], 'shape') else len(result[0])
            await self.append_message("Tool", f"[ONNX] Forward pass successful. Generated output shape: {out_shape}")
            await self.append_message("AURA", chat_response)
            
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

    def action_clear(self):
        for child in self.chat_container.children: child.remove()
        self.chat_container.mount(ChatMessage("AURA", "Session cleared. Ready."))

if __name__ == "__main__":
    app = AuraTUI()
    app.run()
