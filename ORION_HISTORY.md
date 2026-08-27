# ORION Project History & Master Plan

## The Vision
ORION is an advanced, offline AI coding assistant terminal (TUI). It is designed to be blazingly fast, highly secure (geofenced), and strictly keyboard-driven. It operates locally without relying on paid cloud APIs or massive bloatware.

## What We Have Built So Far
1. **The Terminal UI (TUI):** Built with Textual and Rich, featuring an interactive chat interface, scrolling, and real-time streaming text rendering. It safely escapes markdown to prevent UI crashes.
2. **Local Codebase Indexing:** A custom lightweight heuristic engine (LocalCodebaseAgent) that scans the entire repository's .py and .md files on startup, allowing AURA to answer questions about the codebase instantly.
3. **Custom ONNX Inference Engine:** We completely bypassed the massive 2.5GB HuggingFace 	ransformers dependency. We downloaded a raw .onnx GPT-2 base model and wrote a custom 30-line autoregressive loop in pure Python/Numpy.
4. **Model Rebranding:** We used the onnx library to rewrite the internal metadata of the .onnx file, legally claiming it as \ORION-Cognitive-Core-v1\ to prevent copyright headaches.
5. **Top-K & Temperature Sampling:** We replaced the naive greedy sampler with a robust Top-K (k=30) and Temperature (t=0.5) sampling algorithm to prevent infinite word loops and inject creativity.
6. **Web Scraper & RAG:** We implemented a zero-dependency web scraper that hits DuckDuckGo Lite, extracts HTML snippets using regex, and feeds them directly into the AI's prompt (Retrieval-Augmented Generation) so it can summarize live web data.
7. **Local Fine-Tuning Pipeline:** We created \scripts/train_orion.py\, a standalone QLoRA fine-tuning script to train modern models (like Qwen2.5) on old laptops.

## What Is Planned Next
- **Live Chaos Tests:** Validate system availability during injected faults using the live Docker stack.
- **Third-Party Pentest:** Execute external security validation.
- **Geofence & Kill-Switch Rehearsal:** Ensure physical network constraints work flawlessly.
- **Pilot Deployment:** Present the finalized system to the pilot partner.
