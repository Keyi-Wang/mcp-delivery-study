"""Supported-runtime, continuous native UniFi -> MCP -> Hermes execution.

Only observation wrapper: session.call_tool delegates unchanged and captures its
actual result. No replacement session, scheduler, renderer, or lifecycle gate.
"""
import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/mcp-review-revision'
sys.path.insert(0, str(OUT / 'sources/hermes'))
parser = argparse.ArgumentParser()
parser.add_argument('--output')
parser.add_argument('--count-controls', action='store_true')
args = parser.parse_args()
isolated = tempfile.TemporaryDirectory(prefix='mcp-review-native-')
os.environ['HERMES_HOME'] = isolated.name
# Load native gateway.status without bootstrapping unrelated chat-platform gateways.
# This package-initializer bypass is inventoried; status/lifecycle function bodies
# remain native. It does not replace a session, MCP scheduler or result renderer.
gateway_spec = importlib.util.spec_from_loader('gateway', loader=None, is_package=True)
gateway_package = importlib.util.module_from_spec(gateway_spec)
gateway_package.__path__ = [str(OUT / 'sources/hermes/gateway')]
sys.modules['gateway'] = gateway_package
from tools import mcp_tool as core
from tools import mcp_tool_loop as loop
from tools import mcp_tool_discovery as discovery
from tools import mcp_tool_handlers as handlers

assert core._ensure_mcp_sdk(), 'Native Hermes SDK import failed'
loop._ensure_mcp_loop()
cells = []
try:
    for state_key in ([0,2] if args.count_controls else [False,True]):
        perturbed = bool(state_key) if not args.count_controls else False
        for full in (False, True):
            name = f'review-{int(state_key)}-{int(full)}'
            command_args = [str(ROOT / 'scripts/mcp_review_unifi_server.py')]
            if args.count_controls:
                command_args.extend(['--wlan-count',str(state_key)])
            elif perturbed:
                command_args.append('--perturbed')
            if full:
                command_args.append('--full-text')
            config = {'command': str(ROOT / '.venv-mcp-review-producer/bin/python'),
                      'args': command_args, 'cwd': isolated.name, 'connect_timeout': 45}
            async def connect():
                server = await discovery._connect_server(name, config)
                discovery._adopt_server(name, server)
                return server
            server = loop._run_on_mcp_loop(connect, timeout=55)
            print(f'Connected {name}', flush=True)
            observed = []
            original_call = server.session.call_tool
            async def observe(*call_args, **call_kwargs):
                result = await original_call(*call_args, **call_kwargs)
                observed.append(result)
                return result
            server.session.call_tool = observe
            try:
                for tool in (('list_wlans',) if args.count_controls else ('get_wan_status','list_wlans')):
                    observed.clear()
                    output = handlers._make_tool_handler(name, tool, 30)({})
                    assert len(observed) == 1, (name, tool, output)
                    actual = observed[0]
                    replay = handlers._render_call_tool_result(actual, name)
                    assert output == replay, 'Live handler differs from same-result native render'
                    cells.append({'state': (f'wlan_count_{state_key}' if args.count_controls else ('perturbed' if perturbed else 'upstream_seed')),
                                  'mode': 'full_text' if full else 'adaptive', 'tool': tool,
                                  'initialize': server.initialize_result.model_dump(mode='json', by_alias=True),
                                  'received': actual.model_dump(mode='json', by_alias=True, exclude_none=True),
                                  'handler_output': output, 'native_render_equal': output == replay})
                    if args.count_controls:
                        cells[-1]['expected_count'] = state_key
                    print(f'Observed {name} {tool}', flush=True)
            finally:
                loop._run_on_mcp_loop(server.shutdown, timeout=20)
                core._servers.pop(name, None)
finally:
    loop._stop_mcp_loop()
    isolated.cleanup()
report = {'python': platform.python_version(), 'consumer_mcp': importlib.metadata.version('mcp'),
          'protocol_sha256': hashlib.sha256((ROOT / 'research/mcp-review-contracts.json').read_bytes()).hexdigest(),
          'scope': 'Complete producer build_server, upstream built-in controller stub, native Hermes live MCP connection and unchanged synchronous handler; no model/provider request',
          'interventions': ['Author sensitivity state perturbation', 'Existing producer full-text option'],
          'replaced_dependencies': ['Live UniFi controller replaced by upstream built-in StubState',
                                    'gateway package initializer bypassed to avoid unrelated chat-platform bootstrap; native gateway.status and MCP lifecycle functions retained'],
          'observation_wrappers': ['session.call_tool delegates unchanged, records the returned SDK object'],
          'cells': cells}
if args.count_controls:
    report['amendment_sha256'] = hashlib.sha256((ROOT/'research/mcp-count-oracle-amendment.json').read_bytes()).hexdigest()
    report['interventions'] = ['Author-defined empty and two-record controller states','Existing producer full-text option']
    report['scope'] = 'Four additional native stdio calls for count-only sensitivity checks; separate from the original eight calls'
output_path = Path(args.output) if args.output else OUT / ('count-control-live-results.json' if args.count_controls else 'continuous-results.json')
output_path.write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'cells': len(cells), 'native_render_equal': sum(c['native_render_equal'] for c in cells)}))
