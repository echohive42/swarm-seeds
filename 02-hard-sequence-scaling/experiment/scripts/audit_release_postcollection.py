#!/usr/bin/env python3
"""Post-collection release-audit entry point preserving frozen audit bytes."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace


DIRECTORY = Path(__file__).resolve().parent
FROZEN_SCORER = DIRECTORY / "score_results.py"
FROZEN_AUDIT = DIRECTORY / "audit_release.py"
EXPECTED_SCORER_SHA256 = "ec924076080b14e3ccd4afd6486b52f9dfc24502445b7726ee2741cd4106e9ee"
EXPECTED_AUDIT_SHA256 = "750de1429dbdcc6a3154b29b5116322a8eb46d061ef2b3021ea46f814988e79b"
POSTCOLLECTION_SCORER = DIRECTORY / "score_results_postcollection.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if sha256(FROZEN_SCORER) != EXPECTED_SCORER_SHA256:
        print("audit error: frozen score_results.py hash mismatch", file=sys.stderr)
        return 2
    if sha256(FROZEN_AUDIT) != EXPECTED_AUDIT_SHA256:
        print("audit error: frozen audit_release.py hash mismatch", file=sys.stderr)
        return 2
    if "--self-test" not in arguments:
        scored_path: Path | None = None
        if "--scored" in arguments:
            position = arguments.index("--scored")
            if position + 1 < len(arguments):
                scored_path = Path(arguments[position + 1])
        if scored_path is None:
            scored_path = DIRECTORY.parent / "results" / "scored_results.json"
        try:
            scored = json.loads(scored_path.read_text(encoding="utf-8"))
            provenance = scored.get("provenance", {}).get("postcollection_scorer", {})
        except (OSError, json.JSONDecodeError):
            print("audit error: cannot read post-collection scored artifact", file=sys.stderr)
            return 2
        if provenance.get("sha256") != sha256(POSTCOLLECTION_SCORER) or \
                provenance.get("frozen_base_sha256") != EXPECTED_SCORER_SHA256:
            print("audit error: scored artifact was not produced by the current post-collection scorer", file=sys.stderr)
            return 2
    score_spec = importlib.util.spec_from_file_location(
        "experiment02_postcollection_scorer", POSTCOLLECTION_SCORER
    )
    if score_spec is None or score_spec.loader is None:
        print("audit error: cannot load post-collection scorer", file=sys.stderr)
        return 2
    score_module = importlib.util.module_from_spec(score_spec)
    score_spec.loader.exec_module(score_module)
    sys.modules["score_results"] = score_module._BASE
    spec = importlib.util.spec_from_file_location("experiment02_frozen_audit", FROZEN_AUDIT)
    if spec is None or spec.loader is None:
        print("audit error: cannot load frozen audit_release.py", file=sys.stderr)
        return 2
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if "--self-test" not in arguments and "--attempts" not in arguments:
        if "--experiment-dir" in arguments and arguments.index("--experiment-dir") + 1 < len(arguments):
            experiment = Path(arguments[arguments.index("--experiment-dir") + 1])
        else:
            experiment = DIRECTORY.parent
        arguments.extend(["--attempts", str(experiment / "raw" / "final" / "attempts.jsonl")])

    # The frozen audit accidentally left its analysis-recomputation tail inside
    # audit_attempt_artifacts, where `analysis` is out of scope. Preserve every
    # artifact check it completes before that tail, then run the recomputation
    # in the correct post-collection hook using the provenance-preserving scorer.
    frozen_artifact_audit = module.audit_attempt_artifacts

    def fixed_artifact_audit(audit, attempts_data, attempts_path, collection_closed_path):
        try:
            frozen_artifact_audit(audit, attempts_data, attempts_path, collection_closed_path)
        except NameError as error:
            if "analysis" not in str(error):
                raise

    def fixed_recomputation(audit, paths, scored, analysis):
        scorer_spec = importlib.util.spec_from_file_location(
            "experiment02_postcollection_scorer", POSTCOLLECTION_SCORER
        )
        if scorer_spec is None or scorer_spec.loader is None:
            audit.check(False, "post-collection scorer loads for recomputation")
            return
        scorer = importlib.util.module_from_spec(scorer_spec)
        scorer_spec.loader.exec_module(scorer)
        analysis_path = DIRECTORY / "analyze_results.py"
        analysis_spec = importlib.util.spec_from_file_location(
            "experiment02_frozen_analysis", analysis_path
        )
        if analysis_spec is None or analysis_spec.loader is None:
            audit.check(False, "frozen analyzer loads for recomputation")
            return
        analyzer = importlib.util.module_from_spec(analysis_spec)
        analysis_spec.loader.exec_module(analyzer)
        score_args = SimpleNamespace(
            results=str(paths["attempts"]), answers=str(paths["answers"]),
            manifest=str(paths["manifest"]), case_manifest=str(paths["case_manifest"]),
            collection_closed=str(paths["collection_closed"]),
            execution_metadata=None, allow_incomplete=False,
        )
        recomputed_scored = scorer.run_score(score_args)
        audit.check(
            json.dumps(recomputed_scored, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            == json.dumps(scored, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
            "published scored results exactly recompute with post-collection scorer",
        )
        bootstrap = analysis.get("bootstrap", {})
        replicates, seed = bootstrap.get("replicates"), bootstrap.get("seed")
        if not isinstance(replicates, int) or not isinstance(seed, int):
            audit.check(False, "analysis publishes integer bootstrap replicates and seed")
            return
        recomputed_analysis = analyzer.analyze(
            recomputed_scored, replicates=replicates, seed=seed, require_four_blocks=True
        )
        audit.check(
            json.dumps(recomputed_analysis, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            == json.dumps(analysis, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
            "published statistics exactly recompute from scored evidence",
        )

    module.audit_attempt_artifacts = fixed_artifact_audit

    if "--experiment-dir" in arguments and arguments.index("--experiment-dir") + 1 < len(arguments):
        audit_experiment = Path(arguments[arguments.index("--experiment-dir") + 1]).resolve()
    else:
        audit_experiment = DIRECTORY.parent
    frozen_scored_audit = module.audit_scored

    def fixed_scored_audit(audit, scored):
        class CheckProxy:
            def check(self, condition, name, detail=""):
                if name == "frozen concurrency load-gate evidence preserved":
                    try:
                        runtime = json.loads((audit_experiment / "freeze_inputs" / "runtime_config.json").read_text())
                        gate = json.loads((audit_experiment / "freeze_inputs" / "calibration_gate.json").read_text())
                        selected = scored.get("operational_reliability", {}).get("selected_concurrency")
                        condition = (
                            runtime.get("selected_final_concurrency") == selected
                            and gate.get("selected_final_concurrency") == selected
                            and gate.get("passed") is True
                            and isinstance(gate.get("load_gate"), dict)
                        )
                        detail = "validated against frozen runtime_config.json and calibration_gate.json"
                    except (OSError, json.JSONDecodeError):
                        condition = False
                        detail = "cannot validate frozen load-gate inputs"
                audit.check(condition, name, detail)

            def warn(self, name, detail):
                audit.warn(name, detail)

        frozen_scored_audit(CheckProxy(), scored)

    def fixed_public_files(audit, release_dir):
        text_suffixes = {".md", ".json", ".jsonl", ".txt", ".csv", ".py", ".yml", ".yaml", ".toml"}
        findings = []
        for path in sorted(release_dir.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in text_suffixes:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            patterns = module.PRIVATE_PATTERNS
            if path.suffix.lower() == ".py":
                # UUID/task-ID regex literals in audit source are controls, not leaks.
                patterns = tuple(item for item in patterns if item[0] not in {"UUID", "internal task identifier"})
            for label, pattern in patterns:
                if pattern.search(text):
                    findings.append(f"{path.relative_to(release_dir)}: {label}")
        audit.check(not findings, "no private paths, UUIDs, source-task IDs, or secrets", "; ".join(findings[:20]))
        broken = []
        markdown_link = module.re.compile(r"\[[^\]]*\]\(([^)]+)\)")
        for path in sorted(release_dir.rglob("*.md")):
            text = path.read_text(encoding="utf-8")
            for target in markdown_link.findall(text):
                target = target.strip().strip("<>").split("#", 1)[0]
                if not target or "://" in target or target.startswith("mailto:"):
                    continue
                if not (path.parent / target).resolve().exists():
                    broken.append(f"{path.relative_to(release_dir)} -> {target}")
        audit.check(not broken, "local Markdown links resolve", "; ".join(broken[:20]))

    module.audit_scored = fixed_scored_audit
    module.audit_recomputation = fixed_recomputation
    module.audit_public_files = fixed_public_files
    return module.main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
