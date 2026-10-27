"""One-command credential-free reproduction. Default: revised core; --all: contrasts.

python3 scripts/mcp_review_reproduce.py --install --all
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/mcp-review-revision'

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--install', action='store_true')
    parser.add_argument('--all', action='store_true', help='Include all historical exploratory contrasts')
    args = parser.parse_args()
    logs = OUT / 'reproduction-logs'
    logs.mkdir(exist_ok=True)
    commands = []
    started = time.monotonic()
    def run(label, command, cwd=ROOT, env=None):
        print(label, flush=True)
        with (logs / f'{label}.log').open('w') as f:
            result = subprocess.run([str(x) for x in command], cwd=cwd, env=env, stdout=f, stderr=subprocess.STDOUT)
        commands.append({'step':label,'exit_code':result.returncode})
        if result.returncode:
            raise RuntimeError(f'{label} failed; inspect {logs / (label + ".log")}')
    def py(env):
        return ROOT / env / 'bin/python'
    environments = [
        ('.venv-mcp-review-producer','3.13.17',OUT/'producer-requirements-freeze.txt'),
        ('.venv-mcp-review-consumer','3.13.17',OUT/'consumer-requirements-freeze.txt'),
        ('.venv-mcp-review-git','3.13.17',OUT/'git-requirements-freeze.txt'),
        ('.venv-mcp-visibility','3.10',ROOT/'artifacts/mcp-paper-evidence/handler-requirements-freeze.txt')]
    if args.all:
        environments += [
            ('.venv-mcp-wire','3.10',ROOT/'artifacts/mcp-preservation-followup/requirements-freeze.txt'),
            ('.venv-mcp-langchain','3.10',ROOT/'artifacts/mcp-acceptance-study/langchain-requirements-freeze.txt')]
    if args.install:
        uv = ROOT / '.venv-mcp-bootstrap/bin/uv'
        if not uv.exists():
            run('bootstrap-venv',[sys.executable,'-m','venv',ROOT/'.venv-mcp-bootstrap'])
            run('bootstrap-uv',[py('.venv-mcp-bootstrap'),'-m','pip','install','uv==0.13.5'])
        for env, version, requirements in environments:
            if not py(env).exists():
                run('create-'+env,[uv,'venv','--python',version,ROOT/env])
            run('install-'+env,[uv,'pip','sync','--python',py(env),requirements])
        if args.all:
            if not shutil.which('npm') or not shutil.which('node'):
                raise RuntimeError('--all requires Node/npm; validated on Node 16.20.2. No system packages are modified.')
            ts = ROOT / '.mcp-ts-runtime'
            ts.mkdir(exist_ok=True)
            for original,target in [('typescript-package.json','package.json'),('typescript-package-lock.json','package-lock.json')]:
                shutil.copyfile(ROOT/'artifacts/mcp-acceptance-study'/original,ts/target)
            run('install-typescript',['npm','ci','--prefix',ts,'--ignore-scripts','--no-audit','--no-fund'])
    for env,_,_ in environments:
        if not py(env).exists():
            raise RuntimeError(f'{env} missing; rerun with --install')
    expected = {name:json.loads((OUT/name).read_text()) for name in
                ['continuous-results.json','task-contract-results.json','replay-agreement.json','confirmation-results.json']}
    producer_root = OUT/'sources/unifi'
    producer_env = dict(os.environ,PYTHONPATH=str(producer_root/'src'))
    run('unifi-native-tests',[py('.venv-mcp-review-producer'),'-m','pytest','tests/test_adaptive_responses.py',
         'tests/network/test_wlans.py','-q','--override-ini','addopts=',f'--junitxml={OUT / "unifi-native-tests.xml"}'],producer_root,producer_env)
    hermes_env = dict(os.environ,PYTHONPATH=str(OUT/'sources/hermes'))
    original = ROOT/'artifacts/mcp-obligation-study/sources/september/tests/tools/test_mcp_structured_content.py'
    run('hermes-native-tests',[py('.venv-mcp-review-consumer'),'-m','pytest',str(original)+'::TestStructuredContentPreservation',
         str(original)+'::TestContentStructuredArbitration','-q','--override-ini','addopts=',f'--junitxml={OUT / "hermes-native-tests.xml"}'],env=hermes_env)
    run('count-control-live-calls',[py('.venv-mcp-review-consumer'),ROOT/'scripts/mcp_review_continuous.py','--count-controls'])
    for env,script in [('.venv-mcp-review-consumer','mcp_review_continuous.py'),
                       ('.venv-mcp-review-consumer','mcp_review_analysis.py'),
                       ('.venv-mcp-visibility','mcp_review_replay_agreement.py'),
                       ('.venv-mcp-review-consumer','mcp_review_confirmation.py')]:
        run(script,[py(env),ROOT/'scripts'/script])
    checks = {}
    for name,key in [('continuous-results.json','cells'),('task-contract-results.json','rows'),
                     ('task-contract-results.json','summary_sufficient_controls'),
                     ('task-contract-results.json','authored_diagnostics'),
                     ('task-contract-results.json','count_sensitivity_controls'),
                     ('task-contract-results.json','count_oracle_checks'),('replay-agreement.json','rows')]:
        checks[name+':'+key] = expected[name][key] == json.loads((OUT/name).read_text())[key]
    observed = json.loads((OUT/'confirmation-results.json').read_text())
    checks['independent-producer-contrast'] = all(expected['confirmation-results.json'][k] == observed[k]
        for k in ['received','output','required_message_retained','structured_channel_present'])
    if not all(checks.values()):
        raise RuntimeError(f'Primary observations changed: {checks}')
    if args.all:
        jobs = [('.venv-mcp-visibility','mcp_upstream_oracle_audit.py',[]),
                ('.venv-mcp-visibility','mcp_agno_http_capture.py',['--mcp-stdio']),
                ('.venv-mcp-visibility','mcp_repair_chain_probe.py',[]),
                ('.venv-mcp-wire','mcp_webui_media_probe.py',[]),
                ('.venv-mcp-wire','mcp_superset_wire_probe.py',[]),
                ('.venv-mcp-visibility','mcp_patch_attribution.py',[]),
                ('.venv-mcp-visibility','mcp_guidance_matrix.py',[]),
                ('.venv-mcp-langchain','mcp_langchain_contrast.py',[]),
                ('node','mcp_adcp_reconstruction.cjs',[]),
                ('.venv-mcp-wire','mcp_native_producer_probe.py',[]),
                ('.venv-mcp-visibility','mcp_obligation_probe.py',[])]
        for env,script,argv in jobs:
            run(script,[('node' if env=='node' else py(env)),ROOT/'scripts'/script,*argv],
                env=dict(os.environ,MCP_TYPESCRIPT_PATH=str(ROOT/'.mcp-ts-runtime/node_modules/typescript')))
    run('normalize-report-paths',[sys.executable,ROOT/'scripts/normalize_report_paths.py'])
    run('build-historical-tables',[sys.executable,ROOT/'scripts/build_mcp_evidence_tables.py'])
    run('audit-revision',[sys.executable,ROOT/'scripts/mcp_review_artifact_audit.py'])
    report = {'scope':'Same operator local reproduction; not independent human replication',
              'all_contrasts':args.all,'steps':commands,'same_primary_observations':checks,
              'elapsed_seconds':round(time.monotonic()-started,3),'paid_model_calls':0}
    (OUT/'one-command-reproduction.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__ == '__main__':
    main()
