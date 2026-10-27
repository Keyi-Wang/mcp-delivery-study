"""Verify revision sources, synthesize table rows and link new evidence."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/mcp-review-revision-20261026'
PAPER = ROOT / 'tables'

def read(path):
    return json.loads(path.read_text())

def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')

def main():
    records = []
    for label in ['hermes', 'unifi']:
        tree = read(OUT / f'{label}-upstream-tree.json')
        expected = {x['path']:x['sha'] for x in tree['files']}
        for path in sorted((OUT / 'sources' / label).rglob('*')):
            if not path.is_file() or any(x in path.parts for x in ['__pycache__','.pytest_cache']):
                continue
            relative = str(path.relative_to(OUT / 'sources' / label))
            data = path.read_bytes()
            blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
            assert blob == expected[relative], str(path)
            records.append({'path':str(path.relative_to(ROOT)), 'repo':tree['repo'], 'ref':tree['ref'],
                            'upstream':relative, 'git_blob':blob, 'git_blob_verified':True,
                            'sha256':hashlib.sha256(data).hexdigest()})
    save(OUT / 'source-manifest.json', records)
    live = read(OUT / 'continuous-results.json')
    assert len(live['cells']) == 8 and all(r['native_render_equal'] for r in live['cells'])
    protocol_hash = hashlib.sha256((ROOT / 'research/mcp-review-contracts-20261026.json').read_bytes()).hexdigest()
    assert live['protocol_sha256'] == protocol_hash
    replay = read(OUT / 'replay-agreement.json')
    assert replay['matches'] == replay['total'] == 8
    confirmation = read(OUT / 'confirmation-results.json')
    assert confirmation['protocol_sha256'] == protocol_hash
    assert confirmation['required_message_retained'] and not confirmation['structured_channel_present']
    tests = {}
    for name, expected in [('unifi',50),('hermes',7)]:
        cases = list(ET.parse(OUT / f'{name}-native-tests.xml').iter('testcase'))
        failed = sum(c.find('failure') is not None or c.find('error') is not None for c in cases)
        assert len(cases) == expected and failed == 0
        tests[name] = {'passed':len(cases)-failed,'total':len(cases)}
    data = read(OUT / 'task-contract-results.json')
    assert data['contracts_sha256'] == protocol_hash
    table, summary = [], {}
    for strategy,label in [('text_priority','Text priority'),('structured_priority','Structure (control)'),
                           ('combination','Combine (control)'),('full_text_fallback','Native full text')]:
        rows = [r for r in data['rows'] if r['strategy'] == strategy]
        count = [r for r in data['summary_sufficient_controls'] if r['strategy'] == strategy]
        assert len(rows) == 4 and len(count) == 2
        facts = sum(r['required_facts_retained'] for r in rows)
        assert facts == (0 if strategy == 'text_priority' else 4)
        assert all(not r['forbidden_secrets_retained'] for r in rows)
        summary[strategy] = {'required_facts':facts,'full_objects':sum(r['full_object_retained'] for r in rows),
                             'count_only':sum(r['count_retained'] for r in count),
                             'total_utf8_bytes':sum(r['utf8_bytes'] for r in rows)}
        s = summary[strategy]
        table.append(label + f" & {s['required_facts']}/4 & {s['full_objects']}/4 & {s['count_only']}/2 & {s['total_utf8_bytes']}" + r' \\')
    (PAPER / 'review-policy-rows.tex').write_text('\n'.join(table) + '\n')
    sources = [str((OUT / name).relative_to(ROOT)) for name in [
        'continuous-results.json','task-contract-results.json','replay-agreement.json',
        'confirmation-results.json','source-manifest.json','unifi-native-tests.xml','hermes-native-tests.xml']]
    evidence = read(PAPER / 'evidence.json')
    evidence['sources'] = list(dict.fromkeys(evidence['sources'] + sources))
    evidence['source_sha256'] = {p:hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in evidence['sources']}
    evidence['review_revision'] = {'native_tests':tests,'continuous_calls':8,'replay_matches':8,
                                 'policies':summary, 'independent_producer_contrast':True,
                                 'human_review_completed':False}
    save(PAPER / 'evidence.json', evidence)
    save(OUT / 'revision-summary.json', {'verified_source_files':len(records),**evidence['review_revision']})
    save(OUT / 'table-traceability.json', {
        'Table I':{'source':'artifacts/mcp-acceptance-study-20261026/selection-and-execution-audit.json','key':'selected_case_urls','qualification':'Boundaries updated by continuous-results.json'},
        'Table II':{'sources':['artifacts/mcp-paper-evidence-20261026/upstream-test-execution.json','artifacts/mcp-acceptance-study-20261026/langchain-contrast.json'],'keys':['groups','test_groups'],'generator':'scripts/build_mcp_evidence_tables.py'},
        'Table III':{'source':str((OUT/'task-contract-results.json').relative_to(ROOT)),'key':'rows and summary_sufficient_controls','generator':'scripts/mcp_review_artifact_audit.py'},
        'Table IV':{'source':'artifacts/mcp-paper-evidence-20261026/agno-stdio-http-capture.json','key':'pairs: full_followup_request_collision and both_required_answers_present','generator':'scripts/build_mcp_evidence_tables.py'},
        'Figure 1':{'sources':['artifacts/mcp-obligation-study-20261026/obligation-results.json','artifacts/mcp-obligation-study-20261026/dedup-ancestry.json','artifacts/mcp-obligation-study-20261026/later-ancestry.json'],'qualification':'Temporal sequence only'}})
    print(json.dumps({'verified_source_files':len(records),'native_tests':tests,'policies':summary}))

if __name__ == '__main__':
    main()
