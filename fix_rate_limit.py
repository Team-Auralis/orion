import re

with open('apps/api/main.py', 'r') as f:
    content = f.read()

content = content.replace('''def get_real_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"''',
'''def get_real_ip(request: Request) -> str:
    # Strictly trust X-Real-IP from Nginx edge proxy
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "127.0.0.1"''')

with open('apps/api/main.py', 'w') as f:
    f.write(content)
