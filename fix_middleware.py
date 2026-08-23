import re

with open('apps/api/main.py', 'r') as f:
    content = f.read()

content = content.replace('from slowapi import Limiter, _rate_limit_exceeded_handler',
'from slowapi import Limiter, _rate_limit_exceeded_handler\nfrom slowapi.middleware import SlowAPIMiddleware')

content = content.replace('app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)',
'app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)\napp.add_middleware(SlowAPIMiddleware)')

with open('apps/api/main.py', 'w') as f:
    f.write(content)
