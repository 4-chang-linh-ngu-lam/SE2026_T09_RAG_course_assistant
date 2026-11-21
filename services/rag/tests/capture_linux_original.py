"""Capture Linux golden from verified pre-fix IDP ZIP and untouched Parser."""
import hashlib
import json
import sys
import tempfile
import zipfile
from pathlib import Path

root = Path('/work')
hashes = json.loads((root / 'tests/golden/source.json').read_text())
with tempfile.TemporaryDirectory() as temporary:
    original = Path(temporary)
    with zipfile.ZipFile('/baseline-idp.zip') as archive:
        for entry in archive.namelist():
            if not entry.endswith('.py'):
                continue
            relative = 'idp/' + entry.split('idp/', 1)[1]
            payload = archive.read(entry)
            assert hashlib.sha256(payload).hexdigest() == hashes[relative], relative
            destination = original / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
    for relative, digest in hashes.items():
        if relative.startswith('parser/'):
            assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == digest
    sys.path[:0] = [str(original), str(root), str(root / 'tests')]
    from test_phase0 import snapshot
    expected = {}
    cases = json.loads((root / 'tests/golden/expected.json').read_text())
    cases.update({'fast:scan.pdf': None, 'fast:vietnamese.pdf': None, 'fallback:scan.pdf': None})
    for key in cases:
        kind, filename = key.split(':')
        with tempfile.TemporaryDirectory() as output:
            expected[key] = snapshot(root / 'tests/fixtures/generated' / filename, Path(output), kind)
    assert all('error_type' not in expected[k] for k in ('fast:scan.pdf', 'fast:vietnamese.pdf', 'fallback:scan.pdf'))
    Path('/delivery/linux-original.json').write_text(json.dumps(expected, ensure_ascii=False, indent=2))
    Path('/delivery/linux-original-provenance.json').write_text(json.dumps({
        'method': 'original ZIP hash-checked against pre-fix source.json; Parser unchanged',
        'source_hashes': hashes,
    }, indent=2))
