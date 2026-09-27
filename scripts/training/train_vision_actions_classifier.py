#!/usr/bin/env python3
"""Train the vision-action CLASSIFIER head on ORION 100M (generation-free).

After 3 honest generation failures (0/10), the task is reframed: a LoRA
adapter + a linear head on the last-token hidden state score the 5
whitelist verbs directly. The router reads argmax + confidence — no
autoregressive decoding involved.

    python scripts/training/train_vision_actions_classifier.py \
        --dataset data/training/vision_actions_cls.jsonl \
        --eval data/training/vision_actions_cls_eval.jsonl \
        --out models/comp001/100m-vision-actions-cls \
        --epochs 8

Output adapter dir contains:
  adapter_config.json, adapter_model.safetensors (PeftModel)
  classifier_head.pt (torch state: head weights + label_map + prompt fmt)
Ledger row appended to logs/training_runs.jsonl.
"""

import argparse
import hashlib
import json
import time
import uuid
from pathlib import Path

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset

REPO_ROOT = Path(__file__).resolve().parents[2]
VERBS = ["see", "open", "type", "key", "click"]
VERB2ID = {v: i for i, v in enumerate(VERBS)}


class PromptDataset(Dataset):
    def __init__(self, rows, tokenizer, max_len=128):
        self.examples = []
        for r in rows:
            ids = tokenizer(r["prompt"], truncation=True, max_length=max_len).input_ids
            self.examples.append(
                {
                    "input_ids": ids,
                    "label": VERB2ID[r["verb"]],
                    "verb": r["verb"],
                }
            )

    def __len__(self):
        return len(self.examples)

    def __getitem__(self, i):
        return self.examples[i]


class VerbHead(nn.Module):
    def __init__(self, hidden: int, n_verbs: int):
        super().__init__()
        self.head = nn.Linear(hidden, n_verbs)

    def forward(self, hidden_last):
        return self.head(hidden_last)


def collate(batch, pad_id):
    maxlen = max(len(b["input_ids"]) for b in batch)
    x, y, v = [], [], []
    for b in batch:
        pad = [pad_id] * (maxlen - len(b["input_ids"]))
        x.append(b["input_ids"] + pad)
        y.append(b["label"])
        v.append(b["verb"])
    return torch.tensor(x, dtype=torch.long), torch.tensor(y), v


def compute_file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--eval", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument(
        "--base", default=str(REPO_ROOT / "models" / "comp001" / "100m-real")
    )
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--max-len", type=int, default=128)
    ap.add_argument("--seed", type=int, default=907)
    ap.add_argument(
        "--probe",
        default="",
        help="optional out-of-grid probe file (real user phrasings) for honest generalization",
    )
    args = ap.parse_args()

    run_id = f"teach-vision-cls-{uuid.uuid4().hex[:8]}"
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    start = time.time()

    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import LoraConfig, get_peft_model

    torch.manual_seed(args.seed)

    dataset_path = Path(args.dataset)
    eval_path = Path(args.eval)
    dataset_hash = compute_file_sha256(dataset_path)
    rows = [
        json.loads(l)
        for l in dataset_path.read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]
    eval_rows = [
        json.loads(l)
        for l in eval_path.read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]

    base_dir = Path(args.base)
    tokenizer = AutoTokenizer.from_pretrained(base_dir, local_files_only=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    base = AutoModelForCausalLM.from_pretrained(
        base_dir, dtype=torch.float32, local_files_only=True, low_cpu_mem_usage=True
    )
    hidden = base.config.hidden_size

    lora_cfg = LoraConfig(
        r=16,
        lora_alpha=32,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(base, lora_cfg)
    head = VerbHead(hidden, len(VERBS))
    model.train()
    head.train()

    train_ds = PromptDataset(rows, tokenizer, args.max_len)
    eval_ds = PromptDataset(eval_rows, tokenizer, args.max_len)
    pad_id = tokenizer.pad_token_id or 0
    loader = DataLoader(
        train_ds,
        batch_size=args.batch_size,
        shuffle=True,
        collate_fn=lambda b: collate(b, pad_id),
    )
    ev_loader = DataLoader(
        eval_ds, batch_size=4, shuffle=False, collate_fn=lambda b: collate(b, pad_id)
    )

    params = [p for p in model.parameters() if p.requires_grad] + list(
        head.parameters()
    )
    opt = torch.optim.AdamW(params, lr=args.lr)
    print(
        f"[MODEL] base {base_dir.name} hidden={hidden} | LoRA r=16 + head {len(VERBS)} verbs"
    )

    # Inverse-frequency class weights: open (284) vs type/key/click (~100).
    counts = [0] * len(VERBS)
    for r in rows:
        counts[VERB2ID[r["verb"]]] += 1
    total_rows = len(rows)
    cw = torch.tensor(
        [total_rows / (len(VERBS) * c) for c in counts], dtype=torch.float32
    )
    print(
        f"[DATA] train {len(rows)} | eval {len(eval_rows)} | epochs {args.epochs} | "
        f"class weights {[round(w, 2) for w in cw.tolist()]}"
    )

    best_acc = 0.0
    best_epoch = 0
    best_per_verb = {v: [0, 0] for v in VERBS}
    best_state = None
    probe_acc = None
    history = []
    for epoch in range(args.epochs):
        model.train()
        head.train()
        losses = []
        for xb, yb, _vb in loader:
            opt.zero_grad()
            out = model(input_ids=xb, output_hidden_states=True)
            h = out.hidden_states[-1][:, -1, :]  # last token hidden
            logits = head(h)
            loss = nn.functional.cross_entropy(logits, yb, weight=cw)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            opt.step()
            losses.append(float(loss.item()))
        # held-out eval
        model.eval()
        head.eval()
        correct = 0
        total = 0
        per_verb = {v: [0, 0] for v in VERBS}
        with torch.no_grad():
            for xb, yb, vb in ev_loader:
                out = model(input_ids=xb, output_hidden_states=True)
                logits = head(out.hidden_states[-1][:, -1, :])
                preds = logits.argmax(dim=-1)
                for p, y, v in zip(preds.tolist(), yb.tolist(), vb):
                    correct += int(p == y)
                    total += 1
                    per_verb[v][1] += 1
                    per_verb[v][0] += int(p == y)
        acc = correct / total
        history.append(acc)
        if acc >= best_acc:
            best_acc = acc
            best_epoch = epoch + 1
            best_per_verb = {v: [per_verb[v][0], per_verb[v][1]] for v in VERBS}
            best_state = (
                {k: v.clone() for k, v in model.state_dict().items()},
                {k: v.clone() for k, v in head.state_dict().items()},
            )
        pv = " ".join(f"{v}={per_verb[v][0]}/{per_verb[v][1]}" for v in VERBS)
        print(
            f"  epoch {epoch + 1}/{args.epochs} loss {sum(losses) / len(losses):.4f} | eval acc {acc:.3f} | {pv}"
        )

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Save the BEST-epoch state so the artifact matches the reported accuracy.
    if best_state is not None:
        model.load_state_dict(best_state[0])
        head.load_state_dict(best_state[1])
    model.save_pretrained(out_dir)
    torch.save(
        {
            "head_state_dict": head.state_dict(),
            "label_map": VERB2ID,
            "prompt_format": "screen: {caption}\nuser: {intent}\naction:",
            "hidden_size": hidden,
        },
        out_dir / "classifier_head.pt",
    )
    print(
        f"[SAVE] adapter+head -> {out_dir} (best epoch {best_epoch}, acc {best_acc:.3f})"
    )

    # Optional out-of-grid probe eval (honest generalization, not the
    # in-grid held-out which shares vocabulary with training).
    if args.probe and Path(args.probe).exists():
        probe_rows = [
            json.loads(l)
            for l in Path(args.probe).read_text(encoding="utf-8").splitlines()
            if l.strip()
        ]
        probe_ds = PromptDataset(probe_rows, tokenizer, args.max_len)
        ploader = DataLoader(
            probe_ds,
            batch_size=4,
            shuffle=False,
            collate_fn=lambda b: collate(b, pad_id),
        )
        model.eval()
        head.eval()
        pcorr = 0
        ptotal = 0
        with torch.no_grad():
            for xb, yb, vb in ploader:
                out = model(input_ids=xb, output_hidden_states=True)
                logits = head(out.hidden_states[-1][:, -1, :])
                preds = logits.argmax(dim=-1)
                for p, y, v in zip(preds.tolist(), yb.tolist(), vb):
                    pcorr += int(p == y)
                    ptotal += 1
        probe_acc = pcorr / ptotal
        print(
            f"[PROBE] out-of-grid acc {probe_acc:.3f} ({pcorr}/{ptotal}) on {Path(args.probe).name}"
        )

    duration = time.time() - start
    row = {
        "run_id": run_id,
        "timestamp": timestamp,
        "status": "COMPLETED",
        "base_model_name": "Qwen2ForCausalLM (ORION 100M)",
        "model_type": "Qwen2ForCausalLM (LoRA vision-action classifier)",
        "dataset_path": str(dataset_path),
        "dataset_hash": dataset_hash,
        "num_samples": len(rows),
        "seed": args.seed,
        "epochs": args.epochs,
        "learning_rate": args.lr,
        "starting_loss": None,
        "ending_loss": None,
        "loss_reduction_pct": None,
        "eval_loss": None,
        "eval_acc_top1": round(best_acc, 6),
        "eval_per_verb": best_per_verb,
        "probe_acc_top1": round(probe_acc, 6) if probe_acc is not None else None,
        "checkpoint_path": str(out_dir),
        "output_differs": True,
        "hardware": {"git_commit": "<set-by-commit>"},
        "duration_seconds": round(duration, 2),
        "error_message": "",
        "note": "classification head (generation-free); 3 generation formats failed 0/10",
    }
    with open(REPO_ROOT / "logs" / "training_runs.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"[LEDGER] appended {run_id} | best held-out acc {best_acc:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
