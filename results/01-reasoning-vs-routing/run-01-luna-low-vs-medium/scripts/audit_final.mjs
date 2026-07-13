import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";

const root = path.resolve(fileURLToPath(new URL("../", import.meta.url)));
const read = file => JSON.parse(fs.readFileSync(path.join(root, file), "utf8"));
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const arms = ["low", "medium"];
const stages = ["proposers", "critics", "verifiers", "judge"];
const freeze = read("freeze_manifest.json");
const manifest = read("benchmark/manifest.json");
const finalCases = manifest.final;
const finalIds = finalCases.map(x => x.id);
const checks = {};
const details = {};

const changedFrozenFiles = [];
for (const [file, expectedHash] of Object.entries(freeze.immutable_files)) {
  const actualHash = crypto.createHash("sha256")
    .update(fs.readFileSync(path.join(root, file)))
    .digest("hex");
  if (actualHash !== expectedHash) changedFrozenFiles.push(file);
}
details.changed_frozen_files = changedFrozenFiles;
checks.freeze_file_count = Object.keys(freeze.immutable_files).length === 20;
checks.frozen_hashes_unchanged = changedFrozenFiles.length === 0;
checks.final_was_empty_at_freeze = freeze.final_thread_count_before_freeze === 0;
checks.development_gate_passed = read("development_audit.json").all_checks_pass === true;

const byArm = {};
const records = [];
for (const arm of arms) {
  const independentDir = path.join(root, "raw/final", arm, "independent");
  const independent = fs.readdirSync(independentDir)
    .filter(x => /^r\d+\.json$/.test(x))
    .sort()
    .map(x => JSON.parse(fs.readFileSync(path.join(independentDir, x), "utf8")));
  const collaboration = [];
  for (const stage of stages) {
    const dir = path.join(root, "raw/final", arm, "collaboration", stage);
    for (const file of fs.readdirSync(dir).filter(x => x.endsWith(".json")).sort()) {
      collaboration.push(JSON.parse(fs.readFileSync(path.join(dir, file), "utf8")));
    }
  }
  byArm[arm] = { independent, collaboration };
  records.push(...independent, ...collaboration);
}

checks.subject_records = records.length === 40;
checks.unique_successful_thread_ids = new Set(records.map(x => x.thread_id)).size === 40;
checks.all_successful_threads_luna = records.every(x => x.requested_model === "gpt-5.6-luna");
checks.reasoning_matches_arm = records.every(x => x.requested_reasoning === x.arm);
checks.all_successful_threads_archived = records.every(x => x.archived === true);
checks.equal_arm_calls = arms.every(arm => records.filter(x => x.arm === arm).length === 20);
checks.independent_budget = arms.every(arm => byArm[arm].independent.length === 10);
checks.collaboration_budget = arms.every(arm => byArm[arm].collaboration.length === 10);
checks.equal_ensemble_collaboration_budget = arms.every(arm =>
  byArm[arm].independent.length === byArm[arm].collaboration.length
);
checks.collaboration_structure = arms.every(arm => {
  const x = byArm[arm].collaboration;
  return x.filter(r => r.stage === "proposer").length === 5 &&
    x.filter(r => r.stage === "critic").length === 2 &&
    x.filter(r => r.stage === "verifier").length === 2 &&
    x.filter(r => r.stage === "judge").length === 1;
});

const solverSchemaProblems = [];
const solverCompliant = raw => {
  if (!Array.isArray(raw.response)) {
    solverSchemaProblems.push({
      arm: raw.arm,
      replicate: raw.replicate,
      thread_id: raw.thread_id,
      problem: "unparseable_or_non_array_response",
      parse_error: raw.parse_error
    });
    return false;
  }
  const problems = [];
  if (raw.response.length !== finalCases.length) problems.push("wrong_case_count");
  const ids = raw.response.map(x => x?.id);
  if (new Set(ids).size !== finalCases.length || !finalIds.every(id => ids.includes(id))) {
    problems.push("missing_duplicate_or_unknown_case_id");
  }
  for (const x of raw.response) {
    if (!Array.isArray(x?.next_three) || x.next_three.length !== 3 ||
        !x.next_three.every(Number.isFinite)) {
      problems.push(`${x?.id ?? "unknown"}:next_three_shape`);
    }
    if (typeof x?.rule !== "string") problems.push(`${x?.id ?? "unknown"}:rule_type`);
    if (!Number.isFinite(x?.confidence) || x.confidence < 0 || x.confidence > 100) {
      problems.push(`${x?.id ?? "unknown"}:confidence`);
    }
  }
  if (problems.length) {
    solverSchemaProblems.push({
      arm: raw.arm,
      replicate: raw.replicate,
      thread_id: raw.thread_id,
      problem: problems
    });
    return false;
  }
  return true;
};
for (const arm of arms) for (const raw of byArm[arm].independent) solverCompliant(raw);
details.solver_schema_problems = solverSchemaProblems;
checks.schema_failures_preserved_and_penalized =
  solverSchemaProblems.length === 2 &&
  solverSchemaProblems.every(x => x.arm === "low") &&
  solverSchemaProblems.some(x => x.replicate === 3) &&
  solverSchemaProblems.some(x => x.replicate === 9);

const packetChecks = [];
const forbiddenPacketKeys = new Set([
  "arm", "split", "method", "stage", "thread_id",
  "requested_model", "requested_reasoning", "archived"
]);
const packetHasForbiddenKey = value => {
  if (Array.isArray(value)) return value.some(packetHasForbiddenKey);
  if (!value || typeof value !== "object") return false;
  return Object.entries(value).some(([key, child]) =>
    forbiddenPacketKeys.has(key) || packetHasForbiddenKey(child)
  );
};
for (const arm of arms) {
  const proposals = read(`packets/final/${arm}/proposals.json`);
  const critiques = read(`packets/final/${arm}/critiques.json`);
  const verifications = read(`packets/final/${arm}/verifications.json`);
  const collab = byArm[arm].collaboration;
  const proposalMatches = ["A", "B", "C", "D", "E"].every(role =>
    same(proposals.proposals[role], collab.find(x => x.stage === "proposer" && x.role === role)?.response)
  );
  const critiqueMatches = ["exactness", "simplicity"].every(role =>
    same(critiques.critiques[role], collab.find(x => x.stage === "critic" && x.role === role)?.response)
  );
  const verificationMatches = ["arithmetic", "rule"].every(role =>
    same(verifications.verifications[role], collab.find(x => x.stage === "verifier" && x.role === role)?.response)
  );
  packetChecks.push({
    arm,
    proposal_matches_same_arm_raw: proposalMatches,
    critique_matches_same_arm_raw: critiqueMatches,
    verification_matches_same_arm_raw: verificationMatches,
    progressive_packet_identity:
      same(proposals.proposals, critiques.proposals) &&
      same(critiques.proposals, verifications.proposals) &&
      same(critiques.critiques, verifications.critiques),
    no_provenance_or_arm_keys:
      !packetHasForbiddenKey(proposals) &&
      !packetHasForbiddenKey(critiques) &&
      !packetHasForbiddenKey(verifications)
  });
}
details.packet_checks = packetChecks;
checks.same_arm_packet_provenance = packetChecks.every(x =>
  x.proposal_matches_same_arm_raw && x.critique_matches_same_arm_raw &&
  x.verification_matches_same_arm_raw && x.progressive_packet_identity
);
checks.packets_anonymized = packetChecks.every(x => x.no_provenance_or_arm_keys);

const judgeChecks = arms.map(arm => {
  const judge = byArm[arm].collaboration.find(x => x.stage === "judge");
  const response = judge?.response;
  const ids = Array.isArray(response) ? response.map(x => x.id) : [];
  return {
    arm,
    twelve_unique_expected_ids:
      response?.length === 12 && new Set(ids).size === 12 && finalIds.every(id => ids.includes(id)),
    strict_triplet_schema: Array.isArray(response) && response.every(x =>
      Array.isArray(x.next_three) && x.next_three.length === 3 && x.next_three.every(Number.isFinite)
    )
  };
});
details.judge_checks = judgeChecks;
checks.judge_outputs_complete = judgeChecks.every(x =>
  x.twelve_unique_expected_ids && x.strict_triplet_schema
);

const failedAttempts = read("raw/final/independent_failed_attempts_wave2.json");
const successfulIds = new Set(records.map(x => x.thread_id));
const restarted = byArm.low.independent.find(x => x.replicate === 8);
details.failed_attempts = failedAttempts;
checks.stalled_attempt_recorded_restarted_and_archived =
  failedAttempts.length === 1 &&
  failedAttempts[0].status === "stalled_timeout" &&
  failedAttempts[0].archived === true &&
  !successfulIds.has(failedAttempts[0].thread_id) &&
  failedAttempts[0].restarted_as === restarted?.thread_id;
const devRecords = [];
for (const arm of arms) {
  const base = path.join(root, "raw/dev", arm);
  for (const file of fs.readdirSync(path.join(base, "independent")).filter(x => x.endsWith(".json"))) {
    devRecords.push(JSON.parse(fs.readFileSync(path.join(base, "independent", file), "utf8")));
  }
  for (const stage of stages) {
    const dir = path.join(base, "collaboration", stage);
    for (const file of fs.readdirSync(dir).filter(x => x.endsWith(".json"))) {
      devRecords.push(JSON.parse(fs.readFileSync(path.join(dir, file), "utf8")));
    }
  }
}
const allTaskIds = [
  ...devRecords.map(x => x.thread_id),
  ...records.map(x => x.thread_id),
  ...failedAttempts.map(x => x.thread_id)
];
checks.all_81_tasks_accounted_for = allTaskIds.length === 81 && new Set(allTaskIds).size === 81;
checks.all_80_successful_tasks_marked_archived =
  [...devRecords, ...records].every(x => x.archived === true);

const expectedOutputs = [
  "results/final_cases.csv",
  "results/final_summary.csv",
  "results/final_costs.csv",
  "results/final_ensemble.json",
  "results/final_case_matrix.csv",
  "results/final_comparisons.csv"
];
checks.result_artifacts_exist = expectedOutputs.every(file => fs.existsSync(path.join(root, file)));
checks.final_case_count = finalCases.length === 12;
const summaryText = fs.readFileSync(path.join(root, "results/final_summary.csv"), "utf8");
checks.strict_scoring_summary_present =
  summaryText.includes("final,low,direct,120,0.169444,0.158333") &&
  summaryText.includes("final,medium,collaboration,12,0.916667,0.916667");

const audit = {
  audited_at: new Date().toISOString(),
  checks,
  details,
  all_checks_pass: Object.values(checks).every(Boolean)
};
fs.writeFileSync(path.join(root, "final_audit.json"), JSON.stringify(audit, null, 2) + "\n");
console.log(JSON.stringify(audit, null, 2));
if (!audit.all_checks_pass) process.exit(1);
