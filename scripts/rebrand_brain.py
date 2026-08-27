import os
import sys

try:
    import onnx
except ImportError:
    print("Please install onnx via 'pip install onnx'")
    sys.exit(1)

model_path = os.path.join(os.getcwd(), 'models', 'orion_brain.onnx')
if not os.path.exists(model_path):
    print(f"Model not found at {model_path}")
    sys.exit(1)

print(f"Loading {model_path} for rebranding...")
model = onnx.load(model_path)

# Strip out original metadata and inject ORION properties
model.producer_name = "Team Auralis (ORION)"
model.producer_version = "1.0.0"
model.domain = "ai.orion.local"
model.model_version = 1
model.doc_string = "Proprietary offline inference engine for the ORION Terminal Environment."

# Rename the graph
model.graph.name = "ORION-Cognitive-Core-v1"

print("Saving rebranded model...")
onnx.save(model, model_path)
print("[SUCCESS] Model metadata successfully overwritten. The raw ONNX file now identifies as ORION-Cognitive-Core.")
