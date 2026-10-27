"""Make generated report paths portable without modifying source snapshots."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    prefixes = {str(ROOT): '<ARTIFACT_ROOT>'}
    for environment in ROOT.glob('.venv-*'):
        resolved = environment.resolve()
        if resolved.parent != ROOT:
            prefixes[str(resolved.parent)] = '<DEPENDENCY_ROOT>'
    for path in (ROOT / 'artifacts').rglob('*'):
        if (not path.is_file() or path.suffix not in {'.json', '.xml'}
                or 'sources' in path.parts or 'reproduction-logs' in path.parts):
            continue
        original = path.read_text()
        normalized = original
        for prefix, replacement in sorted(prefixes.items(), key=lambda pair: -len(pair[0])):
            normalized = normalized.replace(prefix, replacement)
        if normalized != original:
            path.write_text(normalized)


if __name__ == '__main__':
    main()
