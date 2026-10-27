"""Launch the unchanged, pinned UniFi application with its own test controller."""
import argparse
import copy
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'artifacts/mcp-review-revision-20261026/sources/unifi/src'))
from mcp_unifi.config import Settings
from mcp_unifi.clients.stubs import StubState
from mcp_unifi.server import build_server

parser = argparse.ArgumentParser()
parser.add_argument('--full-text', action='store_true')
parser.add_argument('--perturbed', action='store_true')
parser.add_argument('--wlan-count', type=int, choices=[0,2])
args = parser.parse_args()
# The launcher reads no credential files. Isolate settings from inherited UniFi configuration.
for key in list(os.environ):
    if key.startswith(('UNIFI_', 'MCP_UNIFI_', 'OTEL_')):
        os.environ.pop(key)
state = StubState()
# Keep the upstream-generated UUIDs identical across subprocesses and modes.
snapshot = json.loads((ROOT / 'artifacts/mcp-review-revision-20261026/upstream-seed-snapshot.json').read_text())
state.health, state.wlans = snapshot['health'], snapshot['wlans']
# Synthetic passphrase copied from the original upstream read-redaction test.
# The seed itself is already redacted, so leaving it untouched would not test exclusion.
state.wlans[0]['x_passphrase'] = 'correct-horse-battery-staple'
if args.perturbed:
    for row in state.health:
        if row.get('subsystem') == 'wan':
            row.update(status='warning', wan_ip='203.0.113.99')
    state.wlans[0].update(name='Office-Review', enabled=False)
if args.wlan_count == 0:
    state.wlans = []
elif args.wlan_count == 2:
    second = copy.deepcopy(state.wlans[0])
    second.update(_id='count-control-second-wlan', name='Count-Control-Second')
    state.wlans.append(second)
settings = Settings(stub_mode=True, auth_required=False, log_format='text',
                    force_full_text_responses=args.full_text, _env_file=None)
build_server(settings, stub=state).run(transport='stdio', show_banner=False)
