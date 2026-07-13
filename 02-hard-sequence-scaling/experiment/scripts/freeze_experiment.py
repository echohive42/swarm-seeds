#!/usr/bin/env python3
"""Create or verify Experiment 02's pre-collection cryptographic freeze."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

FREEZE_SCHEMA_VERSION = "2.1"
DEFAULT_PATTERNS = (
    "PROTOCOL.md", "ANALYSIS_PLAN.md", "CALIBRATION_PLAN.md", "benchmark", "prompts", "scripts",
)
REQUIRED_DISABLED_FEATURES = (
    "apps", "browser_use", "browser_use_external", "browser_use_full_cdp_access",
    "computer_use", "enable_mcp_apps", "goals", "hooks", "image_generation",
    "in_app_browser", "multi_agent", "multi_agent_v2", "plugin_sharing", "plugins",
    "remote_plugin", "shell_tool", "skill_mcp_dependency_install", "standalone_web_search",
    "tool_suggest", "unified_exec", "workspace_dependencies",
)


class FreezeError(ValueError):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _excluded(relative: Path, output_relative: Path) -> bool:
    parts = set(relative.parts)
    return (relative == output_relative or "__pycache__" in parts or relative.suffix in {".pyc", ".pyo"}
            or (relative.parts and relative.parts[0] in {"raw", "results", "packets", "plots"})
            or relative.name in {"attempts.jsonl", ".DS_Store"})


def discover_files(root: Path, patterns: Iterable[str], output: Path) -> list[Path]:
    try:
        output_relative = output.resolve().relative_to(root.resolve())
    except ValueError:
        output_relative = Path("__external_freeze_output__")
    found: set[Path] = set()
    for pattern in patterns:
        matches = list(root.glob(pattern))
        if not matches:
            raise FreezeError(f"freeze input pattern matched nothing: {pattern}")
        for match in matches:
            if match.is_dir():
                found.update(path for path in match.rglob("*") if path.is_file())
            elif match.is_file():
                found.add(match)
    files = sorted((path for path in found
                    if not _excluded(path.resolve().relative_to(root.resolve()), output_relative)),
                   key=lambda path: path.relative_to(root).as_posix())
    if not files:
        raise FreezeError("no immutable files selected")
    return files


def _load_run_manifest_module(root: Path):
    path = root / "scripts" / "run_manifest.py"
    spec = importlib.util.spec_from_file_location("experiment02_run_manifest", path)
    if spec is None or spec.loader is None:
        raise FreezeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _assert_collection_not_started(root: Path, attempt_log: Path | None) -> None:
    candidates = [attempt_log] if attempt_log else []
    candidates.extend([root / "attempts.jsonl", root / "raw" / "final" / "attempts.jsonl"])
    for path in candidates:
        if path and path.exists() and path.stat().st_size:
            raise FreezeError(f"collection already has attempt data: {path}")
    raw_final = root / "raw" / "final"
    if raw_final.is_dir() and any(path.is_file() for path in raw_final.rglob("*")):
        raise FreezeError(f"collection already has raw final artifacts: {raw_final}")


def _verify_prompt_identities(root: Path, run_manifest: dict[str, Any]) -> str:
    identities = run_manifest.get("prompt_identities")
    if not isinstance(identities, dict) or not identities:
        raise FreezeError("run manifest has no frozen prompt identities")
    compact: dict[str, str] = {}
    for identity_id, identity in identities.items():
        components = identity.get("components")
        if not isinstance(components, list) or not components:
            raise FreezeError(f"prompt identity {identity_id} has no components")
        for component in components:
            path = root / component.get("path", "")
            if not path.is_file() or sha256_file(path) != component.get("sha256"):
                raise FreezeError(f"prompt component changed or missing: {path}")
        actual = sha256_bytes(canonical_bytes(components))
        if actual != identity.get("identity_sha256"):
            raise FreezeError(f"prompt identity hash mismatch: {identity_id}")
        compact[identity_id] = actual
    return sha256_bytes(canonical_bytes(compact))


def codex_cli_identity(command: str | Path) -> dict[str, str]:
    located = shutil.which(str(command)) if not Path(command).is_absolute() else str(command)
    if not located:
        raise FreezeError(f"Codex CLI binary not found: {command}")
    real = Path(located).resolve()
    if not real.is_file():
        raise FreezeError(f"Codex CLI binary is not a file: {real}")
    try:
        completed = subprocess.run([str(real), "--version"], capture_output=True, text=True,
                                   timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FreezeError(f"cannot execute Codex CLI version check: {exc}") from exc
    version = completed.stdout.strip() or completed.stderr.strip()
    if completed.returncode != 0 or not version:
        raise FreezeError(f"Codex CLI version check failed with exit {completed.returncode}")
    parts = real.parts
    if "releases" in parts:
        index = parts.index("releases")
        release_locator = "/".join(parts[index + 1:])
    else:
        release_locator = real.name
    # Public records retain a release-relative locator and a hash of the exact
    # resolved path, never a user-specific absolute home-directory path.
    return {"version": version, "release_locator": release_locator,
            "resolved_path_sha256": sha256_bytes(str(real).encode("utf-8")),
            "binary_sha256": sha256_file(real)}


def _inside_root(root: Path, path: Path, label: str) -> Path:
    resolved = path.resolve()
    if not resolved.is_file():
        raise FreezeError(f"missing {label}: {resolved}")
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise FreezeError(f"{label} must be inside the experiment root") from exc
    return resolved


def _validate_gate_and_runtime(
    root: Path,
    run_manifest: dict[str, Any],
    calibration_report_path: Path,
    runtime_config_path: Path,
    codex_binary: str | Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    calibration_path = _inside_root(root, calibration_report_path, "calibration gate report")
    runtime_path = _inside_root(root, runtime_config_path, "runtime config")
    calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    if calibration.get("passed") is not True or calibration.get("decision") != "proceed_to_final_freeze":
        raise FreezeError("calibration gate did not authorize final freeze")
    firewall = calibration.get("correctness_firewall", {})
    if firewall.get("final_inputs_accessed") is not False or firewall.get("final_correctness_inspected") is not False:
        raise FreezeError("calibration report does not preserve the final correctness firewall")
    selected = calibration.get("selected_final_concurrency")
    if selected not in {10, 20}:
        raise FreezeError("calibration report did not select final concurrency 10 or 20")
    if runtime.get("selected_final_concurrency") != selected:
        raise FreezeError("runtime config concurrency does not match calibration")
    if runtime.get("candidate_concurrency") != 20 or runtime.get("timeout_seconds") != 300:
        raise FreezeError("runtime config must preserve candidate concurrency 20 and timeout 300")
    if runtime.get("requested_model") != run_manifest.get("model"):
        raise FreezeError("runtime config model does not match run manifest")
    if runtime.get("calibration_report_sha256") != sha256_file(calibration_path):
        raise FreezeError("runtime config calibration report hash mismatch")
    if list(runtime.get("disabled_features", [])) != list(REQUIRED_DISABLED_FEATURES):
        raise FreezeError("runtime config feature-disable list is incomplete or reordered")
    runner_path = root / "scripts" / "run_codex_cli.py"
    if runtime.get("runner_sha256") != sha256_file(runner_path):
        raise FreezeError("runtime config runner hash mismatch")
    cli = codex_cli_identity(codex_binary)
    if runtime.get("codex_cli_version") != cli["version"] or runtime.get("codex_binary_sha256") != cli["binary_sha256"]:
        raise FreezeError("runtime config Codex CLI identity mismatch")
    expected_manifest_fields = {
        "selected_concurrency": selected,
        "timeout_seconds": 300,
        "codex_cli_version": cli["version"],
        "codex_binary_sha256": cli["binary_sha256"],
        "runner_sha256": runtime["runner_sha256"],
        "calibration_report_sha256": runtime["calibration_report_sha256"],
        "runtime_config_sha256": sha256_file(runtime_path),
    }
    for key, expected in expected_manifest_fields.items():
        if run_manifest.get(key) != expected:
            raise FreezeError(f"run manifest runtime binding mismatch for {key}")
    if list(run_manifest.get("disabled_features", [])) != list(REQUIRED_DISABLED_FEATURES):
        raise FreezeError("run manifest feature-disable list does not match the runtime contract")
    return calibration, runtime, cli


def build_freeze(root: Path, run_manifest_path: Path, output: Path,
                 patterns: Iterable[str] = DEFAULT_PATTERNS, attempt_log: Path | None = None,
                 frozen_at: str | None = None, codex_binary: str | Path = "codex",
                 calibration_report_path: Path | None = None,
                 runtime_config_path: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    run_manifest_path = run_manifest_path.resolve()
    if not run_manifest_path.is_file():
        raise FreezeError(f"missing run manifest: {run_manifest_path}")
    _assert_collection_not_started(root, attempt_log)
    run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    module = _load_run_manifest_module(root)
    try:
        module.validate_manifest(run_manifest)
    except Exception as exc:
        raise FreezeError(f"invalid run manifest: {exc}") from exc
    if run_manifest.get("split") != "final":
        raise FreezeError("final freeze requires the final run manifest")
    if calibration_report_path is None or runtime_config_path is None:
        raise FreezeError("final freeze requires calibration report and runtime config")
    calibration, runtime, cli_identity = _validate_gate_and_runtime(
        root, run_manifest, calibration_report_path, runtime_config_path, codex_binary
    )
    prompt_set_sha256 = _verify_prompt_identities(root, run_manifest)
    files = discover_files(root, patterns, output)
    required_extra = [run_manifest_path, calibration_report_path.resolve(), runtime_config_path.resolve()]
    for required_path in required_extra:
        if required_path not in [path.resolve() for path in files]:
            files.append(required_path)
    files.sort(key=lambda path: path.relative_to(root).as_posix())
    records: dict[str, dict[str, Any]] = {}
    for path in files:
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError as exc:
            raise FreezeError(f"immutable input lies outside experiment root: {path}") from exc
        records[relative] = {"sha256": sha256_file(path), "bytes": path.stat().st_size}
    immutable_set_sha256 = sha256_bytes(canonical_bytes(records))
    try:
        run_relative = run_manifest_path.relative_to(root).as_posix()
    except ValueError as exc:
        raise FreezeError("run manifest must be inside the experiment root") from exc
    freeze: dict[str, Any] = {
        "freeze_schema_version": FREEZE_SCHEMA_VERSION,
        "experiment_id": run_manifest["experiment_id"],
        "frozen_at": frozen_at or utc_now(),
        "collection_started": False,
        "model": run_manifest["model"],
        "condition_mapping": run_manifest["condition_mapping"],
        "run_manifest_path": run_relative,
        "run_manifest_sha256": records[run_relative]["sha256"],
        "run_manifest_identity_sha256": run_manifest["manifest_sha256"],
        "prompt_set_identity_sha256": prompt_set_sha256,
        "planned_call_count": run_manifest["planned_call_count"],
        "planned_case_response_count": run_manifest["planned_case_response_count"],
        "max_infrastructure_retries": run_manifest["max_infrastructure_retries"],
        "selected_final_concurrency": calibration["selected_final_concurrency"],
        "timeout_seconds": runtime["timeout_seconds"],
        "calibration_report_path": calibration_report_path.resolve().relative_to(root).as_posix(),
        "calibration_report_sha256": sha256_file(calibration_report_path),
        "runtime_config_path": runtime_config_path.resolve().relative_to(root).as_posix(),
        "runtime_config_sha256": sha256_file(runtime_config_path),
        "codex_cli": cli_identity,
        "immutable_files": records,
        "immutable_set_sha256": immutable_set_sha256,
    }
    freeze["freeze_manifest_sha256"] = sha256_bytes(canonical_bytes(freeze))
    return freeze


def verify_freeze(path: Path, root: Path | None = None, codex_binary: str | Path | None = None) -> dict[str, Any]:
    freeze = json.loads(path.read_text(encoding="utf-8"))
    if freeze.get("freeze_schema_version") != FREEZE_SCHEMA_VERSION:
        raise FreezeError("unsupported freeze manifest version")
    copy = dict(freeze)
    recorded = copy.pop("freeze_manifest_sha256", None)
    if recorded != sha256_bytes(canonical_bytes(copy)):
        raise FreezeError("freeze manifest self-hash mismatch")
    root = (root or path.parent).resolve()
    records = freeze.get("immutable_files")
    if not isinstance(records, dict) or not records:
        raise FreezeError("freeze contains no immutable file records")
    if freeze.get("immutable_set_sha256") != sha256_bytes(canonical_bytes(records)):
        raise FreezeError("immutable-set identity mismatch")
    for relative, record in records.items():
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise FreezeError(f"unsafe immutable path: {relative}") from exc
        if not candidate.is_file():
            raise FreezeError(f"frozen file is missing: {relative}")
        if candidate.stat().st_size != record.get("bytes") or sha256_file(candidate) != record.get("sha256"):
            raise FreezeError(f"frozen file changed: {relative}")
    run_path = root / freeze["run_manifest_path"]
    run = json.loads(run_path.read_text(encoding="utf-8"))
    if run.get("manifest_sha256") != freeze.get("run_manifest_identity_sha256"):
        raise FreezeError("run manifest identity no longer matches freeze")
    if sha256_file(run_path) != freeze.get("run_manifest_sha256"):
        raise FreezeError("run manifest file hash no longer matches freeze")
    if _verify_prompt_identities(root, run) != freeze.get("prompt_set_identity_sha256"):
        raise FreezeError("render-source prompt identity no longer matches freeze")
    if codex_binary is not None and codex_cli_identity(codex_binary) != freeze.get("codex_cli"):
        raise FreezeError("Codex CLI version, resolved release path, or binary hash drifted after freeze")
    return freeze


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _self_test() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "scripts").mkdir()
        source_scripts = Path(__file__).resolve().parent
        for name in ("run_manifest.py", "freeze_experiment.py"):
            (root / "scripts" / name).write_bytes((source_scripts / name).read_bytes())
        (root / "scripts" / "run_codex_cli.py").write_text("# frozen fixture runner\n", encoding="utf-8")
        prompts = root / "prompts"
        prompts.mkdir()
        run_module = _load_run_manifest_module(root)
        names = {"COMMON_PREFIX.txt", "ROLE_CATALOG.json", "SCHEMAS.json"}
        for roles in run_module.ROLE_PLAN.values():
            names.update(role[2] for role in roles)
        for name in names:
            (prompts / name).write_text(f"frozen {name}\n", encoding="utf-8")
        (root / "benchmark").mkdir()
        cases = [{"case_id": f"RW-{i:03d}", "prefix": ["1"]} for i in range(1, 49)]
        (root / "benchmark" / "final.json").write_text(json.dumps(cases), encoding="utf-8")
        (root / "PROTOCOL.md").write_text("frozen protocol\n", encoding="utf-8")
        (root / "ANALYSIS_PLAN.md").write_text("frozen analysis\n", encoding="utf-8")
        (root / "CALIBRATION_PLAN.md").write_text("frozen calibration\n", encoding="utf-8")
        fake_codex = root / "codex"
        fake_codex.write_text("#!/bin/sh\necho codex-cli 0.144.3\n", encoding="utf-8")
        fake_codex.chmod(0o755)
        calibration_path = root / "calibration_gate.json"
        calibration = {
            "passed": True,
            "decision": "proceed_to_final_freeze",
            "selected_final_concurrency": 20,
            "correctness_firewall": {
                "final_inputs_accessed": False,
                "final_correctness_inspected": False,
            },
        }
        calibration_path.write_text(json.dumps(calibration), encoding="utf-8")
        cli_identity = codex_cli_identity(fake_codex)
        runtime_path = root / "runtime_config.json"
        runtime = {
            "selected_final_concurrency": 20,
            "candidate_concurrency": 20,
            "timeout_seconds": 300,
            "requested_model": "gpt-5.6-luna",
            "codex_cli_version": cli_identity["version"],
            "codex_binary_sha256": cli_identity["binary_sha256"],
            "runner_sha256": sha256_file(root / "scripts" / "run_codex_cli.py"),
            "calibration_report_sha256": sha256_file(calibration_path),
            "disabled_features": list(REQUIRED_DISABLED_FEATURES),
        }
        runtime_path.write_text(json.dumps(runtime), encoding="utf-8")
        run = run_module.build_manifest(
            cases, prompts, runtime_config=runtime, runtime_config_sha256=sha256_file(runtime_path)
        )
        run_path = root / "run_manifest.json"
        run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
        output = root / "freeze_manifest.json"
        freeze = build_freeze(
            root, run_path, output, frozen_at="2026-01-01T00:00:00Z", codex_binary=fake_codex,
            calibration_report_path=calibration_path, runtime_config_path=runtime_path,
        )
        atomic_write_json(output, freeze)
        assert verify_freeze(output)["planned_call_count"] == 400
        (root / "PROTOCOL.md").write_text("changed\n", encoding="utf-8")
        try:
            verify_freeze(output)
        except FreezeError:
            pass
        else:
            raise AssertionError("verification accepted a changed protocol")
    print("freeze_experiment.py self-test: PASS")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Freeze or verify all pre-collection Experiment 02 identities.")
    parser.add_argument("--self-test", action="store_true")
    sub = parser.add_subparsers(dest="command")
    create = sub.add_parser("create", help="hash immutable inputs before the first final attempt")
    create.add_argument("--experiment-root", type=Path, required=True)
    create.add_argument("--run-manifest", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--include", action="append", dest="patterns", help="root-relative file or glob; repeatable")
    create.add_argument("--attempt-log", type=Path)
    create.add_argument("--codex-binary", required=True,
                        help="versioned Codex CLI release binary (resolved path/hash are frozen)")
    create.add_argument("--calibration-report", type=Path, required=True,
                        help="passing aggregate calibration-gate JSON inside the experiment root")
    create.add_argument("--runtime-config", type=Path, required=True,
                        help="calibration-bound final runtime JSON inside the experiment root")
    create.add_argument("--overwrite", action="store_true", help="replace an existing pre-collection freeze intentionally")
    verify = sub.add_parser("verify", help="rehash every listed file and prompt identity")
    verify.add_argument("freeze_manifest", type=Path)
    verify.add_argument("--experiment-root", type=Path)
    verify.add_argument("--codex-binary", help="also abort on CLI version/path/hash drift")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            _self_test()
            return 0
        if args.command == "create":
            if args.output.exists() and not args.overwrite:
                raise FreezeError(f"refusing to overwrite {args.output}; pass --overwrite intentionally")
            freeze = build_freeze(args.experiment_root, args.run_manifest, args.output,
                                  args.patterns or DEFAULT_PATTERNS, args.attempt_log,
                                  codex_binary=args.codex_binary,
                                  calibration_report_path=args.calibration_report,
                                  runtime_config_path=args.runtime_config)
            atomic_write_json(args.output, freeze)
            print(f"froze {len(freeze['immutable_files'])} files: {args.output}")
            return 0
        if args.command == "verify":
            freeze = verify_freeze(args.freeze_manifest, args.experiment_root, args.codex_binary)
            print(f"verified {len(freeze['immutable_files'])} frozen files: {args.freeze_manifest}")
            return 0
        parser.print_help()
        return 2
    except (FreezeError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
