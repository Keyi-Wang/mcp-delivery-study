#!/usr/bin/env python3
"""Offline pinned-native replay, NOT a full Open WebUI/model deployment.

Run: .venv-mcp-wire/bin/python scripts/mcp_webui_media_probe.py
Protocol: research/mcp-preservation-followup-protocol-20261026.json
"""
from __future__ import annotations

import ast
import asyncio
import base64
import copy
import hashlib
import importlib.metadata
import json
import logging
import re
import struct
import sys
import traceback
import zlib
from pathlib import Path
from typing import Any

from mcp.types import CallToolResult
from starlette.responses import HTMLResponse

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/mcp-preservation-followup-20261026"
PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII="
FACT = "camera_status=online; source=camera.front_door"


def native_functions(path, names, env):
    tree = ast.parse(path.read_text())
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    assert {n.name for n in nodes} == set(names)
    # Compile entire original function nodes. Annotations are postponed only.
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)] + nodes, type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), env)
    return [{"function": n.name, "line": n.lineno, "end_line": n.end_lineno} for n in nodes]


def native_streaming_slice(path, env):
    tree = ast.parse(path.read_text())
    matches = [n for n in ast.walk(tree) if isinstance(n, ast.For)
               and ast.unparse(n.target) == "file_item"
               and ast.unparse(n.iter) == "result.get('files', [])"]
    assert len(matches) == 2, "Upstream shape changed; do not select a different loop silently"
    loop = sorted(matches, key=lambda n: n.lineno)[1]
    wrapper = ast.parse("async def project_streaming(result, request, metadata, user):\n    output_parts = [{'type': 'input_text', 'text': result.get('content', '')}]\n    display_files = []\n    return output_parts, display_files\n").body[0]
    wrapper.body.insert(-1, loop)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[wrapper], type_ignores=[])), str(path), "exec"), env)
    return {"unchanged_AST_slice": "streaming file_item loop", "line": loop.lineno, "end_line": loop.end_lineno}


def image_refs(value):
    if isinstance(value, dict):
        if value.get("type") in {"input_image", "image_url"}:
            url = value.get("image_url")
            if isinstance(url, dict):
                url = url.get("url")
            if isinstance(url, str):
                yield url
        for child in value.values():
            yield from image_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from image_refs(child)


async def execute_cell(version, consumer, fixture, payload):
    storage = {}

    async def store_media(request, data_uri, metadata, user):
        # Controlled side effect only; the content-to-file transformation is native.
        body = base64.b64decode(data_uri.split(",", 1)[1], validate=True)
        url = "/api/v1/files/" + hashlib.sha256(body).hexdigest()[:20] + "/content"
        storage[url] = data_uri
        return url

    async def no_events(metadata):
        return None, None

    async def empty_history(*args):
        return []

    call = {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "camera_snapshot",
            "arguments": "{}", "status": "queued", "approved": True}
    db = {"output": [copy.deepcopy(call)]}

    class MemoryChats:
        @staticmethod
        async def get_message_by_id_and_message_id(*args):
            return copy.deepcopy(db)

        @staticmethod
        async def upsert_message_to_chat_by_id_and_message_id(chat_id, message_id, update, touch=False):
            db.update(copy.deepcopy(update))

    env = {
        "Any": Any, "json": json, "JSONCodec": json, "re": re, "HTMLResponse": HTMLResponse,
        "log": logging.getLogger("webui-probe"),
        "BASE64_IMAGE_DATA_URI_RE": re.compile(r"data:image/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/]+={0,2}", re.IGNORECASE),
        "get_file_url_from_base64": store_media, "is_saved_chat_id": lambda value: value == "saved-chat",
        "Chats": MemoryChats, "get_event_emitter_and_caller": no_events,
        "load_messages_from_db": empty_history, "ENABLE_PLUGINS": False,
        "normalize_messages_for_model": lambda form_data: None,
        "output_id": lambda prefix: prefix + "_controlled",
    }
    source_dir = OUT / "sources" / ("webui-media-" + version)
    native = native_functions(source_dir / "middleware.py", [
        "extract_base64_images", "store_tool_result_image", "process_tool_result",
        "_is_tool_result_error", "drain_approved_tool_calls",
    ], env)
    native += native_functions(source_dir / "misc.py", [
        "reconcile_tool_pairs", "convert_output_to_messages", "get_content_from_message",
    ], env)
    projection = native_streaming_slice(source_dir / "middleware.py", env)
    metadata = {"chat_id": "saved-chat", "message_id": "message-1", "assistant_message_id": "message-1"}
    typed_result = CallToolResult(content=payload)
    typed_content = typed_result.model_dump(mode="json", exclude_none=True)["content"]
    content, files, embeds = await env["process_tool_result"](
        None, "camera_snapshot", typed_content, "mcp", metadata=metadata, user=None)
    result = {"tool_call_id": "call_1", "content": content, "files": files, "embeds": embeds}

    async def prepared_tool_result(*args):
        return copy.deepcopy(result)

    env["execute_tool_call_for_output"] = prepared_tool_result
    if consumer == "approval":
        paused = await env["drain_approved_tool_calls"](None, {}, None, {"id": "offline"}, metadata)
        assert paused is False
        output = db["output"]
    else:
        parts, display_files = await env["project_streaming"](copy.deepcopy(result), None, metadata, None)
        call["status"] = "completed"
        output = [call, {"type": "function_call_output", "id": "fco_controlled", "call_id": "call_1",
                         "output": parts, "status": "completed", "files": display_files}]
    tool_output = next(x for x in output if x["type"] == "function_call_output")
    observations = []
    for flatten in [False, True]:
        messages = env["convert_output_to_messages"](copy.deepcopy(output), flatten_tool_images=flatten)
        refs = list(image_refs(messages))
        resolved = []
        for ref in refs:
            uri = ref if ref.startswith("data:") else storage[ref]
            resolved.append(hashlib.sha256(base64.b64decode(uri.split(",", 1)[1], validate=True)).hexdigest())
        expected_images = int(fixture == "embedded_image" or (fixture == "image" and version == "after"))
        expected_digest = hashlib.sha256(base64.b64decode(PNG)).hexdigest()
        expected_display = int(fixture in {"image", "audio_scope_control"})
        display_count = len(tool_output.get("files", []))
        text_preserved = any(FACT in str(m.get("content", "")) for m in messages)
        checks = {
            "expected_image_reference_count": len(refs) == expected_images,
            "expected_display_file_count": display_count == expected_display,
            "model_image_bytes_match_fixture": all(h == expected_digest for h in resolved),
            "text_control_preserved": text_preserved if fixture == "text" else None,
            "tool_pair_survives_formatter": any(m.get("role") == "tool" for m in messages),
        }
        observations.append({"flatten_tool_images": flatten, "model_image_references": refs,
                             "model_image_byte_digests": resolved, "display_file_count": display_count,
                             "formatted_messages": messages, "checks": checks,
                             "checks_passed": all(v for v in checks.values() if v is not None)})
    return {"version": version, "consumer": consumer, "fixture": fixture,
            "boundary": "complete approval function; controlled IO; explicit formatter" if consumer == "approval"
                        else "original streaming file projection slice; explicit formatter",
            "input": typed_result.model_dump(mode="json", exclude_none=True), "processed_result": result,
            "stored_output": output, "native_functions": native, "streaming_projection": projection,
            "observations": observations}


async def main():
    # Validate transport fixture independently of the native forwarding oracle.
    png_bytes = base64.b64decode(PNG, validate=True)
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
    cursor, compressed = 8, b""
    while cursor < len(png_bytes):
        length = struct.unpack("!I", png_bytes[cursor:cursor + 4])[0]
        chunk = png_bytes[cursor + 4:cursor + 8 + length]
        crc = struct.unpack("!I", png_bytes[cursor + 8 + length:cursor + 12 + length])[0]
        assert zlib.crc32(chunk) & 0xffffffff == crc
        if chunk[:4] == b"IDAT":
            compressed += chunk[4:]
        cursor += length + 12
    assert cursor == len(png_bytes) and len(zlib.decompress(compressed)) == 3
    manifest = json.loads((OUT / "source-content-verification.json").read_text())
    for entry in manifest:
        assert hashlib.sha256((OUT / entry["path"]).read_bytes()).hexdigest() == entry["sha256"]
    fixtures = {
        "image": [{"type": "image", "mimeType": "image/png", "data": PNG}],
        "embedded_image": [{"type": "resource", "resource": {"uri": "camera://front-door/snapshot", "mimeType": "image/png", "blob": PNG}}],
        "text": [{"type": "text", "text": FACT}],
        # Inert bytes: validates routing only, not audio decoding or modality support.
        "audio_scope_control": [{"type": "audio", "mimeType": "audio/wav", "data": base64.b64encode(b"routing-fixture-not-playable-audio").decode()}],
    }
    cells = []
    failures = []
    for version in ["before", "after"]:
        for consumer in ["approval", "streaming_slice"]:
            for fixture, payload in fixtures.items():
                try:
                    cells.append(await execute_cell(version, consumer, fixture, payload))
                except Exception:
                    failures.append({"version": version, "consumer": consumer, "fixture": fixture, "traceback": traceback.format_exc()})
    checks_passed = not failures and all(o["checks_passed"] for c in cells for o in c["observations"])
    report = {"protocol": "research/mcp-preservation-followup-protocol-20261026.json", "source_verification": manifest,
              "python": sys.version, "packages": {p: importlib.metadata.version(p) for p in ["mcp", "starlette", "pydantic"]},
              "execution_cells": len(cells), "formatter_observations": sum(len(c["observations"]) for c in cells),
              "png_fixture_validation": "signature, chunk CRCs, and decompressed one-pixel scanline passed",
              "checks_passed": checks_passed, "failures": failures, "cells": cells,
              "limitations": ["No full application, browser, authenticated file fetch, provider HTTP request or LLM inference",
                              "Model references are formatted-message evidence, not proof of visual task success",
                              "Streaming slice is narrower evidence than native approval function execution",
                              "Display file record is not browser rendering evidence",
                              "JSONCodec bound to stdlib JSON, corresponding to upstream ENABLE_ORJSON=False",
                              "Fixture oracle is source-informed; controls do not estimate defect prevalence"],
              "paid_api_calls": 0}
    (OUT / "webui-media-probe.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({k: report[k] for k in ["execution_cells", "formatter_observations", "checks_passed", "failures", "paid_api_calls"]}, indent=2))
    return 0 if checks_passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
