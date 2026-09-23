import re

with open('apps/api/main.py', 'r') as f:
    content = f.read()

content = content.replace('class Config:\n        allow_inf_nan = False', 'model_config = {"allow_inf_nan": False}')
if 'model_config = {"allow_inf_nan": False}' not in content:
    print("Replace failed")

with open('apps/api/main.py', 'w') as f:
    f.write(content)
