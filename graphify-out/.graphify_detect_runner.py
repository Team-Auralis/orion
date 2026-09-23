from graphify.detect import detect
from pathlib import Path
import json
result = detect(Path('.'))
Path('graphify-out/.graphify_detect.json').write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
Path('graphify-out/.graphify_detect.done').write_text('done', encoding='utf-8')
