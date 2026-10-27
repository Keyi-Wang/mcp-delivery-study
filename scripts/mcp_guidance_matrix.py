"""Source-shaped controls for bounded maintenance guidance, not model accuracy."""
import asyncio
import csv
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from agno.tools.function import Function, FunctionCall
from mcp.types import CallToolResult, TextContent, Tool

from mcp_visibility_probe import LocalSession, NoProviderModel, load_source
from mcp_repair_chain_probe import Session, load as load_hermes

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/mcp-paper-evidence'


def json_documents(value):
    """Decode JSON objects/arrays, including JSON carried inside envelope strings.

    This is a fixture oracle, NOT a general semantic interpretation algorithm.
    """
    if isinstance(value, (dict, list)):
        yield value
        for child in value.values() if isinstance(value, dict) else value:
            yield from json_documents(child)
    elif isinstance(value, str):
        decoder = json.JSONDecoder()
        for i, char in enumerate(value):
            if char not in '{[':
                continue
            try:
                decoded, _ = decoder.raw_decode(value[i:])
            except ValueError:
                continue
            yield from json_documents(decoded)


def typed_subset(expected, observed):
    if type(expected) is not type(observed):
        return False
    if isinstance(expected, dict):
        return all(k in observed and typed_subset(v, observed[k]) for k, v in expected.items())
    if isinstance(expected, list):
        return len(expected) == len(observed) and all(typed_subset(x, y) for x, y in zip(expected, observed))
    return expected == observed


def evaluate(output, requirements, forbidden):
    documents = list(json_documents(output))
    checks = []
    for req in requirements:
        if req['kind'] == 'text':
            present = req['value'] in output
        elif req['kind'] == 'json_subset':
            present = any(typed_subset(req['value'], doc) for doc in documents)
        elif req['kind'] == 'explicit_empty_object':
            present = any(type(doc) is dict and doc == {} for doc in documents)
        else:
            raise ValueError(req)
        checks.append({'requirement': req, 'present': present})
    leaked = [s for s in forbidden if s in output]
    return {'checks': checks, 'required_information_present': all(c['present'] for c in checks),
            'forbidden_values_present': leaked, 'application_private_values_excluded': not leaked}


def oracle_selfchecks():
    fact = [{'kind': 'json_subset', 'value': {'count': 0, 'ready': False}}]
    cases = [
        ('correct_types', '{"ready":false,"count":0}', fact, [], True),
        ('bool_is_not_int', '{"ready":false,"count":false}', fact, [], False),
        ('string_is_not_int', '{"ready":false,"count":"0"}', fact, [], False),
        ('wrong_key', '{"ready":false,"other":0}', fact, [], False),
        ('envelope_is_allowed', json.dumps({'result': '{"count":0,"ready":false}'}), fact, [], True),
        ('truncation', '{"ready":false,"count":', fact, [], False),
        ('missing_object', '', [{'kind': 'explicit_empty_object'}], [], False),
        ('empty_enveloped', '{"result":{}}', [{'kind': 'explicit_empty_object'}], [], True),
        ('metadata_leak', 'public PRIVATE_APP_88', [{'kind': 'text', 'value': 'public'}], ['PRIVATE_APP_88'], False),
        ('metadata_excluded', 'public', [{'kind': 'text', 'value': 'public'}], ['PRIVATE_APP_88'], True),
    ]
    observations = []
    for name, output, req, forbidden, expected in cases:
        result = evaluate(output, req, forbidden)
        actual = result['required_information_present'] and result['application_private_values_excluded']
        assert actual == expected, name
        observations.append({'case': name, 'expected': expected, 'observed': actual})
    return observations


def fixtures():
    data = {'record_id': 'work-42', 'status': 'STATUS_READY_7K'}
    json_req = [{'kind': 'json_subset', 'value': data}]
    file_req = [{'kind': 'text', 'value': 'FILE_ANSWER_19'}]
    typed = {'record': {'count': 0, 'ready': False, 'note': None, 'labels': ['研发', 'é']}}
    def row(name, texts, structured, req, **extra):
        result = {'content': [{'type': 'text', 'text': t} for t in texts], 'isError': extra.pop('isError', False)}
        if structured is not None:
            result['structuredContent'] = structured
        private = extra.pop('private', None)
        if private:
            result['_meta'] = {'application_only': private}
        return {'name': name, 'source': result, 'requirements': req,
                'forbidden': [private] if private else [], **extra}
    return [
        row('structured_only', [], data, json_req),
        row('summary_plus_data', ['Query completed; details follow in structuredContent.'], data, json_req),
        row('file_plus_metadata', ['FILE_ANSWER_19'], {'fileName': 'shared.txt'}, file_req),
        row('equivalent_dual', [json.dumps(data)], data, json_req),
        row('reordered_equivalent', [json.dumps(dict(reversed(list(data.items()))), indent=2)], data, json_req),
        row('split_complementary_text', ['FILE_ANSWER_19', 'SECOND_LINE_24'], {'fileName': 'shared.txt'},
            file_req + [{'kind': 'text', 'value': 'SECOND_LINE_24'}]),
        row('whitespace_plus_data', [' \n\t '], data, json_req),
        row('empty_object', [], {}, [{'kind': 'explicit_empty_object'}]),
        row('typed_nested_values', [], typed, [{'kind': 'json_subset', 'value': typed}]),
        row('application_private_meta', [json.dumps(data)], data, json_req, private='PRIVATE_APP_88'),
        row('conflicting_channels', [json.dumps({'status': 'STATUS_BLOCKED_3Q'})], data,
            [{'kind': 'json_subset', 'value': {'status': 'STATUS_BLOCKED_3Q'}},
             {'kind': 'json_subset', 'value': {'status': 'STATUS_READY_7K'}}],
            interpretation='Both source claims are required for a conflict review, NOT a correct resolved answer.'),
        row('structured_error', [], {'code': 'DENIED_REASON_43'},
            [{'kind': 'json_subset', 'value': {'code': 'DENIED_REASON_43'}}], isError=True,
            interpretation='Authored error-cause diagnostic, not a confirmed new production bug or success-path obligation.'),
    ]


def main():
    selfchecks = oracle_selfchecks()
    inputs = fixtures()
    expected_names = json.loads((ROOT / 'research/mcp-guidance-amendment.json').read_text())['guidance_matrix']['fixtures']
    assert [r['name'] for r in inputs] == expected_names
    fixture_path = OUT / 'guidance-fixtures.json'
    fixture_path.write_text(json.dumps(inputs, ensure_ascii=False, indent=2) + '\n')
    rows = []
    for label in ['before', 'after', 'hermes-before', 'hermes-structured-first', 'hermes-combined']:
        agno = not label.startswith('hermes')
        module = load_source(label) if agno else load_hermes(label)
        if not agno:
            module._run_on_mcp_loop = lambda coro, timeout: asyncio.run(coro)
        for case in inputs:
            source = CallToolResult.model_validate(case['source'])
            if agno:
                entry = module.get_entrypoint_for_tool(Tool(name='get_record', inputSchema={'type': 'object'}), LocalSession(source))
                converted = asyncio.run(entry())
                call = FunctionCall(function=Function(name='get_record', entrypoint=lambda: converted), arguments={}, call_id='local-guidance')
                messages = []
                list(NoProviderModel(id='offline-no-provider').run_function_call(call, messages))
                assert len(messages) == 1 and isinstance(messages[0].content, str)
                output = messages[0].content
                app_metadata = converted.metadata
                boundary = 'native_tool_message'
            else:
                module._servers['offline'] = SimpleNamespace(session=Session(source))
                output = module._make_tool_handler('offline', 'read_status', 5.0)({})
                app_metadata = None
                boundary = 'native_handler_output'
            observation = evaluate(output, case['requirements'], case['forbidden'])
            rows.append({'implementation': label, 'fixture': case['name'], 'boundary': boundary,
                         'output': output, 'utf8_bytes': len(output.encode('utf-8')),
                         'ready_answer_occurrences': output.count('STATUS_READY_7K'),
                         'application_metadata': app_metadata, **observation})
    assert len(rows) == 60
    assert all(r['application_private_values_excluded'] for r in rows)
    # Expected outcome is reported per requirement, not an aggregate framework ranking.
    report = {'protocol': 'research/mcp-guidance-amendment.json', 'rows': rows,
              'oracle_selfchecks': selfchecks,
              'fixture_sha256': hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
              'paid_api_calls': 0,
              'limits': ['12 authored controls across five implementations; not 60 natural incidents.',
                         'Agno native message and Hermes handler boundaries differ; do not rank framework pass rates.',
                         'Typed JSON subset checks are fixture-specific, not a general semantic oracle.',
                         'Conflict retention does not resolve authority or identify the true answer.',
                         'Bytes/occurrences are not token costs or measured downstream model harm.',
                         'Structured error is a prospective diagnostic; no new real-world defect claim.']}
    (OUT / 'guidance-matrix.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    compact = [{k: r[k] for k in ['implementation', 'fixture', 'boundary', 'required_information_present',
                                'application_private_values_excluded', 'utf8_bytes', 'ready_answer_occurrences']} for r in rows]
    with (OUT / 'guidance-matrix.csv').open('w') as f:
        writer = csv.DictWriter(f, fieldnames=list(compact[0]))
        writer.writeheader()
        writer.writerows(compact)
    print(json.dumps(compact, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
