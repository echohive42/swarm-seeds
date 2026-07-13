# Independent Experiment 03 analysis — Amendment 01

Amendment 01 changes the primary point estimate but not the inferential conclusion. The evolved champion solved 21 of 48 untouched final cases (43.75%); the corrected ten-generalist Vote10 solved 18 (37.5%). The paired difference is +6.25 percentage points, with a 95% bootstrap interval of -4.17 to +16.67 points. Champion alone won five discordant cases, corrected Vote10 alone won two, and both solved sixteen; exact McNemar p = 0.453125. The interval includes zero, so superiority is not established. Its 90% interval, -2.08 to +14.58 points, also does not establish equivalence within +/-10 points.

## Correction chronology

The frozen protocol specified ten independent **generalist** solvers. The original implementation instead used ten independent solvers with a fixed mixture of role lenses. That pool used the right ten-call budget, but it was not the architecture named Vote10 in the protocol. The mismatch was detected during release audit only after hidden final answers had been opened and the original results scored.

Amendment 01 therefore ran 40 fresh, isolated generalist calls—ten per final block—with the already registered model, common prefix, generalist lens, restrictions, and scorer. No hidden answer or prior output was supplied to those calls. This restores the protocol-determined baseline, but it is unavoidably a post-unblinding correction. The registered execution had 400 calls; the correction brings total recorded execution to 440.

The original diversified independent pool is preserved separately under `results/final-diversified-vote`. It is a superseded exploratory sensitivity arm, **not** registered Vote10. It scored 21/48 and tied the champion, with a paired 95% interval of -12.5 to +12.5 points and McNemar p = 1.0. Directly, corrected generalist plurality scored 18/48 versus diversified plurality's 21/48; they shared fifteen successes, with three corrected-only and six diversified-only cases. An independently recomputed stratified paired interval for corrected minus diversified was -18.75 to +6.25 points. That comparison is descriptive and concerns two different lens allocations.

## Search and generalization

The search signal still weakens across progressively fresher data. The best observed training score rose from 8/12 in Generation 0 to 9/12 in Generations 1 and 2, but population mean accuracy was 54.2%, 59.7%, then 54.2%; it did not improve monotonically. All 18 genomes were evaluated on the same 12 training cases. The three finalists each scored 9/12 there. On 24 fresh validation cases, the eventual champion scored 13/24 while the other two scored 9/24 each, so validation usefully changed the training ranking. The champion then scored 21/48 final: 75.0% training, 54.2% validation, and 43.75% final. Those declines are descriptive evidence of selection optimism, not formal drift estimates.

Final exact scores were close: best founder 22/48, champion 21/48, fixed Swarm10 20/48, and corrected generalist Vote10 18/48. Champion minus founder was -2.08 points (95% CI -12.5 to +8.33); champion minus fixed was +2.08 points (-8.33 to +12.5). Both exact McNemar p-values were 1.0. Term accuracy was 52.5% founder, 51.25% champion, 48.75% fixed, and 48.33% corrected Vote10.

## Error patterns and overrides

Champion's three-case primary advantage came from final blocks B01 (+2) and B04 (+1); B02 and B03 were ties. Relative to corrected Vote10, champion was +2/16 on hard, +1/16 on stress, and tied on very-hard. Its family gains were AFFINE (+2/6), INTERLEAVE (+1/6), and LIN2 (+1/6), offset by PDELTA (-1/6). Neither primary method solved GROWBLOCK or MODAFFINE. These small subgroup counts are exploratory.

The champion judge made ten changes to proposer plurality: three useful, three harmful, and four neutral, for zero net exact gain. The founder gained one net case from judging. Fixed Swarm10 gained five—seven useful versus two harmful—the largest descriptive improvement.

Errors were complementary but not directly routable. A post-hoc champion-plus-corrected-Vote10 oracle reaches only 23/48 because the baseline adds two cases beyond champion. The amended four-method oracle reaches 28/48, leaving twenty cases unsolved; champion was never the sole correct primary method. Adding the separately labeled diversified sensitivity pool raises the post-hoc oracle to 31/48 because it uniquely solves three more cases. These are unattainable oracle ceilings, not evidence that a real selector could identify the right answer.

## Resource tradeoff

Every deployed method used the same 40-call budget, with no malformed calls. Champion consumed 644,209 total tokens versus corrected Vote10's 593,809, an 8.5% increase for the non-significant +6.25-point estimate. Champion's summed call latency was 3.9% lower, though summed latency is not elapsed wall time under concurrency. The correction itself added 40 calls and 593,809 tokens; cost telemetry was unavailable.

Bottom line: after restoring the registered generalist baseline, the champion is descriptively ahead rather than tied, but the experiment still provides no statistical evidence of superiority. The post-unblinding correction and the original diversified-pool sensitivity result must remain visible in every interpretation.
