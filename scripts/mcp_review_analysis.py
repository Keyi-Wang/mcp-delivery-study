"""Task-level oracles and policy-only comparisons on captured native results."""
import ast
import copy
import hashlib
import inspect
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/mcp-review-revision-20261026'
sys.path.insert(0, str(OUT / 'sources/hermes'))
from tools import mcp_tool_handlers as handlers
from mcp.types import CallToolResult
from mcp_count_oracle import count_retained, observed_counts

def documents(value):
    if isinstance(value, (dict, list)):
        yield value
        for child in value.values() if isinstance(value, dict) else value:
            yield from documents(child)
    elif isinstance(value, str):
        decoder = json.JSONDecoder()
        for i, char in enumerate(value):
            if char in '{[':
                try:
                    decoded, _ = decoder.raw_decode(value[i:])
                except ValueError:
                    continue
                yield from documents(decoded)

def subset(expected, actual):
    if type(expected) is not type(actual):
        return False
    if isinstance(expected, dict):
        return all(k in actual and subset(v, actual[k]) for k, v in expected.items())
    if isinstance(expected, list):
        return len(expected) == len(actual) and all(subset(x, y) for x, y in zip(expected, actual))
    return expected == actual

def contains(output, expected):
    return any(subset(expected, obj) for obj in documents(output))

def handoff(output, tool):
    """Decide from delivered fields only, without the expected answer/state oracle."""
    records = [obj for obj in documents(output) if isinstance(obj, dict)]
    if tool == 'get_wan_status':
        facts = {(r['status'], r['wan_ip']) for r in records
                 if isinstance(r.get('status'), str) and isinstance(r.get('wan_ip'), str)}
        if len(facts) != 1:
            return 'request_missing_or_conflicting_evidence'
        status, _ = next(iter(facts))
        return ('send_public_ip_to_connectivity_review' if status == 'ok'
                else 'flag_wan_for_investigation')
    # The frozen workload has one configured SSID. Multiple/conflicting records
    # require a richer review policy and are not silently assigned an action.
    facts = {(r['name'], r['enabled']) for r in records
             if isinstance(r.get('name'), str) and type(r.get('enabled')) is bool}
    if len(facts) != 1:
        return 'request_missing_or_conflicting_evidence'
    _, enabled = next(iter(facts))
    return 'include_ssid_in_configuration_review' if enabled else 'mark_ssid_disabled'

def combined_renderer():
    source = inspect.getsource(handlers._render_call_tool_result)
    tree = ast.parse(source)
    function = tree.body[0]
    matches = [n for n in function.body if isinstance(n, ast.If) and
               ast.unparse(n.test) == 'structured is not None and usable_parts > 0']
    assert len(matches) == 1
    function.body.remove(matches[0])
    namespace = dict(handlers.__dict__)
    exec(compile(tree, '<single-branch-intervention>', 'exec'), namespace)
    (OUT / 'combination-intervention.py.txt').write_text(ast.unparse(tree) + '\n')
    return namespace['_render_call_tool_result']

combined = combined_renderer()

def render(result, strategy):
    obj = CallToolResult.model_validate(result)
    if strategy == 'combination':
        return combined(obj, 'review')
    if strategy == 'structured_priority' and result.get('structuredContent') is not None:
        # Only arbitration changes: native serialization, metadata and caps remain.
        obj = CallToolResult.model_validate(dict(result, content=[]))
    return handlers._render_call_tool_result(obj, 'review')

def main():
    live = json.loads((OUT / 'continuous-results.json').read_text())
    snapshot = json.loads((OUT / 'upstream-seed-snapshot.json').read_text())
    rows, count_controls = [], []
    for cell in live['cells']:
        expected = copy.deepcopy(next(r for r in snapshot['health'] if r['subsystem'] == 'wan')
                                 if cell['tool'] == 'get_wan_status' else snapshot['wlans'])
        secrets = ['correct-horse-battery-staple']  # upstream synthetic read-redaction fixture
        if isinstance(expected, list):
            for r in expected:
                r['x_passphrase'] = '[REDACTED]'
            if cell['state'] == 'perturbed':
                expected[0].update(name='Office-Review', enabled=False)
            required = [{k:r[k] for k in ['name', 'enabled']} for r in expected]
        else:
            if cell['state'] == 'perturbed':
                expected.update(status='warning', wan_ip='203.0.113.99')
            required = {k:expected[k] for k in ['status', 'wan_ip']}
        assert contains(cell['received'], expected), 'Producer did not deliver the expected source-derived data'
        strategies = ['native_full_text'] if cell['mode'] == 'full_text' else [
            'text_priority', 'structured_priority', 'combination']
        for strategy in strategies:
            output = render(cell['received'], strategy)
            if strategy in ('text_priority', 'native_full_text'):
                assert output == cell['handler_output']
            retained = contains(output, required)
            action = handoff(output, cell['tool'])
            rows.append({'tool': cell['tool'], 'state': cell['state'], 'strategy': strategy,
                         'required': required, 'output': output, 'required_facts_retained': retained,
                         'full_object_retained': contains(output, expected),
                         'forbidden_secrets_retained': [s for s in secrets if s in output],
                         'utf8_bytes': len(output.encode()), 'handoff_action': action})
            if cell['tool'] == 'list_wlans':
                n = len(expected)
                count_ok = count_retained(output, n)
                count_controls.append({'state': cell['state'], 'strategy': strategy,
                                       'count_retained': count_ok, 'expected_count': n, 'observed_counts': observed_counts(output), 'full_object_retained': contains(output, expected)})
    authored = json.loads((ROOT / 'artifacts/mcp-paper-evidence-20261026/guidance-fixtures.json').read_text())
    diagnostic = []
    for case in authored:
        if case['name'] not in ['equivalent_dual', 'conflicting_channels', 'file_plus_metadata', 'application_private_meta']:
            continue
        for strategy in ['text_priority', 'structured_priority', 'combination', 'authored_append_json']:
            source = copy.deepcopy(case['source'])
            if strategy == 'authored_append_json':
                # Explicitly authored fallback control; preserve original text and add
                # structured JSON. Native UniFi fallback is evaluated separately above.
                source['content'].append({'type': 'text', 'text': json.dumps(source['structuredContent'])})
            output = render(source, strategy)
            checks = [(req['value'] in output if req['kind'] == 'text' else contains(output, req['value']))
                      for req in case['requirements']]
            diagnostic.append({'fixture': case['name'], 'strategy': strategy, 'output': output,
                               'all_declared_facts_retained': all(checks),
                               'both_conflicting_claims_delivered': all(checks) if case['name'] == 'conflicting_channels' else None,
                               'conflict_resolved': False if case['name'] == 'conflicting_channels' else None,
                               'forbidden_values_present': [v for v in case['forbidden'] if v in output],
                               'utf8_bytes': len(output.encode()),
                               'ready_fact_occurrences': output.count('STATUS_READY_7K')})
    count_live = json.loads((OUT/'count-control-live-results.json').read_text())
    count_sensitivity = []
    for cell in count_live['cells']:
        n = cell['expected_count']
        assert count_retained(cell['received'], n), 'Producer count mismatch'
        strategies = ['native_full_text'] if cell['mode'] == 'full_text' else ['text_priority','structured_priority','combination']
        for strategy in strategies:
            output = render(cell['received'], strategy)
            if strategy in ('text_priority','native_full_text'):
                assert output == cell['handler_output']
            count_sensitivity.append({'state':cell['state'],'mode':cell['mode'],
                'strategy':strategy,'expected_count':n,'observed_counts':observed_counts(output),
                'count_retained':count_retained(output,n),'output':output})
    fixtures = json.loads((ROOT/'research/mcp-count-oracle-fixtures-20261027.json').read_text())
    count_checks = []
    for case in fixtures:
        observed = count_retained(case['output'], case['expected_count'])
        count_checks.append({**case,'observed_counts':observed_counts(case['output']),
            'observed_acceptance':observed,'check_passed':observed == case['expected_acceptance']})
    assert len(count_sensitivity) == 8 and all(x['count_retained'] for x in count_sensitivity)
    assert all(x['check_passed'] for x in count_checks)
    # Instrument checks: type-sensitive values and nonrequired-field omission.
    selfchecks = [contains('{"status":"ok","wan_ip":"203.0.113.42"}', {'status':'ok','wan_ip':'203.0.113.42'}),
                  not contains('{"enabled":"false"}', {'enabled':False}),
                  not contains('{"count":false}', {'count':0}),
                  not contains('{"wrong":"ok"}', {'status':'ok'})]
    assert all(selfchecks)
    report = {'contracts_sha256': live['protocol_sha256'], 'rows': rows,
              'summary_sufficient_controls': count_controls, 'authored_diagnostics': diagnostic,
              'instrument_checks': selfchecks,
              'count_sensitivity_controls': count_sensitivity, 'count_oracle_checks': count_checks,
              'amendment_sha256':hashlib.sha256((ROOT/'research/mcp-count-oracle-amendment-20261027.json').read_bytes()).hexdigest(),
              'strategy_definitions':{'native_full_text':'Native UniFi force_full_text_responses option; separate producer call', 'authored_append_json':'Append serialized structuredContent to the original text blocks; diagnostic only'},
              'qualification': 'Exact fixture-level evidence retention; no general semantic oracle, real task success, or universal strategy ranking. authored_append_json is an authored diagnostic; native_full_text rows are native producer runs. Count controls inspect only cardinality, including empty/two-record sensitivity states.'}
    (OUT / 'task-contract-results.json').write_text(json.dumps(report, indent=2) + '\n')
    summary = {s:{'facts':sum(r['required_facts_retained'] for r in rows if r['strategy']==s),
                  'total':sum(r['strategy']==s for r in rows),
                  'bytes':sum(r['utf8_bytes'] for r in rows if r['strategy']==s)} for s in ['text_priority','structured_priority','combination','native_full_text']}
    print(json.dumps(summary))

if __name__ == '__main__':
    main()
