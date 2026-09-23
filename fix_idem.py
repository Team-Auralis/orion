import re

with open('apps/api/main.py', 'r') as f:
    content = f.read()

content = content.replace('''        if namespaced_key:
            cached = db.query(IdempotencyKey).filter(IdempotencyKey.key == namespaced_key).first()
            if cached:
                return json.loads(cached.response_body)''',
'''        if namespaced_key:
            try:
                cached = db.query(IdempotencyKey).filter(IdempotencyKey.key == namespaced_key).first()
                if cached:
                    return json.loads(cached.response_body)
            except Exception as ex:
                print(f"Idempotency cache lookup error: {ex}")
                pass''')

with open('apps/api/main.py', 'w') as f:
    f.write(content)
