import os
import sys

print("=== ORION Local AI Fine-Tuning Pipeline ===")
print("Checking for required dependencies...")

try:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments, Trainer
    from peft import LoraConfig, get_peft_model
    from datasets import Dataset
except ImportError:
    print("\n[!] Missing training libraries. Run this first:")
    print("pip install torch transformers peft datasets")
    sys.exit(1)

# Ponytail: We use Qwen2.5-0.5B. It is ungated, tiny (500M params fits in 2GB RAM), 
# and natively supports up to 32k context window out of the box (unlike GPT-2).
MODEL_NAME = "Qwen/Qwen2.5-0.5B"
OUTPUT_DIR = "./models/orion_custom_lora"

print(f"\n1. Loading Tokenizer for {MODEL_NAME}...")
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token

print(f"2. Loading Base Model (This may take a minute if downloading)...")
# We load it in bfloat16 or float32 depending on hardware, using device_map to auto-allocate
device = "cuda" if torch.cuda.is_available() else "cpu"
model = AutoModelForCausalLM.from_pretrained(MODEL_NAME, torch_dtype=torch.float32).to(device)

print("\n3. Applying LoRA (Low-Rank Adaptation)...")
# LoRA freezes the main 500M parameters and only trains a tiny 1-2M parameter adapter layer.
# This is how you train on an old laptop without exploding your RAM.
lora_config = LoraConfig(
    r=8, 
    lora_alpha=16, 
    target_modules=["q_proj", "v_proj"], 
    lora_dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM"
)
model = get_peft_model(model, lora_config)
model.print_trainable_parameters()

print("\n4. Generating Custom ORION Training Data...")
# This is a sample dataset. You can replace this with your actual proprietary code or docs.
training_data = {
    "text": [
        "User: What is the core directive of ORION?\nAURA: The core directive is to operate locally, maintain the terminal environment, and protect the codebase without relying on external cloud APIs.",
        "User: Explain the geofence protocol.\nAURA: The ORION geofence protocol ensures that no proprietary source code leaves the host machine. It physically blocks outbound HTTP requests during active scanning.",
        "User: Who created you?\nAURA: I am ORION-Cognitive-Core, an offline AI system designed for the Auralis infrastructure.",
        "User: What is your maximum context window?\nAURA: Thanks to my modern architecture, I can process up to 32,000 tokens of context, allowing me to ingest massive code files."
    ]
}

def tokenize_function(examples):
    return tokenizer(examples["text"], padding="max_length", truncation=True, max_length=128)

dataset = Dataset.from_dict(training_data).map(tokenize_function, batched=True)
dataset.set_format(type="torch", columns=["input_ids", "attention_mask"])
# For causal LM, labels are the same as input_ids
dataset = dataset.map(lambda x: {"labels": x["input_ids"]})

print("\n5. Starting Training Loop...")
training_args = TrainingArguments(
    output_dir=OUTPUT_DIR,
    per_device_train_batch_size=1,
    gradient_accumulation_steps=4,
    learning_rate=2e-4,
    num_train_epochs=3, # Bump this to 50 for actual learning
    logging_steps=1,
    save_steps=10,
    optim="adamw_torch",
    remove_unused_columns=False,
    report_to="none" # Disable wandb logging
)

trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=dataset,
)

trainer.train()

print(f"\n6. Saving Custom ORION LoRA Adapter to {OUTPUT_DIR}...")
model.save_pretrained(OUTPUT_DIR)
tokenizer.save_pretrained(OUTPUT_DIR)

print("\n[SUCCESS] Your fully custom, laptop-trained model is ready!")
