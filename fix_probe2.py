import re

with open('scripts/security_probe.py', 'r') as f:
    content = f.read()

content = content.replace('''except requests.exceptions.ConnectionError:
        print(f"\\n[-] Could not connect to target {base_url}")
        sys.exit(1)''',
'''except requests.exceptions.ConnectionError as e:
        print(f"\\n[-] Could not connect to target {base_url}")
        print(e)
        sys.exit(1)''')

with open('scripts/security_probe.py', 'w') as f:
    f.write(content)
