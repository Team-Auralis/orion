import sys

with open('scripts/aura_tui.py', 'r') as f:
    lines = f.readlines()

new_lines = []
skip = False

replacement = '''
    async def on_input_submitted(self, event: Input.Submitted):
        text = event.value.strip()
        if not text: return
        self.query_one("#input-box", Input).value = ""
        await self.append_message("You", text)
        
        if text.startswith("!"):
            await self.process_shell(text[1:].strip())
        elif text.startswith("@"):
            await self.process_file(text[1:].strip())
        elif text.startswith("?"):
            await self.process_api(text[1:].strip())
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
            
            messages = [
                {"role": "system", "content": "You are AURA, an advanced offline AI assistant. Keep answers brief and helpful."},
                {"role": "user", "content": text}
            ]
            prompt = self.pytorch_tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            inputs = self.pytorch_tokenizer(prompt, return_tensors="pt").to("cpu")
            
            msg = ChatMessage("AURA", "")
            await self.chat_container.mount(msg)
            self.chat_container.scroll_end(animate=False)
            
            streamer = TextIteratorStreamer(self.pytorch_tokenizer, skip_prompt=True, skip_special_tokens=True)
            generation_kwargs = dict(inputs, streamer=streamer, max_new_tokens=150, temperature=0.7, top_p=0.9)
            
            thread = Thread(target=self.pytorch_model.generate, kwargs=generation_kwargs)
            thread.start()
            
            generated_text = ""
            for new_text in streamer:
                generated_text += new_text
                msg.update_text(generated_text)
                await asyncio.sleep(0.01)
                
            await self.append_message("Tool", "> Generation completed via Modern PyTorch Instruct Engine.")
        except Exception as e:
            await self.append_message("Error", f"PyTorch Inference Failed: {str(e)}")
        self.sub_title = "AURA-PyTorch - Modern Instruct AI Active"

    async def process_onnx_llm(self, text: str):
'''

for i, line in enumerate(lines):
    if "async def on_input_submitted" in line:
        new_lines.append(replacement.lstrip('\n'))
        skip = True
    elif "async def process_onnx_llm" in line:
        skip = False
        
    if not skip:
        new_lines.append(line)

with open('scripts/aura_tui.py', 'w') as f:
    f.writelines(new_lines)
