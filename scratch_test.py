from textual.app import App, ComposeResult
from textual.widgets import Static, Label
from rich.markup import escape

class ChatMessage(Static):
    def __init__(self, role: str, content: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.role = role
        self.content = escape(content)
        
    def compose(self) -> ComposeResult:
        yield Label(f"ROLE: {self.role}")
        yield Label(f"CONTENT: {self.content}")

class MyApp(App):
    def compose(self) -> ComposeResult:
        yield ChatMessage("AURA", "Hello world!")

if __name__ == '__main__':
    app = MyApp()
    app.run()
