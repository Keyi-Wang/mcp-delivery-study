"""Frozen independent-producer contrast; never selected by observed outcome."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/mcp-review-revision-20261026'
sys.path.insert(0, str(OUT / 'sources/hermes'))
with tempfile.TemporaryDirectory(prefix='mcp-review-git-') as tmp:
    repo = Path(tmp) / 'repo'
    repo.mkdir()
    env = dict(os.environ, GIT_AUTHOR_DATE='2026-10-26T00:00:00Z',
               GIT_COMMITTER_DATE='2026-10-26T00:00:00Z', GIT_CONFIG_NOSYSTEM='1',
               GIT_CONFIG_GLOBAL=os.devnull)
    for command in [['git', 'init', '-q', '-b', 'main'],
                    ['git', '-c', 'user.name=Research Fixture', '-c',
                     'user.email=fixture@example.invalid', 'commit', '-q', '--allow-empty',
                     '-m', 'review-confirmation-20261026']]:
        subprocess.run(command, cwd=repo, env=env, check=True)
    os.environ['HERMES_HOME'] = str(Path(tmp) / 'hermes')
    spec = importlib.util.spec_from_loader('gateway', loader=None, is_package=True)
    package = importlib.util.module_from_spec(spec)
    package.__path__ = [str(OUT / 'sources/hermes/gateway')]
    sys.modules['gateway'] = package
    from tools import mcp_tool as core
    from tools import mcp_tool_loop as loop
    from tools import mcp_tool_discovery as discovery
    from tools import mcp_tool_handlers as handlers
    assert core._ensure_mcp_sdk()
    loop._ensure_mcp_loop()
    name = 'independent-git'
    config = {'command': str(ROOT / '.venv-mcp-review-git/bin/python'),
              'args': ['-m', 'mcp_server_git', '--repository', str(repo)],
              'cwd': tmp, 'connect_timeout': 45}
    async def connect():
        server = await discovery._connect_server(name, config)
        discovery._adopt_server(name, server)
        return server
    server = None
    try:
        server = loop._run_on_mcp_loop(connect, timeout=55)
        observed = []
        original = server.session.call_tool
        async def observe(*args, **kwargs):
            result = await original(*args, **kwargs)
            observed.append(result)
            return result
        server.session.call_tool = observe
        output = handlers._make_tool_handler(name, 'git_log', 30)({'repo_path': str(repo), 'max_count': 1})
        assert len(observed) == 1, output
        result = observed[0].model_dump(mode='json', by_alias=True, exclude_none=True)
        report = {'source': 'modelcontextprotocol/servers; PyPI mcp-server-git==2026.10.19',
                  'selection': 'First available package version after the confirmation rule was frozen',
                  'protocol_sha256': hashlib.sha256((ROOT / 'research/mcp-review-contracts-20261026.json').read_bytes()).hexdigest(),
                  'producer_mode': 'Native packaged server, real local Git repository, real stdio connection to native Hermes handler',
                  'prediction': 'Plain-text commit message remains available through text priority',
                  'received': result, 'output': output,
                  'required_message_retained': 'review-confirmation-20261026' in output,
                  'structured_channel_present': result.get('structuredContent') is not None,
                  'native_render_equal': output == handlers._render_call_tool_result(observed[0], name),
                  'qualification': 'Independent producer contrast only, not a second loss/reversal family; native gateway package initializer bypass as inventoried for the main experiment'}
        (OUT / 'confirmation-results.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({k: report[k] for k in ['required_message_retained', 'structured_channel_present', 'native_render_equal']}))
    finally:
        if server:
            loop._run_on_mcp_loop(server.shutdown, timeout=20)
            core._servers.pop(name, None)
        loop._stop_mcp_loop()
