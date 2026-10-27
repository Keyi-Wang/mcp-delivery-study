"""Execute pinned Hermes modules with real MCP types and a controlled session.

Native handler output is observed, not a provider request or actual model answer.
Inputs are authored source-shaped controls; no credentials or private data used.
"""
import asyncio
import hashlib
import importlib.util
import json
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace

from mcp.types import CallToolResult, TextContent

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/mcp-preservation-study-20261026"


def load(label):
    record = next(r for r in json.loads((OUT / "source-manifest.json").read_text()) if r["label"] == label)
    path = OUT / record["local"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]
    spec = importlib.util.spec_from_file_location(label.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Session:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    async def call_tool(self, name, arguments):
        assert name == "read_status" and arguments == {}
        self.calls += 1
        return self.response.model_copy(deep=True)


def main():
    marker = "WAN2_DOWN_PROBE"
    structured = {"wan2": {"state": marker}}
    file_text = 'NAME="ResearchFixtureOS"\nVERSION="1.0"'
    fixtures = [
        ("text_only", file_text, None, False, ["ResearchFixtureOS"]),
        ("structured_only", None, structured, False, [marker]),
        ("summary_plus_data", "get_wan_status completed. Full result is in structuredContent.", structured, False, [marker]),
        ("file_plus_metadata", file_text, {"fileName": "os-release", "fileType": "text"}, False, ["ResearchFixtureOS"]),
        ("equivalent_dual", json.dumps(structured), structured, False, [marker]),
        ("text_error", "Record not found", None, True, ["Record not found"]),
    ]
    rows = []
    for label in ["hermes-before", "hermes-structured-first", "hermes-combined"]:
        module = load(label)
        # The original handler and its error formatting execute unchanged.
        # Only the external session and background scheduler are replaced.
        module._run_on_mcp_loop = lambda coro, timeout: asyncio.run(coro)
        for name, text, data, error, required in fixtures:
            result = CallToolResult(content=[] if text is None else [TextContent(type="text", text=text)],
                                    structuredContent=data, isError=error)
            session = Session(result)
            module._servers["offline"] = SimpleNamespace(session=session)
            output = module._make_tool_handler("offline", "read_status", 5.0)({})
            assert session.calls == 1
            decoded = json.loads(output)
            rows.append({"version": label, "case": name, "sdk_input": result.model_dump(by_alias=True, exclude_none=True),
                         "native_handler_output": decoded, "required_atoms": required,
                         "preserved_atoms": [atom for atom in required if atom in output],
                         "all_required_atoms_preserved": all(atom in output for atom in required)})
    def passed(label, case):
        return next(r["all_required_atoms_preserved"] for r in rows if r["version"] == label and r["case"] == case)
    assert not passed("hermes-before", "structured_only")
    assert not passed("hermes-before", "summary_plus_data")
    assert passed("hermes-structured-first", "summary_plus_data")
    assert passed("hermes-before", "file_plus_metadata")
    assert not passed("hermes-structured-first", "file_plus_metadata")
    assert all(r["all_required_atoms_preserved"] for r in rows if r["version"] == "hermes-combined")
    report = {"kind": "native_handler_historical_repair_chain", "dependency_versions": {"mcp": version("mcp")},
              "source_issues": ["https://github.com/NousResearch/hermes-agent/issues/5874", "https://github.com/NousResearch/hermes-agent/issues/7043"],
              "source_fixes": ["https://github.com/NousResearch/hermes-agent/pull/5979", "https://github.com/NousResearch/hermes-agent/pull/7118"],
              "rows": rows, "paid_api_calls": 0,
              "limits": ["Whole pinned handler modules imported; session and loop scheduling replaced by controlled stand-ins.",
                         "Real MCP CallToolResult types used; values are authored, not production recordings.",
                         "Observed handler output, not final provider request or downstream model answer.",
                         "Three historical source versions share one dependency environment; not complete historical installations.",
                         "Six inputs are controls, not six independent bug incidents.",
                         "September regression is source-reviewed separately and is not executed here."]}
    collisions = []
    for label in ["hermes-before", "hermes-structured-first", "hermes-combined"]:
        module = load(label)
        module._run_on_mcp_loop = lambda coro, timeout: asyncio.run(coro)
        for task in ["wan_status", "file_value"]:
            observations = []
            for answer in ["ALPHA_PROBE", "BETA_PROBE"]:
                if task == "wan_status":
                    text = "get_wan_status completed. Full result is in structuredContent."
                    data = {"wan2": {"state": answer}}
                else:
                    text = f'NAME="{answer}"'
                    data = {"fileName": "os-release", "fileType": "text"}
                result = CallToolResult(content=[TextContent(type="text", text=text)], structuredContent=data)
                module._servers["offline"] = SimpleNamespace(session=Session(result))
                observed = module._make_tool_handler("offline", "read_status", 5.0)({})
                observations.append({"answer": answer, "source_result": result.model_dump(by_alias=True, exclude_none=True), "observed": observed})
            collisions.append({"version": label, "task": task, "observations": observations,
                               "different_answers_same_observation": observations[0]["observed"] == observations[1]["observed"]})
    assert [r['different_answers_same_observation'] for r in collisions] == [True, False, False, True, False, False]
    report['counterfactual_collision_controls'] = collisions
    report['collision_interpretation'] = 'Constructed same-question pairs differ only in the answer-bearing source value. Equal observed handler output cannot distinguish those values without another information source. This is an observation-boundary result, not measured LLM accuracy or a natural task distribution.'
    (OUT / "hermes-repair-chain.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({label: {r["case"]: r["all_required_atoms_preserved"] for r in rows if r["version"] == label}
                      for label in ["hermes-before", "hermes-structured-first", "hermes-combined"]}, indent=2))


if __name__ == "__main__":
    main()
