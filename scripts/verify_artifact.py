"""Check the frozen release inventory before running experiments."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    manifest = json.loads((ROOT / 'MANIFEST.json').read_text())
    failed = []
    for item in manifest['files']:
        path = ROOT / item['path']
        if not path.is_file():
            failed.append(item['path'] + ': missing')
        elif hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            failed.append(item['path'] + ': changed')
    if failed:
        raise SystemExit('\n'.join(failed))
    print(f"Verified {len(manifest['files'])} files against MANIFEST.json")


if __name__ == '__main__':
    main()
