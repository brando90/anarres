# Environment utility for VeriBench

**Status:** Study design in progress. Baseline, supervised fine-tuning, and reinforcement-learning measurements are reported below from an external record as retrospective development evidence. The environment-utility prediction has not been tested on VeriBench.

[VeriBench](https://ehersch.github.io/veribench-blog/) evaluates whether AI coding agents can translate programs into meaningful Lean 4 artifacts with checkable specifications and theorems. This workstream studies a different question about the same target: which training environments produce the greatest held-out improvement on VeriBench at a fixed RL budget?

It extends the [controlled environment-utility study](../environment-utility/README.md) to a new candidate family and evaluation target. Candidate environments are assembled for formal code verification, measured under the starting policy, and compared through their downstream VeriBench utility curves. The goal is to predict which environments will help before paying for full RL runs.

## Measurements to date

[rl-4-code-verification](https://github.com/brando90/rl-4-code-verification) holds the experiment records for this workstream, pinned here at commit `139e8d9b47d44626035594c19d708d6b26a856cc`. Each row below links to the experiment's results file at that commit. [results/records.json](results/records.json) holds each cited figure with the SHA-256 digest, size, media type, license, and producing experiment of its source file. The page reflects this pin and changes when a new commit moves it.

These measurements are retrospective development evidence from the benchmark authors' group. Anarres has not qualified VeriBench as a source (see [source qualification](../../cyber/formal-verification/source-qualification/README.md)), and the measurements await independent qualification. They used the D-013 train and validation splits of VeriBench, and experiment 08 evaluated the D-013 test split once. The prospective study must name which of these partitions it holds out.

Terms. VeriBench V1 has 896 tasks, a 614-task core and a 282-task IndustrySet (the formal-verification workstream calls this release `veribench@1.3`). The external repository pins the task pack at `c11b99ba` and the scorer at `59059a20`. SCSC is the VeriBench aggregate score. A group is the eight samples drawn for one task. A group is mixed when its samples do not all receive the same reward, and the mixed-group share is the fraction of tasks with a mixed group.

| Question | Result | Scope and limits | Evidence |
| --- | --- | --- | --- |
| [Where do small open models start?](https://github.com/brando90/rl-4-code-verification/blob/139e8d9b47d44626035594c19d708d6b26a856cc/experiments/01_small_open_models_veribench_v1_single_call_baseline/results.md) | Nine models were run once on all 896 tasks. Qwen3-14B produced one cell with positive test and proof factors in 896, and the other eight models produced none. An eight-sample probe of 128 tasks (4 per split) covered eight of the nine models, and Qwen3.6-27B was not probed. Qwen3-14B had mixed groups on 6 of 128 probe tasks (share 0.047) and Qwen3.5-9B on 4 (share 0.031). Each reached the locked 0.20 `kernel_binary` per-split threshold on at least one split, with a best split share of 0.333 and 0.250, so gate G1 is PASS. The other six probed models had none. | Single call, no tools. A split holds at most 4 probe tasks, so each best split share rests on one mixed task. | Retrospective. The probe is exploratory. |
| [Does a base model give a group-relative signal at eight samples?](https://github.com/brando90/rl-4-code-verification/blob/139e8d9b47d44626035594c19d708d6b26a856cc/experiments/05_qwen3_base_models_vbv1_g8_pass_signal_sft_derisk/results.md) | All 21,504 cells (three Qwen3 Base models, 896 tasks each, eight samples per task) were scored. The `kernel_binary` mixed-group share over 896 tasks per model is 0.000 [0.000, 0.004] for 1.7B and 8B and 0.006 [0.002, 0.013] for 4B, against a 0.05 decision threshold. The verdict is that a supervised warm start is needed. | Qwen3 Base only. | Retrospective. |
| [Does matched Lean supervised fine-tuning supply that warm start?](https://github.com/brando90/rl-4-code-verification/blob/139e8d9b47d44626035594c19d708d6b26a856cc/experiments/08_qwen3_base_matched_lean_sft_opus55_astra_teachers_vbv1_train_val_test/results.md) | Version 1 (`expt_v1`) gives PARTIAL on the frozen validation rule. 8B first passes at step 658 and 14B at step 334. The 1.7B and 4B models pass no rung. On 222 held-out test tasks with eight samples each, SCSC is 0.1116 [0.0823, 0.1435] for the selected 8B model against 0.0000 for Base 8B, and 0.0869 [0.0651, 0.1095] for the selected 14B model against 0.0023 [0.0004, 0.0045] for Base 14B. The gain lies on the 152-task core. On the 70 IndustrySet test tasks the 8B difference is 0.0000 and the 14B difference is -0.0037 [-0.0120, 0.0048]. | One selected checkpoint per size, at different token fractions (8B at 1.0, 14B at 0.5), so the two sizes are unmatched. Intervals resample tasks and do not measure variation across training seeds. Follow-up versions 2 (blocked) and 3 (incomplete at the pin) are not reported. | Retrospective. The D-013 test split was evaluated once. |
| [Does an IRT forecast choose learnable prompts?](https://github.com/brando90/rl-4-code-verification/blob/139e8d9b47d44626035594c19d708d6b26a856cc/experiments/19_interpretable_irt_scsc_factors_predict_and_guide_strict_pass1_vbv1_d013/results.md) | The item response theory (IRT) forecast separates the 32 validation tasks with mixed groups from the other 103 with AUC 0.862 [0.792, 0.925], above the 0.70 gate borrowed from experiment 13. Its margin over the panel pass rate is +0.011 [-0.004, +0.027], which the data do not resolve, and the experiment's own verdict is PASS, NOT IRT-SPECIFIC. In an exploratory comparison, task features alone reach 0.954. The second primary endpoint, that IRT adds held-out information about strict success, was not supported. | Forecast on 135 validation tasks for one starting policy, an experiment 08 4B checkpoint that passed no validation rung. The experiment trains nothing. | Retrospective. The features-only AUC is exploratory. |
| [Does a smooth reward beat a strict reward in reinforcement learning?](https://github.com/brando90/rl-4-code-verification/blob/139e8d9b47d44626035594c19d708d6b26a856cc/experiments/25_smooth_vs_strict_reward_grpo_qwen3_1p7b_sft_vbv1_3_d013/results.md) | Group relative policy optimization (GRPO) on the Qwen3-1.7B Lean fine-tuned model (experiment 08 step 658, strict pass@1 4.26% at update 0), three seeds per arm. At update 48, on 135 validation tasks with 32 samples each (4,320 cells per run), strict pass@1 is 50.89% [43.55, 57.84] with the strict reward and 34.64% [28.99, 40.14] with the smooth reward. Smooth minus strict is -16.25 points [-19.17, -13.28]. The seed-paired differences are +12.5, -4.0, and -57.2 points, and an exact permutation test over the six run means gives p=0.50, so the arms cannot be separated at the run level. | The interval resamples tasks with the six trained models held fixed. Smooth-reward seed 2 never learned. Open at the pin: a fourth smooth-reward seed is running. Both seed-2 runs resumed from update 8 after a host reboot, and the resume path was not checked. | Retrospective. The run reads the D-013 validation split. |
| [Does reinforcement learning with factor feedback improve the target?](https://github.com/brando90/rl-4-code-verification/blob/139e8d9b47d44626035594c19d708d6b26a856cc/experiments/09_qwen3_1p7b_grpo_scsc_scalar_vs_factor_feedback_vbv1_d013/results.md) | Not measured. The pilot failed its implementation gate before any optimizer update, because 4 of 4,077 generated actions fell outside the recomputed old-policy support. | An infrastructure failure that says nothing about partial credit. | Infrastructure failure. |

The VeriBench task instruction suggests a namespace that is not a valid Lean identifier for 533 of the 896 tasks. In experiment 01, a namespace rewrite raised Qwen3-14B from 1 to 25 of 896 cells with positive test and proof factors (a diagnostic with the task as its unit). Both counts are quoted from the [baseline facts](https://github.com/brando90/rl-4-code-verification/blob/139e8d9b47d44626035594c19d708d6b26a856cc/docs/FACTS_veribench_baselines.md) and have no machine-written record. The effect of the hint on the trained models in the other rows was not measured.

## Reproduce

`make study-check` runs `scripts/audit_records.py` and its negative test. The audit checks that each number in the table above is the number in `results/records.json` after rounding, that each link to the external repository carries the pinned commit, that each source file records a SHA-256 digest, size, media type, license, and producing experiment, and that no source path is absolute. The negative test changes a copy of the page and of the records and requires the audit to fail. Source files write the SCSC score as SCS4CV in places, and its artifact key is `SCSC`. To rebuild the records and verify the digests against the pinned commit, check out the external repository and run:

```bash
python3 scripts/extract_records.py --source PATH_TO_CHECKOUT --check
python3 scripts/audit_records.py --source PATH_TO_CHECKOUT
```

The extraction reads only the machine-written result files named in `records.json`, as stored at the pinned commit. The prose of the external results files is not an input, and one figure is computed here: the exact permutation test over the six run means of experiment 25.

## Relation to the formal-verification workstream

The [formal-verification workstream](../../cyber/formal-verification/README.md) qualifies Lean sources, verifiers, and runners through the `anarres formal` adapter. This study uses held-out VeriBench utility at a fixed budget as its target. A Lean candidate environment from the adapter would be assessed against that target, after source qualification.

## Why this is a new environment setting

| Component | Controlled scale study | VeriBench study |
| --- | --- | --- |
| Training tasks | Natural-language mathematical problems with answer generation | Programs that must be translated into structured Lean 4 artifacts |
| Interaction | One response followed by symbolic answer verification | Agentic tool use, Lean compilation, specification construction, and proof development |
| Reward evidence | Mathematical equivalence under one deterministic verifier | Compilation, nontrivial formal content, and coverage of the intended specification |
| Held-out target | Pass@1 on a disjoint OpenR1-Math panel | Performance on held-out VeriBench tasks |

These differences can change which experience is available, how much survives the training contract, and what counts as useful downstream improvement. The VeriBench study therefore remeasures every candidate environment under its own starting policy and tests the predictive representation again. The original four quadrants and fitted coefficients remain specific to the controlled scale study.

## Planned protocol

1. Freeze training candidates and a held-out VeriBench evaluation split by content identity.
2. Qualify Lean toolchains, task fixtures, and reward behavior before measuring learnability.
3. Measure policy-relative signal, effective coverage, generated cost, and verifier reliability without reading RL outcomes.
4. Freeze environment predictions and uncertainty rules.
5. Train the selected candidate environments under one compute-matched contract.
6. Score curve prediction, environment ordering, and allocation regret on held-out VeriBench performance.

The protocol keeps infrastructure failures separate from scientific failures and records every environment identity before claim-bearing training. Public task releases will use versioned external artifacts with dataset cards and immutable revisions.
