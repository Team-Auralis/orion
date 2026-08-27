import os
import shutil
from huggingface_hub import hf_hub_download

print("Downloading local ONNX brain and tokenizer (this may take a minute)...")
try:
    # optimum/gpt2 contains standard ONNX exports for GPT2
    model_path = hf_hub_download(repo_id="optimum/gpt2", filename="decoder_model.onnx")
    tokenizer_path = hf_hub_download(repo_id="optimum/gpt2", filename="tokenizer.json")
    
    target_dir = os.path.join(os.getcwd(), "models")
    os.makedirs(target_dir, exist_ok=True)
    
    target_model_path = os.path.join(target_dir, "orion_brain.onnx")
    target_tokenizer_path = os.path.join(target_dir, "tokenizer.json")
    
    print(f"Copying model to {target_model_path}...")
    shutil.copy(model_path, target_model_path)
    print(f"Copying tokenizer to {target_tokenizer_path}...")
    shutil.copy(tokenizer_path, target_tokenizer_path)
    
    print("\n[SUCCESS] Local brain installed! You can now run '.\orion' to start the offline AI.")
except Exception as e:
    print(f"\n[ERROR] Failed to download or copy the model: {e}")
