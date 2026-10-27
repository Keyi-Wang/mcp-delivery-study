"""Generate manuscript tables from retained execution artifacts."""
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / 'artifacts/mcp-paper-evidence-20261026'
PAPER = ROOT / 'tables'


def read(path):
    return json.loads((ROOT / path).read_text())


def write_csv(name, rows):
    with (ART / name).open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    PAPER.mkdir(exist_ok=True)
    # Verify the adapter and historical module hashes before interpreting runs.
    for x in read('artifacts/empirical-directions-20261026/source-manifest.json'):
        assert hashlib.sha256((ROOT / x['path']).read_bytes()).hexdigest() == x['sha256']
    for x in read('artifacts/mcp-preservation-study-20261026/source-manifest.json'):
        assert hashlib.sha256((ROOT / 'artifacts/mcp-preservation-study-20261026' / x['local']).read_bytes()).hexdigest() == x['sha256']

    tests = read('artifacts/mcp-paper-evidence-20261026/upstream-test-execution.json')
    capture = read('artifacts/mcp-paper-evidence-20261026/agno-stdio-http-capture.json')
    hermes = read('artifacts/mcp-preservation-study-20261026/hermes-repair-chain.json')
    webui = read('artifacts/mcp-preservation-followup-20261026/webui-media-probe.json')
    superset = read('artifacts/mcp-preservation-study-20261026/superset-wire-probe.json')
    attribution = read('artifacts/mcp-paper-evidence-20261026/patch-attribution.json')
    guidance = read('artifacts/mcp-paper-evidence-20261026/guidance-matrix.json')
    acceptance = read('artifacts/mcp-acceptance-study-20261026/selection-and-execution-audit.json')
    langchain = read('artifacts/mcp-acceptance-study-20261026/langchain-contrast.json')
    adcp = read('artifacts/mcp-acceptance-study-20261026/adcp-reconstruction.json')
    obligations = read('artifacts/mcp-obligation-study-20261026/obligation-results.json')
    producer = read('artifacts/mcp-obligation-study-20261026/native-producer-results.json')
    for item in read('artifacts/mcp-obligation-study-20261026/source-manifest.json'):
        data = (ROOT / item['path']).read_bytes()
        assert hashlib.sha256(data).hexdigest() == item['sha256']
        assert hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() == item['git_blob']
    assert len(producer['unit_tests']) == 21 and len(producer['rows']) == 8
    assert all(r['producer_client_retains_full_payload'] for r in producer['rows'])
    assert len(obligations['producer_consumer_cells']) == 24
    rows = []
    for source, title in [('combined', 'Combined-policy tests'), ('september', 'Later arbitration tests')]:
        cells = [next(r for r in obligations['groups'] if r['implementation'] == v and r['test_source'] == source)
                 for v in ['combined', 'september', 'branch-removal']]
        rows.append(title + ' & ' + ' & '.join(f"{r['passed']}/{r['total']}" for r in cells) + r' \\')
    for force_full, title in [(False, 'Producer: compact text'), (True, 'Producer: forced full text')]:
        counts = [sum(r['required_information_present'] for r in obligations['producer_consumer_cells']
                      if r['implementation'] == v and r['force_full_text'] == force_full)
                  for v in ['combined', 'september', 'branch-removal']]
        rows.append(title + ' & ' + ' & '.join(f'{x}/4' for x in counts) + r' \\')
    (PAPER / 'obligation-rows.tex').write_text('\n'.join(rows) + '\n')
    for item in read('artifacts/mcp-acceptance-study-20261026/source-manifest.json'):
        assert hashlib.sha256((ROOT / item['path']).read_bytes()).hexdigest() == item['sha256']
    assert len(tests['rows']) == 61 and not any(g['runtime_errors'] for g in tests['groups'])
    assert capture['runs'] == 16 and capture['http_requests'] == 32 and not capture['errors']
    assert capture['mcp_transport'] == 'actual_stdio'
    assert all(len(x['mcp_received_results']) == 1 for x in capture['rows'])
    assert webui['checks_passed'] and len(webui['cells']) == 16
    assert len(superset['rows']) == 6
    assert attribution['runs'] == 16 and attribution['http_requests'] == 32
    assert all(r['patch_only_matches_after_entire_request'] and r['reverted_matches_before_entire_request']
               for r in attribution['comparisons'])
    assert len(guidance['rows']) == 60 and len(guidance['oracle_selfchecks']) == 10
    diagnostic = {(r['implementation'], r['fixture']): r for r in guidance['rows']}
    versions = ['before', 'after', 'hermes-before', 'hermes-structured-first', 'hermes-combined']
    assert all(not diagnostic[v, 'structured_error']['required_information_present'] for v in versions)
    assert all(diagnostic[v, 'application_private_meta']['required_information_present'] and
               diagnostic[v, 'application_private_meta']['application_private_values_excluded'] for v in versions)
    assert all(diagnostic[v, 'application_private_meta']['application_metadata']['meta']['application_only'] == 'PRIVATE_APP_88'
               for v in ['before', 'after'])
    for fixture, combined_bytes in [('equivalent_dual', 151), ('reordered_equivalent', 160)]:
        combined = diagnostic['hermes-combined', fixture]
        priority = diagnostic['hermes-structured-first', fixture]
        assert combined['utf8_bytes'] == combined_bytes and priority['utf8_bytes'] == 65
        assert combined['ready_answer_occurrences'] == 2 and priority['ready_answer_occurrences'] == 1

    groups = {(g['test_source'], g['implementation']): g for g in tests['groups']}
    rows = []
    for label, names, versions in [
        ('Agno', ['agno-before-tests', 'agno-after-tests'], ['before', 'after']),
        ('Hermes', ['hermes-first-tests', 'hermes-combined-tests'], ['hermes-before', 'hermes-structured-first', 'hermes-combined'])]:
        rows.append((r'Agno tests & Metadata & Fallback & --- \\' if label == 'Agno' else
                     r'\midrule Hermes tests & Text & Structure & Combined \\'))
        for test in names:
            counts = [str(groups[test, v]['passed']) + '/' + str(groups[test, v]['total']) for v in versions]
            name = {'agno-before-tests': 'Metadata tests', 'agno-after-tests': 'Fallback tests',
                    'hermes-first-tests': 'Priority tests', 'hermes-combined-tests': 'Combined tests'}[test]
            rows.append(f'{name} & ' + ' & '.join(counts + (['---'] if label == 'Agno' else [])) + r' \\')
    rows.append(r'\midrule LangChain tests & Earlier & Repaired & --- \\')
    for source, title in [('before', 'earlier converter'), ('after', 'later converter')]:
        cells = [next(g for g in langchain['test_groups'] if g['test_version'] == source and
                      g['implementation'] == version) for version in ['before', 'after']]
        rows.append(title.capitalize() + ' & ' + ' & '.join(
            f"{g['passed']}/{g['total']}" for g in cells) + r' & --- \\')
    (PAPER / 'test-rows.tex').write_text('\n'.join(rows) + '\n')
    write_csv('test-version-matrix.csv', tests['groups'])

    names = {'structured_only': 'Structured only', 'summary_plus_data': 'Summary + structured',
             'file_plus_metadata': 'File text + metadata', 'equivalent_dual': 'Equivalent dual'}
    pairs = {(p['adapter'], p['fixture']): p for p in capture['pairs']}
    rows = []
    for fixture, name in names.items():
        cells = []
        for v in ['before', 'after']:
            cells.extend(['same' if pairs[v, fixture]['full_followup_request_collision'] else 'diff.',
                          'yes' if pairs[v, fixture]['both_required_answers_present'] else 'no'])
        rows.append(name + ' & ' + ' & '.join(cells) + r' \\')
    (PAPER / 'request-rows.tex').write_text('\n'.join(rows) + '\n')
    write_csv('request-collision-matrix.csv', capture['pairs'])

    rows = []
    names = dict(text_only='Text only', structured_only='Structured only', summary_plus_data='Summary + structured',
                 file_plus_metadata='File text + metadata', equivalent_dual='Equivalent dual', text_error='Text error')
    for fixture, name in names.items():
        cells = []
        for v in ['hermes-before', 'hermes-structured-first', 'hermes-combined']:
            r = next(r for r in hermes['rows'] if r['version'] == v and r['case'] == fixture)
            cells.append('yes' if r['all_required_atoms_preserved'] else 'no')
        rows.append(name + ' & ' + ' & '.join(cells) + r' \\')
    (PAPER / 'hermes-rows.tex').write_text('\n'.join(rows) + '\n')

    labels = {'whitespace_plus_data': 'Whitespace + data', 'empty_object': 'Explicit empty object',
              'typed_nested_values': 'Typed nested data', 'split_complementary_text': 'Split file text + metadata',
              'conflicting_channels': 'Both conflicting values', 'structured_error': 'Structured error cause'}
    rows = []
    for fixture, name in labels.items():
        cells = []
        for version in ['after', 'hermes-structured-first', 'hermes-combined']:
            row = next(r for r in guidance['rows'] if r['fixture'] == fixture and r['implementation'] == version)
            cells.append('yes' if row['required_information_present'] else 'no')
        rows.append(name + ' & ' + ' & '.join(cells) + r' \\')
    (PAPER / 'guidance-rows.tex').write_text('\n'.join(rows) + '\n')

    evidence = {
        'status': 'Bounded empirical manuscript with completed staged retrieval screening and executable successful-repair contrasts; no LLM-effectiveness or acceptance guarantee.',
        'projects': 6, 'included_incident_records': 7, 'audited_merged_repair_PRs': 9,
        'upstream_test_version_executions': len(tests['rows']) + len(langchain['test_rows']),
        'upstream_test_execution_groups': len(tests['groups']) + len(langchain['test_groups']),
        'langchain_native_tool_cells': len(langchain['rows']),
        'adcp_native_function_cells': len(adcp['rows']),
        'longitudinal_test_executions_including_repeats': len(obligations['test_rows']),
        'native_producer_original_unit_executions': len(producer['unit_tests']),
        'native_producer_negotiated_sessions': len(producer['rows']),
        'producer_consumer_composed_cells': len(obligations['producer_consumer_cells']),
        'producer_consumer_answer_pairs': len(obligations['producer_consumer_pairs']),
        'longitudinal_frozen_diagnostic_cells_including_repeats': len(obligations['cells']),
        'staged_screening_records': acceptance['screened_title_or_beyond'],
        'full_body_screening_records': acceptance['full_body_inspections'],
        'extended_ledger_records': acceptance['extended_ledger_records'],
        'agno_native_stdio_agent_runs': capture['runs'], 'agno_actual_provider_HTTP_requests': capture['http_requests'],
        'agno_counterfactual_pairs': len(capture['pairs']),
        'agno_full_request_collisions': sum(p['full_followup_request_collision'] for p in capture['pairs']),
        'hermes_main_version_fixture_cells': len(hermes['rows']),
        'hermes_counterfactual_inputs': sum(len(p['observations']) for p in hermes['counterfactual_collision_controls']),
        'webui_execution_cells': len(webui['cells']), 'webui_formatter_observations': webui['formatter_observations'],
        'superset_HTTP_calls': len(superset['rows']),
        'patch_attribution_runs': attribution['runs'],
        'patch_attribution_HTTP_requests': attribution['http_requests'],
        'guidance_diagnostic_cells': len(guidance['rows']),
        'guidance_fixtures': 12,
        'guidance_oracle_selfchecks': len(guidance['oracle_selfchecks']),
        'counting': 'Do not sum these heterogeneous units into a sample size or a defect count. Transport checks supersede previous Agno controlled-session checks in main tables.',
        'paid_model_calls': 0, 'actual_model_task_success_measured': False,
        'sources': [
            'artifacts/mcp-paper-evidence-20261026/upstream-test-execution.json',
            'artifacts/mcp-paper-evidence-20261026/agno-stdio-http-capture.json',
            'artifacts/mcp-paper-evidence-20261026/repair-metadata.json',
            'artifacts/mcp-paper-evidence-20261026/upstream-test-diffs.json',
            'artifacts/mcp-preservation-study-20261026/hermes-repair-chain.json',
            'artifacts/mcp-preservation-followup-20261026/webui-media-probe.json',
            'artifacts/mcp-preservation-study-20261026/superset-wire-probe.json',
            'artifacts/mcp-paper-evidence-20261026/patch-attribution.json',
            'artifacts/mcp-paper-evidence-20261026/guidance-matrix.json',
            'artifacts/mcp-paper-evidence-20261026/guidance-fixtures.json',
            'artifacts/mcp-acceptance-study-20261026/langchain-contrast.json',
            'artifacts/mcp-acceptance-study-20261026/adcp-reconstruction.json',
            'artifacts/mcp-acceptance-study-20261026/completed-screening.json',
            'artifacts/mcp-acceptance-study-20261026/selection-and-execution-audit.json',
            'artifacts/mcp-acceptance-study-20261026/source-manifest.json',
            'artifacts/mcp-obligation-study-20261026/source-manifest.json',
            'artifacts/mcp-obligation-study-20261026/native-producer-results.json',
            'artifacts/mcp-obligation-study-20261026/obligation-results.json',
            'artifacts/mcp-obligation-study-20261026/dedup-commit.json',
            'artifacts/mcp-obligation-study-20261026/dedup-ancestry.json',
            'artifacts/mcp-obligation-study-20261026/later-ancestry.json',
        ],
    }
    evidence['source_sha256'] = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in evidence['sources']}
    (PAPER / 'evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps({k: v for k, v in evidence.items() if k not in ['sources', 'source_sha256']}, indent=2))


if __name__ == '__main__':
    main()
