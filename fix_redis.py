
with open("docker-compose.yml", "r", encoding="utf-8") as f:
    text = f.read()
import re
text = text.replace("6379\\\"", "6379\"").replace("\\\"6379", "\"6379")
with open("docker-compose.yml", "w", encoding="utf-8") as f:
    f.write(text)
