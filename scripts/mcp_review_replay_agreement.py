"""Validate the earlier controlled replay against identical live received data."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from mcp.types import CallToolResult
from mcp_obligation_probe import load_september

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/mcp-review-revision-20261026'
module = load_september()
live = json.loads((OUT / 'continuous-results.json').read_text())
rows = []
for cell in live['cells']:
    result = CallToolResult.model_validate(cell['received'])
    module._servers['review'] = SimpleNamespace(session=SimpleNamespace(call_tool=AsyncMock(return_value=result)),
                                                _rpc_lock=None, _pending_call_context=None)
    replay = module._make_tool_handler('review', cell['tool'], 30)({})
    rows.append({'state':cell['state'], 'mode':cell['mode'], 'tool':cell['tool'],
                 'replay_output':replay, 'equal_to_live_native':replay == cell['handler_output']})
assert all(r['equal_to_live_native'] for r in rows)
(OUT / 'replay-agreement.json').write_text(json.dumps({'rows':rows,'matches':sum(r['equal_to_live_native'] for r in rows),'total':len(rows)},indent=2)+'\n')
print(f'{len(rows)}/{len(rows)} live outputs match the earlier controlled replay on identical inputs')
