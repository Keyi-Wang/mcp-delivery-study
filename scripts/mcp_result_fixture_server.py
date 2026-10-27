"""Read-only local MCP server for explicitly synthetic transport fixtures."""
import asyncio
import json
import sys
from pathlib import Path

from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, Tool

fixture = Path(sys.argv[1])
server = Server('result-preservation-fixture')


@server.list_tools()
async def list_tools():
    return [Tool(name='get_record', description='Read the fixed local work-package record.',
                 inputSchema={'type': 'object', 'properties': {}, 'additionalProperties': False})]


@server.call_tool()
async def get_record(name, arguments):
    assert name == 'get_record' and not arguments
    result = CallToolResult.model_validate(json.loads(fixture.read_text()))
    fixture.with_suffix('.receipt.json').write_text(json.dumps({
        'tool': name, 'arguments': arguments,
        'returned': result.model_dump(mode='json', by_alias=True, exclude_none=True),
        'source': 'authored local fixture; not a production dataset',
    }, indent=2) + '\n')
    return result


async def main():
    async with stdio_server() as (reader, writer):
        await server.run(reader, writer, server.create_initialization_options())


if __name__ == '__main__':
    asyncio.run(main())
