import httpx
resp = httpx.post("http://localhost:11434/api/generate", json={
    "model": "qwen2:0.5b",
    "prompt": "Respond strictly with {\"test\": 1}",
    "stream": False,
    "format": "json"
})
print(resp.json())
