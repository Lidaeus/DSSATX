import json, hashlib, os
d = json.load(open(r'D:\Tomato_Cal\subprojects\critical_n\reports\n_v4_lai_20261103\bin\r4\build_receipt.json'))
root = r'D:\Tomato_Cal_worktrees\dssat4864-rootn-T2-20261112'
sep = chr(92)
n = 0
for k, want in d['source_hashes'].items():
    p = os.path.join(root, *k.split(sep))
    if not os.path.isfile(p):
        print(k, 'MISSING'); continue
    got = hashlib.sha256(open(p, 'rb').read()).hexdigest()
    n += 1
    if got != want:
        print('DIFF:', k, 'receipt', want[:12], 'committed', got[:12])
print('checked', n, 'files; source_diff =', json.dumps(d.get('source_diff'))[:300])
