import hashlib
import json
from pathlib import Path

b25 = Path('data/user/experiments/xxql2501_best_env_10layer_20260825')
b26 = Path('data/user/experiments/xxql2601_best_env_10layer_20260825')

# 25SP
lines_25 = [
    '$BATCH(TOMATO)',
    '!',
    '@FILEX                                                                                        TRTNO     RP     SQ     OP     CO'
]
for trno in [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]:
    lines_25.append(f'XXQL2501.TMX                                                                                   {trno:>2}      1      0      0      0')
(b25 / 'DSSBatch.v48').write_text('\n'.join(lines_25) + '\n', encoding='utf-8')

# 26SP
lines_26 = [
    '$BATCH(TOMATO)',
    '!',
    '@FILEX                                                                                        TRTNO     RP     SQ     OP     CO'
]
for trno in range(1, 13):
    lines_26.append(f'XXQL2601.TMX                                                                                   {trno:>2}      1      0      0      0')
(b26 / 'DSSBatch.v48').write_text('\n'.join(lines_26) + '\n', encoding='utf-8')

# Update manifests
for b in [b25, b26]:
    manifest_path = b / 'input_manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    for entry in manifest['files']:
        fname = entry.get('name')
        fpath = b / fname
        if fpath.exists() and fpath.is_file():
            entry['sha256'] = hashlib.sha256(fpath.read_bytes()).hexdigest()
            entry['bytes'] = fpath.stat().st_size
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
print('Successfully fixed DSSBatch.v48 with exact column widths!')
