with open('scripts/aura_tui.py', 'r') as f:
    text = f.read()

text = text.replace('    async def process_onnx_llm(self, text: str):\n    async def process_onnx_llm(self, text: str):', '    async def process_onnx_llm(self, text: str):')

with open('scripts/aura_tui.py', 'w') as f:
    f.write(text)
