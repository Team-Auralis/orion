import time
import json
import random
import re
import asyncio
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Header, Footer, Static, Input, Label
from textual.binding import Binding

# --- MOCK CAPABILITIES ---
REGISTRY = {
    "comm.cloud": {"status": "OFFLINE", "cost": 1},
    "comm.edge": {"status": "OFFLINE", "cost": 2},
    "comm.satellite": {"status": "ONLINE", "cost": 10},
    "surveillance.drone": {"status": "ONLINE", "cost": 5}
}

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
            yield Label("[b]Assistant[/b]", classes="chat-label-aura")
            yield Label(f"{self.content}\n", classes="chat-content-aura")
        elif self.role == "Tool":
            yield Label(f"[dim]? {self.content}[/dim]\n", classes="chat-tool")

class AuraTUI(App):
    CSS = """
    Screen {
        background: #000000;
        color: #dddddd;
    }
    Header {
        background: #111111;
        color: #888888;
        height: 1;
        border-bottom: solid #222222;
    }
    Footer {
        background: #111111;
        color: #888888;
    }
    #chat-container {
        padding: 1 2;
    }
    .chat-label-you {
        color: #ffffff;
        margin-top: 1;
    }
    .chat-label-aura {
        color: #aaaaaa;
        margin-top: 1;
    }
    .chat-content {
        margin-bottom: 1;
    }
    .chat-content-aura {
        color: #cccccc;
        margin-bottom: 1;
    }
    .chat-tool {
        color: #666666;
    }
    #input-box {
        border: round #333333;
        background: #000000;
        height: 3;
        margin: 1;
    }
    """
    
    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+l", "clear", "Clear", show=True),
        Binding("tab", "switch_agent", "Switch Agent", show=True)
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="chat-container"):
            yield ChatMessage("AURA", "I am the ORION Agent. What do you want to build or execute?")
        yield Input(placeholder="Ask anything... (@ files, ! shell, / commands)", id="input-box")
        yield Footer()

    def on_mount(self):
        self.title = "my-project"
        self.sub_title = "claude-sonnet - agent"
        self.chat_container = self.query_one("#chat-container")

    async def on_input_submitted(self, event: Input.Submitted):
        if not event.value.strip():
            return
            
        user_text = event.value
        event.input.value = ""
        
        await self.append_message("You", user_text)
        
        if user_text.lower() in ["clear"]:
            self.action_clear()
            return
        elif user_text.startswith("!"):
            await self.process_shell(user_text)
            return
        
        await self.process_intent(user_text)

    async def append_message(self, role: str, content: str):
        msg = ChatMessage(role, content)
        await self.chat_container.mount(msg)
        self.chat_container.scroll_end(animate=False)
        
    async def process_shell(self, text: str):
        await self.append_message("Tool", f"Shell\\n$ {text[1:]}\\n\\nExecuted successfully.")

    async def process_intent(self, text: str):
        text_lower = text.lower()
        self.sub_title = "claude-sonnet - working"
        
        if "status" in text_lower or "health" in text_lower:
            await asyncio.sleep(0.5)
            await self.append_message("Tool", "Read registry.state")
            await self.append_message("AURA", "Cloud Node is OFFLINE. Edge Node is OFFLINE. Satellite Link is ONLINE.")
        elif "comm" in text_lower or "broadcast" in text_lower:
            await self.append_message("AURA", "I'll inspect the infrastructure first.")
            await asyncio.sleep(0.5)
            await self.append_message("Tool", "Search 'comm.*'")
            await self.append_message("Tool", "Attempting comm.cloud -> OFFLINE")
            await asyncio.sleep(0.3)
            await self.append_message("Tool", "Attempting comm.edge -> OFFLINE")
            await asyncio.sleep(0.3)
            await self.append_message("AURA", "Only 'comm.satellite' is available, but it requires VEIL authorization. \\nAutomatically signing request using operator credentials...")
            await asyncio.sleep(0.8)
            await self.append_message("Tool", "Edit configuration\\n@@\\n- comm_link = 'cloud'\\n+ comm_link = 'satellite'\\n\\nTarget 'comm.satellite' executed successfully.")
        else:
            await self.append_message("AURA", "I have parsed your request. I will generate a plan to achieve this.")
            
        self.sub_title = "claude-sonnet - agent"

    def action_clear(self):
        for child in self.chat_container.children:
            child.remove()
        self.chat_container.mount(ChatMessage("AURA", "Session cleared. Ready."))

if __name__ == "__main__":
    app = AuraTUI()
    app.run()
