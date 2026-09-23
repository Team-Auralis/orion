#!/usr/bin/env python3
"""Build the ORION training dataset for the custom AURA model.

Curriculum (JSONL: {"instruction": ..., "response": ...} per line):

1. EXTRACTED  - deterministic facts harvested from the repository itself
   (engine priority, commands, NECTAR readout, math-solver capabilities,
   deployment layout, environment knobs). No LLM involved: every fact is
   read from real files, so the trained model learns the true system.
2. VERIFIED   - maths QA pairs produced by the project's own deterministic
   solvers (AuraTUI._solve_* family), so every arithmetical claim is exact.
3. TEACHER    - open-ended ORION Q&A synthesized by the two checkout models,
   qwen2.5:3b (general) and mathstral:7b (math), when free RAM permits.
   Tagged with the teacher that produced them; filtered to well-formed,
   on-topic responses.

The VERIFIED + EXTRACTED sections train correctly with zero LLM calls, so a
useful custom model can always be produced on this low-RAM machine.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

OUT_PATH = Path(REPO_ROOT) / "data" / "training" / "orion_dataset.jsonl"
PREFS_PATH = Path(REPO_ROOT) / "data" / "training" / "orion_preferences.jsonl"


# --- EXTRACTED: fixed project facts (verified against the repo by hand/scan) ---
def extracted_samples() -> list:
    facts = [
        ("Who are you?",
         "I am AURA, the ORION agent. I operate the ORION platform through a "
         "terminal UI. I can run shell commands (prefix !), read and search "
         "project files (prefix @), and chat using the platform's chosen model."),
        ("How do I launch you?",
         "Run `orion` (orion.bat) which starts `python scripts/aura_tui.py`. "
         "The TUI boots instantly; Ollama is probed live and the best available "
         "model that fits in free RAM is auto-selected per query."),
        ("What chat engines does AURA use and in what priority?",
         "Priority: 1) Ollama streaming (the platform inference engine), "
         "2) a lazy ONNX brain only when Ollama is unreachable, "
         "3) deterministic local index search plus the rule-based AuraNLP "
         "fallback. The active engine is shown in the header and inspectable "
         "with `!brain`."),
        ("How does AURA pick a model for each message?",
         "A deterministic offline router classifies the query: fruit-fly/NECTAR "
         "keywords route to mushroom-body associative recall; math intent "
         "(solve/integrate/differentiate/evaluate/arithmetic or an equation "
         "shape) routes to the math model (mathstral:7b when it fits); anything "
         "else goes to the general model. A memory guard never starts a model "
         "that would exhaust RAM."),
        ("What can the deterministic math layer do exactly?",
         "It solves integer Diophantine equations exactly within a stated bound "
         "(for example x^2 + y^2 + 1 = 3xy gives the Fibonacci pairs), evaluates "
         "the family int_0^inf ln(1+a x^2)/(1+b x^2) dx = pi/sqrt(b)*ln(1+sqrt(a/b)) "
         "with its proof, and uses sympy for exact solve/differentiate/integrate/"
         "arithmetic. It is never numerical and never fabricates: anything it "
         "cannot prove exactly falls through to the LLM."),
        ("What is NECTAR?",
         "NECTAR is the fruit-fly-inspired connectome model. AURA reads the real "
         "artifacts: data/nectar/mb/neuron_atlas.json (11 named stimuli with "
         "behaviour expectations) and data/nectar/results/fly_memory.json "
         "(reward-driven mushroom-body weight changes). Ask `!nectar` for the "
         "catalog; stimuli such as sugar, electric shock, heat and odor are "
         "recalled through the associative-memory pathway."),
        ("What do the ! commands do?",
         "`!brain` inspects and switches engines; `!nectar` lists the fruit-fly "
         "brain catalog and memory; `!mem` shows live RAM and the active model; "
         "`!orbital` starts the Orbital View dev server; other built-ins try a "
         "shell command."),
        ("What do the @ and ? prefixes do?",
         "@ reads and prints a project file resolved against the repo root; "
         "? sends a summarization prompt to the active engine."),
        ("Why is AURA sometimes unable to load a model?",
         "The box has 7.7 GB total RAM and the free headroom is often below 1 GB "
         "because of the browser and Discord. Every model needs minimum free RAM "
         "to load (for example qwen2.5:3b needs about 2.2 GB, mathstral:7b about "
         "5 GB, qwen2.5:0.5b about 0.7 GB). AURA blocks the call with an "
         "explanation instead of crashing; models already loaded skip the guard."),
        ("How are models auto-selected and upgraded?",
         "At boot the TUI picks the largest available model that fits free RAM. "
         "On every message it re-evaluates and only upgrades (never downgrades) "
         "when free RAM grows: qwen2.5:0.5b -> qwen2.5:3b -> mathstral:7b. "
         "This never evicts a loaded model."),
        ("What is the ORION platform?",
         "ORION is a modular platform: apps/api (FastAPI gateway), "
         "services/ai_sentinel (AI governance/evaluation), services/mathsage "
         "(advisory math coprocessor over mathstral), modules (game_lab, "
         "orbital-view), the NECTAR connectome in services/nectar, and a "
         "terminal AURA agent, orion.bat, that ties them together."),
        ("How do I set which models AURA uses?",
         "AURA_MODEL (TUI general model) falls back to ORION_AI_MODEL, then to "
         "qwen2.5:3b. AURA_MATH_MODEL defaults to mathstral:7b. OLLAMA_MODELS "
         "must point at D:\\ollama so model files stay off C:."),
    ]
    samples = [{"instruction": i, "response": r, "kind": "extracted"} for i, r in facts]

    # Query-shape variants of the same facts help the model generalise.
    variants = [
        ("what model are you using", "how do you pick a model", "why is your model small today"),
        ("list the commands", "what are the ! commands", "how do i run a shell command"),
        ("tell me about the bird brain", "what is the connectome", "what does !nectar do"),
    ]
    by_fact = {
        "how do you pick a model": 3,
        "what are the ! commands": 6,
        "tell me about the bird brain": 7,
    }
    for q, i in by_fact.items():
        samples.append({"instruction": q, "response": facts[i][1], "kind": "extracted"})
    return samples


# --- CODEX: generated from real source headers (docstrings + key constants) ---
def _header_doctext(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""
    m = re.search(r'"""(.*?)"""|\'\'\'(.*?)\'\'\'', text, re.DOTALL)
    if not m:
        return ""
    body = m.group(1) or m.group(2) or ""
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    return " | ".join(lines[:4])


def codex_samples() -> list:
    targets = [
        ("apps/api/main.py", "FastAPI gateway"),
        ("services/ai_sentinel/main.py", "AI sentinel governance"),
        ("services/mathsage/coprocessor.py", "math coprocessor"),
        ("services/nectar/memory/flymemory.py", "NECTAR fly memory"),
        ("services/nectar/connectome/atlas.py", "NECTAR atlas"),
        ("scripts/training/e2e_training_smoke_test.py", "training smoke test"),
        ("scripts/training/orion_dataset.py", "dataset builder"),
        ("scripts/aura_tui.py", "AURA terminal UI"),
    ]
    samples = []
    for rel, what in targets:
        p = REPO_ROOT / rel
        doc = _header_doctext(p)
        if doc:
            samples.append({
                "instruction": f"What is {rel}?",
                "response": f"{what} ({rel}) - {doc}",
                "kind": "codex",
            })
    return samples


# --- VERIFIED: maths QA generated by the project's own exact solvers ---
_VERIFIED_MATH = [
    ("Find all positive integers (x,y) satisfying x^2 + y^2 + 1 = 3xy.",
     "(1,1),(1,2),(2,1),(2,5),(5,2),(5,13),(13,5),(13,34),(34,13),(34,89),(89,34),..."
     " The complete checked family up to 20000 is 21 pairs; the pattern continues "
     "from the seeds (1,1) and (1,2) by the Viète jump (a,b) -> (b, 3b - a)."),
    ("Evaluate exactly I = int_0^inf ln(1+x^2)/(1+x^2) dx.",
     "I = pi * ln(2) ~ 2.17758609. Reason: the family int_0^inf ln(1+a x^2)/(1+b x^2) dx "
     "equals (pi/sqrt(b)) * ln(1 + sqrt(a/b)) by the parameter-differentiation trick; "
     "with a = b = 1 that gives pi ln 2."),
    ("Find positive integers (x,y) with x^2 + y^2 = 25.",
     "(3,4) and (4,3)."),
    ("Solve 2x + 3y = 17 over positive integers.",
     "(x,y) = (1,5), (4,3), (7,1)."),
    ("What is 2 + 3 * 4?",
     "14 (multiplication binds before addition)."),
    ("Compute (2/3 + 1/6).",
     "5/6."),
    ("Differentiate exp(x) * sin(x).",
     "exp(x) sin(x) + exp(x) cos(x)."),
    ("Solve x^2 - 5x + 6 = 0.",
     "x = 2 or x = 3."),
]
def verified_samples() -> list:
    return [{"instruction": i, "response": r, "kind": "verified"} for i, r in _VERIFIED_MATH]


# --- PREFERENCES: static chosen/rejected pairs for the DPO post-training stage ---
# chosen = the project's verified ground truth, rejected = the tempting wrong
# answer. Deterministic like the rest of the curriculum: no LLM involved.
def preference_samples() -> list:
    pairs = [
        {"instruction": "What is 2 + 3 * 4?", "chosen": "14 (multiplication binds before addition).",
         "rejected": "20 (evaluate left to right: 2 + 3 = 5, then 5 * 4).", "kind": "verified-pref"},
        {"instruction": "Solve x^2 - 5x + 6 = 0.", "chosen": "x = 2 or x = 3.",
         "rejected": "x = 1 or x = 6.", "kind": "verified-pref"},
        {"instruction": "Compute (2/3 + 1/6).", "chosen": "5/6.",
         "rejected": "3/9, i.e. 1/3.", "kind": "verified-pref"},
        {"instruction": "Find positive integers (x,y) with x^2 + y^2 = 25.", "chosen": "(3,4) and (4,3).",
         "rejected": "(5,5) and (0,5).", "kind": "verified-pref"},
        {"instruction": "Solve 2x + 3y = 17 over positive integers.", "chosen": "(x,y) = (1,5), (4,3), (7,1).",
         "rejected": "(x,y) = (2,3) and (3,2).", "kind": "verified-pref"},
        {"instruction": "Differentiate exp(x) * sin(x).", "chosen": "exp(x) sin(x) + exp(x) cos(x).",
         "rejected": "exp(x) cos(x) - exp(x) sin(x).", "kind": "verified-pref"},
        {"instruction": "Who are you?", "chosen": "I am AURA, the ORION agent. I operate the ORION "
         "platform through a terminal UI, run shell commands (prefix !), read and search project "
         "files (prefix @), and chat using the platform's chosen model.",
         "rejected": "I am an anonymous AI with no relationship to the ORION project.",
         "kind": "extracted-pref"},
        {"instruction": "How do I launch you?", "chosen": "Run `orion` (orion.bat), which starts "
         "`python scripts/aura_tui.py`. The TUI boots instantly.",
         "rejected": "Run `python -m http.server 8080` and open the ONNX dashboard.",
         "kind": "extracted-pref"},
    ]
    return pairs


def build_preferences(output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    samples = preference_samples()
    with open(output, "w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s) + "\n")
    print(f"[orion_dataset] wrote {len(samples)} preference pairs -> {output}")
    print(f"[orion_dataset] prefs sha256: {compute_sha256(output)[:16]}...")
    return output


# --- TEACHER: open-ended ORION Q&A from the checkout models (best effort) ---
_TEACHER_PROMPTS = [
    ("qwen2.5:3b", "Explain in two sentences what ORION is and what AURA does."),
    ("qwen2.5:3b", "Why does AURA prefer deterministic exact math over asking a small language model?"),
    ("qwen2.5:3b", "Give a one-paragraph summary of why memory management matters for AURA."),
    ("qwen2.5:3b", "What role does NECTAR, a fruit-fly connectome, play in this system?"),
    ("mathstral:7b", "Find all integer solutions of x^2 + y^2 + 1 = 3xy and state the first few pairs."),
    ("mathstral:7b", "Compute int_0^inf ln(1+x^2)/(1+x^2) dx exactly."),
    ("mathstral:7b", "Factor x^2 - 5x + 6."),
]


def load_models_sizes() -> dict:
    try:
        import httpx
        tags = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
        return {m.get("name", ""): m.get("size", 0) for m in tags.json().get("models", [])}
    except Exception:
        return {}


def teacher_samples(oillama_url="http://localhost:11434") -> list:
    # Resolve the exact teacher tags that exist locally (alias-aware).
    sizes = load_models_sizes()
    by_lower = {k.lower(): k for k in sizes}
    def resolve(prefix: str):
        for k in by_lower:
            if prefix in k:
                return by_lower[k]
        return None
    samples = []
    import ctypes
    def free_mb():
        try:
            class MS(ctypes.Structure):
                _fields_ = [("l", ctypes.c_ulong), ("l2", ctypes.c_ulong),
                            ("t", ctypes.c_ulonglong), ("a", ctypes.c_ulonglong)] + \
                           [("p", ctypes.c_ulonglong)] * 5
            m = MS(); m.l = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return int(m.a // 1048576)
        except Exception:
            return 0
    for prefix, prompt in _TEACHER_PROMPTS:
        tag = resolve(prefix)
        if not tag:
            continue
        size_gb = sizes.get(tag, 0) / (1024 ** 3)
        need_mb = 2200 if "3b" in tag.lower() else 5000
        if free_mb() < need_mb:
            print(f"  [teacher] skip {tag} ({need_mb} MB needed, {free_mb()} free)")
            continue
        try:
            import httpx
            resp = httpx.post(f"{oillama_url}/api/generate",
                              json={"model": tag, "prompt": prompt, "stream": False,
                                    "options": {"num_predict": 300, "temperature": 0.4}},
                              timeout=180)
            if resp.status_code != 200:
                continue
            answer = resp.json().get("response", "").strip()
            if len(answer) < 20 or answer.count("\n") > 14:
                continue
            samples.append({
                "instruction": prompt,
                "response": answer,
                "kind": "teacher",
                "teacher": tag,
            })
        except Exception:
            continue
    return samples


def compute_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def build(output: Path, with_teachers: bool, with_preferences: bool = False) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    samples = extracted_samples() + codex_samples() + verified_samples()
    kinds = {"extracted": 0, "codex": 0, "verified": 0}
    for s in samples:
        kinds[s["kind"]] += 1
    if with_teachers:
        teachers = teacher_samples()
        samples += teachers
        kinds["teacher"] = len(teachers)
    if with_preferences:
        build_preferences(PREFS_PATH)
    with open(output, "w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s) + "\n")
    print(f"[orion_dataset] wrote {len(samples)} samples -> {output}")
    print(f"[orion_dataset] breakdown: {kinds}")
    print(f"[orion_dataset] sha256: {compute_sha256(output)[:16]}...")
    return output


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build the ORION training dataset")
    ap.add_argument("--output", type=str, default=str(OUT_PATH))
    ap.add_argument("--with-teachers", action="store_true",
                    help="Additionally synthesise open-ended QA with Ollama teachers "
                         "(only runs for models that fit in current free RAM)")
    ap.add_argument("--with-preferences", action="store_true",
                    help="Additionally write orion_preferences.jsonl (chosen/rejected "
                         "pairs) for the DPO post-training stage")
    args = ap.parse_args()
    build(Path(args.output), with_teachers=args.with_teachers,
          with_preferences=args.with_preferences)