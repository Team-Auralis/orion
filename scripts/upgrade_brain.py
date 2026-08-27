import os
print("=== UPGRADING ORION COGNITIVE CORE ===")
print("Downloading Qwen2.5-0.5B-Instruct...")
print("This is a modern instruction-tuned model, replacing the base GPT-2 model.")

try:
    from transformers import AutoModelForCausalLM, AutoTokenizer
    
    save_path = os.path.join(os.getcwd(), "models", "qwen_instruct")
    
    tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-0.5B-Instruct")
    model = AutoModelForCausalLM.from_pretrained("Qwen/Qwen2.5-0.5B-Instruct")
    
    tokenizer.save_pretrained(save_path)
    model.save_pretrained(save_path)
    
    print(f"\n[SUCCESS] Modern Instruct Model saved to {save_path}")
    print("The TUI will now automatically detect and use this upgraded brain.")
except Exception as e:
    print(f"[ERROR] {e}")
