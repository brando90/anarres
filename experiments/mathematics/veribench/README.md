# Environment utility for VeriBench

**Status:** Study design in progress. Baseline, supervised fine-tuning, and reinforcement-learning pilot measurements are reported below from an external record. The environment-utility prediction has not been tested on VeriBench.

[VeriBench](https://ehersch.github.io/veribench-blog/) evaluates whether AI coding agents can translate programs into meaningful Lean 4 artifacts with checkable specifications and theorems. This workstream studies a different question about the same target: which training environments produce the greatest held-out improvement on VeriBench at a fixed RL budget?

It extends the [controlled environment-utility study](../environment-utility/README.md) to a new candidate family and evaluation target. Candidate environments are assembled for formal code verification, measured under the starting policy, and compared through their downstream VeriBench utility curves. The goal is to predict which environments will help before paying for full RL runs.

## Measurements to date

[rl-4-code-verification](https://github.com/brando90/rl-4-code-verification) holds the experiment records for this workstream, pinned here at commit `139e8d9b47d44626035594c19d708d6b26a856cc`. Each row below points to the experiment's own results file, and [results/records.json](results/records.json) holds every cited figure with the digest of its source file. Counts are VeriBench V1 tasks (896: a 614-task core and a 282-task IndustrySet) unless the row says otherwise. The score is SCSC, the VeriBench aggregate. The source records name the same score SCS4CV, and its artifact key is `SCSC`.

| Question | Result | Present boundary |
| --- | --- | --- |
| [Where do small open models start?](https://github.com/brando90/rl-4-code-verification/blob/139e8d9b47d44626035594c19d708d6b26a856cc/experiments/01_small_open_models_veribench_v1_single_call_baseline/results.md) | Nine models were run once on all 896 tasks. Qwen3-14B produced one fully compiling, fully proved file in 896 tasks. In an eight-sample probe of 128 tasks per model, two models (Qwen3-14B, Qwen3.5-9B) reached a `kernel_binary` mixed-group share of at least 0.20 on some split. The other six probed models had exactly 0.0. | Single call, no tools. The probe covers 128 tasks per model, not 896. |
| [Does a base model give a group-relative signal at eight samples?](https://github.com/brando90/rl-4-code-verification/blob/139e8d9b47d44626035594c19d708d6b26a856cc/experiments/05_qwen3_base_models_vbv1_g8_pass_signal_sft_derisk/results.md) | Across 21,504 cells (three Qwen3 Base models, 896 tasks, eight samples), the mixed-group share is 0.000 for 1.7B and 8B and 0.006 for 4B. | Qwen3 Base only. The verdict is that a supervised warm start is needed. |
| [Does matched Lean supervised fine-tuning supply that warm start?](https://github.com/brando90/rl-4-code-verification/blob/139e8d9b47d44626035594c19d708d6b26a856cc/experiments/08_qwen3_base_matched_lean_sft_opus55_astra_teachers_vbv1_train_val_test/results.md) | The frozen validation rule gives PARTIAL. 8B first passes at step 658 and 14B at step 334. The 1.7B and 4B models pass no rung. On 222 held-out test tasks with eight samples each, SCSC is 0.1116 [0.0823, 0.1435] for the selected 8B model against 0.0000 for Base 8B, and 0.0869 [0.0651, 0.1095] for the selected 14B model against 0.0023 [0.0004, 0.0045] for Base 14B. | One selected checkpoint per size. Intervals resample tasks and do not measure variation across training seeds. |
| [Does an IRT forecast choose learnable prompts?](https://github.com/brando90/rl-4-code-verification/blob/139e8d9b47d44626035594c19d708d6b26a856cc/experiments/19_interpretable_irt_scsc_factors_predict_and_guide_strict_pass1_vbv1_d013/results.md) | The forecast ranks learnable prompts with AUC 0.862, above its 0.70 gate. It does no better than the panel pass rate, and task features alone reach 0.954. | Forecast on 135 validation tasks for one starting policy. It measures a forecast, not training. |
| [Does a smooth reward beat a strict reward in reinforcement learning?](https://github.com/brando90/rl-4-code-verification/blob/139e8d9b47d44626035594c19d708d6b26a856cc/experiments/25_smooth_vs_strict_reward_grpo_qwen3_1p7b_sft_vbv1_3_d013/results.md) | GRPO on the Qwen3-1.7B Lean SFT model, three seeds per arm, validation strict pass@1 at update 48: strict reward 50.89% [43.55, 57.84], smooth reward 34.64% [28.99, 40.14], smooth minus strict -16.25 points [-19.17, -13.28]. The seed-paired differences are +12.5, -4.0, and -57.2 points, so the arms cannot be separated at the run level. | The interval resamples tasks with the six trained models held fixed, so it is a task-level interval and no seed-level test. Smooth-reward seed 2 never learned. |
| [Does reinforcement learning with factor feedback improve the target?](https://github.com/brando90/rl-4-code-verification/blob/139e8d9b47d44626035594c19d708d6b26a856cc/experiments/09_qwen3_1p7b_grpo_scsc_scalar_vs_factor_feedback_vbv1_d013/results.md) | Not measured. The pilot failed its implementation gate before any optimizer update, because generated actions and recomputed old-policy probabilities disagreed. | An infrastructure failure that says nothing about partial credit. |

One limit applies to every row. The VeriBench task instruction suggests a namespace that is not a valid Lean identifier for 533 of the 896 tasks, which is one contributor to low compile rates in small models; the [baseline facts](https://github.com/brando90/rl-4-code-verification/blob/139e8d9b47d44626035594c19d708d6b26a856cc/docs/FACTS_veribench_baselines.md) record the diagnostic.

## Reproduce

`make study-check` runs `scripts/audit_records.py`. It confirms that every figure above matches `results/records.json` after rounding, that each record carries the digest of its source file, and that no source path is absolute. To rebuild the records, check out the external repository at the pinned commit and run:

```bash
python3 scripts/extract_records.py --source PATH_TO_CHECKOUT --check
```

The extraction reads only the machine-written result files named in `records.json`. The prose of the external results files is not an input.

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
