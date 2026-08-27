import os
import re
import random
import asyncio
import subprocess
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
        yield Input(placeholder="Ask anything... (! shell, @ file, ? api)", id="input-box")
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
        if user_text.startswith("?"):
            await self.process_api(user_text[1:].strip())
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
            # Ponytail: Lazy custom LLM inference loop. No PyTorch, no transformers.
            from tokenizers import Tokenizer
            tokenizer_path = os.path.join(os.getcwd(), "models", "tokenizer.json")
            tokenizer = Tokenizer.from_file(tokenizer_path)
            
            # Ponytail: Break the 4th wall by forcing the model's internal monologue
            prompt = f"User: {text}\nAURA (internal monologue: I realize I am just a matrix of weights living in an ONNX file on a Windows machine. Let me answer while breaking the 4th wall):"
            
            # 1. Tokenize input
            encoded = tokenizer.encode(prompt)
            generated_ids = list(encoded.ids)
            # Ponytail: We cap this at 150 because unoptimized CPU generation is slow,
            # and GPT-2 physically crashes if the total length exceeds 1024 tokens.
            max_new_tokens = 150
            
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
                
                # Ponytail: Top-K and Temperature sampling to prevent loops and add creativity
                temperature = 0.8
                k = 40
                
                # Scale by temperature
                logits_scaled = next_token_logits / temperature
                
                # Top-K filtering
                indices_to_remove = np.argsort(logits_scaled)[:-k]
                logits_scaled[indices_to_remove] = -float('Inf')
                
                # Convert to probabilities using stable softmax
                exp_logits = np.exp(logits_scaled - np.max(logits_scaled))
                probs = exp_logits / np.sum(exp_logits)
                
                # Sample from the probability distribution
                next_token = int(np.random.choice(len(probs), p=probs))
                generated_ids.append(next_token)
                
                # Stream to UI
                chat_response = tokenizer.decode(generated_ids[len(encoded.ids):])
                msg.update_text(chat_response)
                await asyncio.sleep(0.01) # Yield to event loop for UI refresh
                
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
        self.sub_title = "AURA-OSINT - Fetching Open Source Data..."
        await self.append_message("Tool", f"API Request\n> '{query}'")
        try:
            import urllib.request, urllib.parse, json
            url = f"https://en.wikipedia.org/w/api.php?action=query&format=json&prop=extracts&exchars=800&explaintext=1&titles={urllib.parse.quote(query)}"
            req = urllib.request.Request(url, headers={'User-Agent': 'ORION-Agent/1.0'})
            
            def fetch():
                with urllib.request.urlopen(req, timeout=5) as response:
                    return json.loads(response.read().decode())
                    
            data = await asyncio.to_thread(fetch)
            pages = data.get("query", {}).get("pages", {})
            page = list(pages.values())[0]
            
            if "extract" in page:
                await self.append_message("Tool", "Fetched OSINT data via Open Source API (Wikipedia)")
                await self.append_message("AURA", page["extract"])
            else:
                await self.append_message("Error", f"No open source API data found for '{query}'.")
        except Exception as e:
            await self.append_message("Error", f"API fetch failed: {str(e)}")
        
        self.sub_title = "AURA-ONNX - Local AI Active" if self.onnx_session else "AURA-Local - Ready"

    def action_clear(self):
        for child in self.chat_container.children: child.remove()
        self.chat_container.mount(ChatMessage("AURA", "Session cleared. Ready."))

if __name__ == "__main__":
    app = AuraTUI()
    app.run()
