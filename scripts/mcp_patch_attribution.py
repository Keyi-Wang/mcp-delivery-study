"""Paired patch-only/reversion interventions; real local stdio and HTTP, no LLM."""
import ast
import difflib
import hashlib
import importlib.util
import json
from pathlib import Path

from mcp_agno_http_capture import execute
from mcp_visibility_probe import load_source

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/mcp-paper-evidence-20261026'


def main():
    sources = ROOT / 'artifacts/empirical-directions-20261026/sources'
    before = (sources / 'before/mcp.py').read_text()
    after = (sources / 'after/mcp.py').read_text()
    block = ('            if not response_str.strip():\n'
             '                response_str = _serialize_structured_content(result) or ""\n\n')
    anchor = '            return ToolResult(\n                content=response_str.strip(),'
    node = next(n for n in ast.parse(after).body
                if isinstance(n, ast.FunctionDef) and n.name == '_serialize_structured_content')
    helper = ast.get_source_segment(after, node)
    assert block not in before and after.count(block) == 1
    assert before.count(anchor) == 1 and '_serialize_structured_content' not in before
    added = before.replace(anchor, block + anchor) + '\n\n' + helper + '\n'
    reverted = after.replace(block, '').replace(helper + '\n\n\n', '')
    assert '_serialize_structured_content' not in reverted
    # Unrelated toolkit-naming changes remain only in the later-source arm.
    assert 'def get_default_toolkit_name' not in added
    assert 'def get_default_toolkit_name' in reverted
    generated = OUT / 'patch-interventions'
    generated.mkdir(exist_ok=True)
    modules = {'before': load_source('before'), 'after': load_source('after')}
    manifest = []
    for name, original, modified in [('before_plus_fallback', before, added),
                                      ('after_minus_fallback', after, reverted)]:
        path = generated / (name + '.py')
        path.write_text(modified)
        patch = ''.join(difflib.unified_diff(original.splitlines(True), modified.splitlines(True),
                                           fromfile=name + ':base', tofile=name + ':intervention'))
        path.with_suffix('.diff').write_text(patch)
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules[name] = module
        manifest.append({'arm': name, 'path': str(path.relative_to(ROOT)),
                         'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                         'historical_release': False})
    rows = []
    for name, module in modules.items():
        for fixture in ['structured_only', 'summary_plus_data', 'file_plus_metadata', 'equivalent_dual']:
            rows.append(execute(name, fixture, 'STATE_CAUSAL_4P', mcp_stdio=True,
                                adapter_module=module, enforce_original_expectations=False))
    index = {(r['adapter'], r['fixture']): r for r in rows}
    comparisons = []
    for fixture in ['structured_only', 'summary_plus_data', 'file_plus_metadata', 'equivalent_dual']:
        body = lambda arm: index[arm, fixture]['actual_http_requests'][1]['body']
        item = {'fixture': fixture,
                'patch_only_matches_after_entire_request': body('before_plus_fallback') == body('after'),
                'reverted_matches_before_entire_request': body('after_minus_fallback') == body('before'),
                'before_matches_after_entire_request': body('before') == body('after'),
                'retained_by_arm': {arm: index[arm, fixture]['answer_in_actual_followup_tool_message'] for arm in modules}}
        assert item['patch_only_matches_after_entire_request'] and item['reverted_matches_before_entire_request']
        assert item['before_matches_after_entire_request'] == (fixture != 'structured_only')
        comparisons.append(item)
    report = {'protocol': 'research/mcp-guidance-amendment-20261026.json',
              'generated_sources': manifest, 'rows': rows, 'comparisons': comparisons,
              'runs': len(rows), 'http_requests': sum(len(r['actual_http_requests']) for r in rows),
              'paid_api_calls': 0,
              'limits': ['Two experimental source interventions, not two extra historical releases or incidents.',
                         'Necessary/sufficient attribution only for these fixtures in the fixed dependency environment.',
                         'Real stdio and provider HTTP; scripted receiver is not an LLM.']}
    (OUT / 'patch-attribution.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'runs': len(rows), 'comparisons': comparisons}, indent=2))


if __name__ == '__main__':
    main()
