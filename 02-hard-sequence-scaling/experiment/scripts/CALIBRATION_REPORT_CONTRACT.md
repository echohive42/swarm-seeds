# Calibration gate input contract

`evaluate_calibration.py` converts the Experiment 02 development, calibration,
and operational records into one aggregate pass or fail report. It does not
accept a final manifest or a final answer file.

## Command

```text
python3 scripts/evaluate_calibration.py \
  --development-manifest <development-run-manifest.json> \
  --development-attempts <development-attempts.jsonl> \
  --calibration-manifest <calibration-run-manifest.json> \
  --calibration-attempts <calibration-attempts.jsonl> \
  --calibration-truth benchmark/hidden/calibration_answers.jsonl \
  --benchmark-manifest benchmark/manifest.json \
  --preflight-report <preflight.json> \
  --pipeline-report <pipeline-audit.json> \
  --load-report <load-report.json> \
  --candidate-number 1 \
  --output <calibration-gate.json>
```

The benchmark manifest checksum is verified before the calibration truth file
is opened. This prevents a renamed or substituted truth file from entering the
gate.

Candidate number is always `1`. This protocol defines no reserve set and no
replacement candidate. Any calibration failure stops Experiment 02 and moves
redesign to a new protocol version.

## Preflight report

The preflight report is a JSON object. These fields must be `true`:

```text
model_catalog_verified
runner_fixture_passed
prompt_via_stdin
ignore_user_config
ephemeral_sessions
fresh_empty_workdirs
read_only_sandbox
stage_output_schemas
stdout_jsonl_preserved
stderr_preserved
exit_status_preserved
standard_library_only
no_resume_code_path
retry_requires_no_agent_message
```

It must also contain:

```json
{
  "requested_model": "gpt-5.6-luna",
  "timeout_seconds": 300,
  "candidate_concurrency": 20,
  "codex_cli_version": "codex-cli 0.144.3",
  "usage_telemetry_status": "available or unavailable",
  "disabled_features": [
    "apps",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
    "computer_use",
    "enable_mcp_apps",
    "goals",
    "hooks",
    "image_generation",
    "in_app_browser",
    "multi_agent",
    "multi_agent_v2",
    "plugin_sharing",
    "plugins",
    "remote_plugin",
    "shell_tool",
    "skill_mcp_dependency_install",
    "standalone_web_search",
    "tool_suggest",
    "unified_exec",
    "workspace_dependencies"
  ]
}
```

## Pipeline audit report

The pipeline audit is a JSON object. These fields must be `true`:

```text
swarm10_fixture_passed
routing_graph_valid
reasoning_isolation_valid
clean_room_replay_identical
malformed_fixture_rejected
retry_identity_preserved
packet_manifest_reproducible
raw_jsonl_reproduces_agent_messages
stderr_exit_joinable
no_packet_over_input_limit
no_silent_response_truncation
no_answer_key_used_for_pipeline_checks
command_contract_all_calls
```

## Load report

The load report identifies one frozen 20-call independent calibration pool.
Its top level fields are:

```json
{
  "candidate_concurrency": 20,
  "timeout_seconds": 300,
  "max_active_processes": 20,
  "deadlock": false,
  "calls": []
}
```

Each of the 20 call records contains:

```json
{
  "call_id": "frozen manifest call ID"
}
```

The evaluator derives first-attempt status, retry resolution, maximum attempt
latency, timeout state, JSONL integrity, final-message presence, process start,
crash state, operating-system kill or resource exhaustion, session reuse, and
resource warnings from the append-only calibration attempt log. Every attempt
in the selected pool must carry that operational telemetry. The load report is
therefore responsible only for identifying the frozen pool and recording the
runner-level maximum active process count and deadlock state.

The evaluator selects final concurrency 20 only when every monitored condition
passes. Otherwise it selects 10. A stable fallback to 10 can still pass the
overall gate, but missing evidence, unresolved calls, session reuse, or corrupt
JSONL blocks the final freeze.

## Output privacy

The output includes only aggregate schema counts, Direct accuracy, Vote10 and
Vote20 accuracy, tier totals, operational counts, hashes, and pass or fail
checks. It does not include case IDs, predictions, case-level correctness, or
final data.
