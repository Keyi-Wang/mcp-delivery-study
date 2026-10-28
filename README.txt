MCP Result Delivery Study
=========================

Reproduction artifact for:
When Passing Tests Disagree: An Empirical Study of MCP Result Delivery
Keyi Wang, East China Normal University
Contact: keyiwang1010@gmail.com
Repository: https://github.com/Keyi-Wang/mcp-delivery-study

This artifact examines whether information returned by an MCP tool survives
integration code and reaches the intended recipient. It includes pinned source
snapshots, original test assertions, controlled executions, raw observations,
selection records, task contracts, and table-generation scripts.

QUICK START
-----------
From a checkout of this repository:

  python3 scripts/verify_artifact.py
  python3 scripts/mcp_review_reproduce.py --install --all

Use a fresh checkout when checking the manifest: reproduction overwrites generated
results. Omit --all to execute only the main producer/consumer case and independent producer contrast.
After dependencies are installed, omit --install on subsequent runs.

Requirements: Linux/POSIX environment, Python 3 with venv/pip, Git, and Node/npm
for --all. The installation creates project-local virtual environments using
uv 0.13.5. The main case uses Python 3.13.17; historical contrasts use Python 3.10.
The TypeScript contrast was validated with Node 16.20.2 and TypeScript 5.7.3.
Installation requires network access to download Python runtimes and pinned
packages. No global packages are modified. The experiments use local processes,
stdio, temporary Git repositories and loopback HTTP. No model-service credential
is needed; these experiments perform no model inference.

WHAT SHOULD REPRODUCE
---------------------
Main case: the original UniFi build_server application, its built-in controller
stub, and the native Hermes MCP client/handler. The controller seed realization is
fixed; the second state is an explicitly authored sensitivity condition. Neither
state is a recording from a production network.

  Selected UniFi test modules:                         50/50 pass
  Selected Hermes test classes:                        7/7 pass
  Live stdio calls:                            8
  Exact live-output/replay agreements:          8/8

Across four task/state conditions (WAN status/address and WLAN name/enabled):

  Strategy              Required facts   Count-only controls   Output bytes
  Text priority         0/4              2/2                   318
  Structure control     4/4              2/2                   1089
  Combination control   4/4              2/2                   1451
  Native full text      4/4              2/2                   1587

These are deterministic contract checks, not model task-accuracy measurements.
Full-object retention, required-fact retention, excluded values, and byte counts
are reported separately. The synthetic password used in an exclusion control is
from an upstream test, not an actual credential.

The count-only oracle accepts explicit counts or complete record-list lengths,
without inspecting WLAN names or enabled values. In addition to the original
one-record controls, four native calls exercise empty/two-record producer states;
all eight policy-level count checks pass. Fourteen instrument checks include
wrong counts, field-independent lists, unrelated metadata, truncated JSON and
conflicting summary/list counts. The original task/policy totals above are unchanged.

Policy identifiers distinguish operations:
  native_full_text: real UniFi force_full_text_responses setting, new producer call;
  authored_append_json: append serialized structuredContent to the original text
                        in an authored diagnostic; not the UniFi configuration.
The initial commit used full_text_fallback for both. The frozen original contract
is preserved; research/mcp-count-oracle-amendment.json records the clarified
identifiers and count-oracle correction before the additional checks were run.

A separate official Git MCP producer retains its known text commit message through
the same Hermes path. It is a working contrast, not another loss incident.

With --all, the runner also regenerates Agno, historical Hermes, Open WebUI,
Superset, LangChain and AdCP contrasts. Cross-version tests intentionally produce
some failing assertions: the matrix is the observation. A failed cross-version
assertion is not by itself proof of semantic loss. Unexpected harness/runtime
failures cause reproduction to exit unsuccessfully. The final table builders
check the retained matrix and primary evidence invariants.

READING THE EVIDENCE
--------------------
Start with artifacts/mcp-review-revision/:

  continuous-results.json       Complete received results and handler outputs
  task-contract-results.json    Facts, counts, exclusions, bytes, actions and oracle checks
  count-control-live-results.json  Four additional native empty/two-record calls
  replay-agreement.json         Exact live-versus-replay comparisons
  confirmation-results.json     Independent producer contrast
  execution-inventory.json      Native and replaced components; execution limits
  source-manifest.json           Pinned commits, Git blobs and SHA-256 hashes
  table-traceability.json        Five paper tables and timeline mapped to evidence
  harness-corrections.json       Setup/oracle corrections, not product defects

research/mcp-review-contracts.json contains the frozen main task contracts.
Other research/ files document fixture provenance and experimental design.
The task sources were inspected before validation: these are not blind holdouts.

artifacts/mcp-acceptance-study/completed-screening.json records the
87 unique candidates from six capped searches, their screening stages, decisions
and limitations. selection-and-execution-audit.json includes the extended ledger
and source issue/PR links. search-round1.json retains the retrieved search evidence.
These are frozen selection records, not outputs regenerated by the experiment
runner. They do not establish ecosystem prevalence or exhaustive coverage.

The remaining artifact directories contain historical test and transport results,
fixtures, source manifests and dependency locks. Directories identify the study stages. A directory or script name containing
"review" identifies the
revision experiment batch; it does not imply external reviewer endorsement.

Generated table fragments and the hash-linked evidence index are in tables/.
Table I uses the selection audit; Table II uses original cross-version tests;
Table III uses the main task/policy comparison; Table IV uses actual Agno follow-up
HTTP request captures. Table V maps cases to maintenance checks using
research/mcp-cross-case-synthesis.json. See table-traceability.json for exact files and keys.

After reproduction, one-command-reproduction.json reports executed steps and eight
comparisons with the retained primary observations. Diagnostic logs are written
locally under reproduction-logs/ and are not part of the versioned release.

SCOPE AND LIMITATIONS
---------------------
This is a selected-case, source-informed empirical study. Counts of executions,
assertions, cells and projects are different units and must not be summed as a
sample size or a defect count. Local reruns do not establish production frequency,
end-to-end agent success, latency, token cost or user benefit. The historical
contrasts have different observation boundaries; consult execution-inventory.json.
Independent human case review has not been completed.

The release omits manuscript drafts and operational records. Non-experimental
publication-planning fields are omitted from design documents; the frozen main
task contract, test assertions, observed outcomes and source bytes are retained.
Machine-local path prefixes in generated reports are normalized to <ARTIFACT_ROOT>
and <DEPENDENCY_ROOT>. Test-report wall-clock timestamps and hostnames are omitted;
test counts, outcomes and durations are retained. Paths use study-stage names.
These packaging conventions do not change experimental observations. Relative
ordering of protocols, amendments and runs is retained. Search cutoff dates define
the sampled corpus; upstream event dates support the longitudinal analysis. The
Git contrast uses a predetermined synthetic commit date/message as test input,
not a record of execution time. Prior package versions remain in Git history. Upstream source snapshots
remain byte-identical to their pinned versions. No blanket license is asserted
for third-party files: see NOTICE.txt and the retained upstream licenses.

For an immutable reference, use the full Git commit hash of this checkout.
