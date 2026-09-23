# Probe real symbols only
import re
cli = open(r'D:\orion\orion_money\orion\cli.py', encoding='utf-8').read().splitlines()
print('== cli.py: every _summary / ledger. / summary usage ==')
for i, ln in enumerate(cli, 1):
    if re.search(r'_summary|ledger\.|summary\(', ln):
        print(i, ln.strip()[:100])
print()
import orion.ledger as L
print('ledger has summary callable:', callable(getattr(L, 'summary', None)))
import orion.memory as M
print('memory defines MemoryKind:', hasattr(M, 'MemoryKind'))
if hasattr(M, 'MemoryKind'):
    print('  members:', [x.value for x in M.MemoryKind])
