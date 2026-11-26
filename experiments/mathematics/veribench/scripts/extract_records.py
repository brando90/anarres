#!/usr/bin/env python3
"""Rebuild results/records.json from a pinned rl-4-code-verification checkout.

Usage:
    python3 scripts/extract_records.py --source PATH_TO_CHECKOUT [--check]

The script reads each source file as stored at the commit named in `PIN`
(`git show PIN:path`), so a modified working tree cannot change the records.
Without `--check`, it writes `results/records.json`. With `--check`, it compares
the extraction with the released file and exits nonzero on any difference.

JSON files are read as documents, CSV files as lists of rows, and other files
(scripts, configs, source code) as text. A figure from a CSV or text file is
always a derived figure, with its derivation in a named function below.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import itertools
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / "results" / "records.json"
PIN = "139e8d9b47d44626035594c19d708d6b26a856cc"
REPOSITORY = "https://github.com/brando90/rl-4-code-verification"
LICENSE = "Apache-2.0"

E01 = (
    "experiments/01_small_open_models_veribench_v1_single_call_baseline"
    "/expt_v1/results/probe_channels_summary.json"
)
E01_DIAGNOSTIC = (
    "experiments/01_small_open_models_veribench_v1_single_call_baseline"
    "/expt_v1/results/diagnostics_10-07-2026/combined_{label}_g1__0.json"
)
# The same summary with the namespace-rewritten files replacing the cells they edit.
E01_NAMESPACE = E01_DIAGNOSTIC.format(label="qwen3-14b").replace("__0.json", "__1.json")
E01_PROBE_FAMILIES = (
    "experiments/01_small_open_models_veribench_v1_single_call_baseline"
    "/expt_v1/results/summaries/rho_h_qwen3-14b_g8_kernel_binary.json"
)
E05 = (
    "experiments/05_qwen3_base_models_vbv1_g8_pass_signal_sft_derisk"
    "/expt_v1/results/analysis_e05.json"
)
_E08_RUN = (
    "experiments/08_qwen3_base_matched_lean_sft_opus55_astra_teachers_vbv1_train_val_test/expt_v1/"
)
_E08 = _E08_RUN + "results/"
E08_SELECTION = _E08 + "selection.json"
E08_TEST = _E08 + "test_eval.json"
E08_LADDER = _E08 + "ladder_manifest.json"
E08_SCORER = _E08 + "scorer_adapter_check.json"
E08_SPLIT_SUMMARY = _E08 + "split/vbv1_split_summary.json"
E08_SPLIT_MANIFEST = _E08 + "split/vbv1_split_manifest.csv"
E08_CONFIG = _E08_RUN + "configs/e08_sft_{size}.yaml"
E09 = (
    "experiments/09_qwen3_1p7b_grpo_scsc_scalar_vs_factor_feedback_vbv1_d013"
    "/expt_v1/results/terminal_receipt.json"
)
_E19 = "experiments/19_interpretable_irt_scsc_factors_predict_and_guide_strict_pass1_vbv1_d013/"
E19 = _E19 + "expt_v1/results/analysis_e19.json"
E19_PINS = _E19 + "expt_v1/input_pins_e19.json"
E19_CODE = _E19 + "expt_v1/analyze_e19.py"
_E25 = "experiments/25_smooth_vs_strict_reward_grpo_qwen3_1p7b_sft_vbv1_3_d013/expt_v1/"
E25 = _E25 + "results/full_run_at2925/analysis_e25.json"
E25_STATS = _E25 + "code/stats_e20.py"
E25_EVAL = _E25 + "code/eval_local.sh"
E25_LAUNCH_S01 = _E25 + "results/full_run_at1788/full_run.sh"
E25_LAUNCH_S2 = _E25 + "results/full_run_at2925/full_run5.sh"
E25_LANE = _E25 + "code/lane.sh"
E25_ANALYZE = _E25 + "code/analyze_e25.py"
E19_DATA = _E19 + "expt_v1/data_e19.py"
E01_RUN = "experiments/01_small_open_models_veribench_v1_single_call_baseline/expt_v1/run_model.sh"
E05_RUN = "experiments/05_qwen3_base_models_vbv1_g8_pass_signal_sft_derisk/expt_v1/run_model_e05.sh"
E08_TRAINING_DONE = _E08 + "parent_training_complete_10-11-2026.json"
E08_RUN_LADDER = _E08_RUN + "scripts/run_ladder_e08.sh"
E08_ANALYZE_LADDER = _E08_RUN + "scripts/analyze_ladder.py"
E08_SCREEN = _E08_RUN + "scripts/score_teacher_files.py"
E08_JUDGE_STATE = _E08 + "judge/state.json"
E08_JUDGE_CONTROLS = _E08 + "judge/controls_check.json"
E08_JUDGE_FSC = _E08 + "judge/fsc_test_sft_{size}.json"
E08_JUDGE_SIZES = {"8B": "8B_f1p0", "14B": "14B_f0p5"}
REWARDS = "src/rl4cv/rewards.py"
JOBS = "src/rl4cv/veribench/jobs.py"

MEDIA_TYPES = {
    ".json": "application/json",
    ".csv": "text/csv",
    ".py": "text/x-python",
    ".sh": "text/x-shellscript",
    ".yaml": "application/yaml",
}

PROBED = (
    "qwen3.5-0.8b",
    "qwen3.5-2b",
    "qwen3.5-4b",
    "qwen3.5-9b",
    "qwen3-1.7b",
    "qwen3-4b",
    "qwen3-8b",
    "qwen3-14b",
)
SINGLE_CALL = PROBED + ("qwen3.6-27b-local",)

# Producing experiment and run of each source file, for the artifact reference.
PRODUCED_BY = {
    E01: ("01", "expt_v1 probe summary"),
    E05: ("05", "expt_v1 analysis"),
    E08_SELECTION: ("08", "expt_v1 checkpoint selection"),
    E08_TEST: ("08", "expt_v1 held-out test evaluation"),
    E08_LADDER: ("08", "expt_v1 validation ladder manifest"),
    E08_SCORER: ("08", "expt_v1 scorer adapter check"),
    E08_SPLIT_SUMMARY: ("08", "expt_v1 D-013 split summary"),
    E08_SPLIT_MANIFEST: ("08", "expt_v1 D-013 split manifest"),
    E09: ("09", "expt_v1 terminal receipt"),
    E19: ("19", "expt_v1 analysis"),
    E19_PINS: ("19", "expt_v1 input pins"),
    E19_CODE: ("19", "expt_v1 analysis code"),
    E25: ("25", "full_run_at2925 analysis"),
    E25_STATS: ("25", "expt_v1 statistics code"),
    E25_EVAL: ("25", "expt_v1 evaluation script"),
    E25_LAUNCH_S01: ("25", "full_run_at1788 launch script, seeds 0 and 1"),
    E25_LAUNCH_S2: ("25", "full_run_at2925 launch script, seed 2"),
    E25_LANE: ("25", "expt_v1 lane script that starts the trainer"),
    E25_ANALYZE: ("25", "expt_v1 analysis code"),
    E19_DATA: ("19", "expt_v1 panel loader"),
    E01_RUN: ("01", "expt_v1 model run script"),
    E05_RUN: ("05", "expt_v1 model run script"),
    E08_TRAINING_DONE: ("08", "expt_v1 training completion record 10-11-2026"),
    E08_RUN_LADDER: ("08", "expt_v1 ladder generation script"),
    E08_ANALYZE_LADDER: ("08", "expt_v1 ladder analysis code"),
    E08_SCREEN: ("08", "expt_v1 teacher-file and vacuity screen code"),
    E08_JUDGE_STATE: ("08", "expt_v1 judge run state"),
    E08_JUDGE_CONTROLS: ("08", "expt_v1 judge controls check"),
    E01_NAMESPACE: ("01", "expt_v1 diagnostics 10-07-2026, namespace rewrite"),
    E01_PROBE_FAMILIES: ("01", "expt_v1 probe summary per benchmark family"),
    REWARDS: ("shared", "rl4cv package reward definitions"),
    JOBS: ("shared", "rl4cv package scorer-row reader"),
}
for _size in ("1.7B", "8B", "14B"):
    PRODUCED_BY[E08_CONFIG.format(size=_size)] = ("08", f"expt_v1 {_size} training config")
for _size, _label in E08_JUDGE_SIZES.items():
    PRODUCED_BY[E08_JUDGE_FSC.format(size=_label)] = (
        "08",
        f"expt_v1 held-out test FSC judging, selected {_size} model",
    )

# Each figure: (id, source file, key path inside the JSON file).
FIGURES: list[tuple[str, str, tuple]] = [
    ("e01.gate_g1.verdict", E01, ("gate_g1", "verdict")),
    ("e01.gate_g1.locked_channel", E01, ("gate_g1", "locked_channel")),
]
for _model in PROBED:
    FIGURES += [
        (
            f"e01.{_model}.kernel_binary_max_split",
            E01,
            ("gate_g1", "per_model", _model, "kernel_binary_max_split"),
        ),
        (f"e01.{_model}.probe_rows", E01, ("labels", _model, "n_rows")),
        (
            f"e01.{_model}.probe_tasks",
            E01,
            ("labels", _model, "channels", "kernel_binary", "n_groups_measured"),
        ),
        (
            f"e01.{_model}.probe_mixed_share",
            E01,
            ("labels", _model, "channels", "kernel_binary", "q_mixed_empirical"),
        ),
    ]
for _label in SINGLE_CALL:
    _diagnostic = E01_DIAGNOSTIC.format(label=_label)
    PRODUCED_BY[_diagnostic] = ("01", "expt_v1 diagnostics 10-07-2026")
    FIGURES += [
        (f"e01.{_label}.cells", _diagnostic, ("n_cells",)),
        (
            f"e01.{_label}.compiling_proved_cells",
            _diagnostic,
            ("as_written", "cells_IC_tests_x_IC_proofs_positive", 0),
        ),
    ]
for _model in ("qwen3-1.7b-base", "qwen3-4b-base", "qwen3-8b-base"):
    FIGURES += [
        (f"e05.{_model}.cells_declared", E05, ("models", _model, "execution", "cells_declared")),
        (f"e05.{_model}.cells_scored", E05, ("models", _model, "execution", "cells_scored")),
        (
            f"e05.{_model}.mixed_share",
            E05,
            ("models", _model, "channels", "kernel_binary", "all_896", "mixed_share"),
        ),
        (
            f"e05.{_model}.mixed_share_wilson95",
            E05,
            ("models", _model, "channels", "kernel_binary", "all_896", "mixed_share_wilson95"),
        ),
        (f"e05.{_model}.verdict", E05, ("models", _model, "verdict")),
    ]
FIGURES += [
    ("e08.verdict", E08_SELECTION, ("verdict",)),
    ("e08.8B.first_passing_step", E08_SELECTION, ("gate_table", "1.0", "8B", "step")),
    (
        "e08.8B.first_passing_tokens",
        E08_SELECTION,
        ("gate_table", "1.0", "8B", "cumulative_assistant_tokens"),
    ),
    ("e08.14B.first_passing_step", E08_SELECTION, ("gate_table", "0.5", "14B", "step")),
    (
        "e08.14B.first_passing_tokens",
        E08_SELECTION,
        ("gate_table", "0.5", "14B", "cumulative_assistant_tokens"),
    ),
    (
        "e08.1.7B.earliest_passing_fraction",
        E08_SELECTION,
        ("earliest_passing_fraction_per_size", "1.7B"),
    ),
    (
        "e08.4B.earliest_passing_fraction",
        E08_SELECTION,
        ("earliest_passing_fraction_per_size", "4B"),
    ),
    (
        "e08.8B.earliest_passing_fraction",
        E08_SELECTION,
        ("earliest_passing_fraction_per_size", "8B"),
    ),
    (
        "e08.14B.earliest_passing_fraction",
        E08_SELECTION,
        ("earliest_passing_fraction_per_size", "14B"),
    ),
    ("e08.test.n_tasks", E08_TEST, ("n_test_tasks",)),
    (
        "e08.test.selected_8B.known_cells",
        E08_TEST,
        ("systems", "test_sft_8B_f1p0", "scopes", "all", "n_known_cells"),
    ),
]
for _label, _system in (
    ("selected_8B", "test_sft_8B_f1p0"),
    ("selected_14B", "test_sft_14B_f0p5"),
    ("base_8B", "base_8B_e05"),
    ("base_14B", "base14b"),
):
    FIGURES += [
        (
            f"e08.test.{_label}.scsc",
            E08_TEST,
            ("systems", _system, "scopes", "all", "point_common_cohort", "SCSC"),
        ),
        (
            f"e08.test.{_label}.scsc_bootstrap95",
            E08_TEST,
            ("systems", _system, "scopes", "all", "bootstrap95_task", "SCSC"),
        ),
    ]
for _size in ("8B", "14B"):
    for _scope in ("core", "industryset"):
        FIGURES += [
            (
                f"e08.test.{_size}.{_scope}.scsc_difference",
                E08_TEST,
                ("paired_differences", _size, _scope, "SCSC_diff", "point"),
            ),
            (
                f"e08.test.{_size}.{_scope}.scsc_difference_bootstrap95",
                E08_TEST,
                ("paired_differences", _size, _scope, "SCSC_diff", "bootstrap95"),
            ),
            (
                f"e08.test.{_size}.{_scope}.shared_known_cells",
                E08_TEST,
                ("paired_differences", _size, _scope, "n_shared_known_cells"),
            ),
        ]
FIGURES += [
    ("e09.status", E09, ("status",)),
    ("e09.reason", E09, ("reason",)),
    ("e09.reason_detail", E09, ("reason_detail",)),
    ("e09.scientific_completion", E09, ("scientific_completion",)),
    ("e25.tasks", E25, ("tasks",)),
    ("e25.u0.cells", E25, ("runs", "u0", "cells")),
    ("e25.u0.strict_successes", E25, ("runs", "u0", "strict_successes")),
    ("e25.u0.pass_at_1", E25, ("runs", "u0", "pass_at_1")),
    ("e25.u48.cells_per_run", E25, ("runs", "A_s0_u048", "cells")),
    ("e25.u48.strict.pass_at_1", E25, ("bootstrap_points", "u48", "A", "point")),
    ("e25.u48.strict.ci95", E25, ("bootstrap_points", "u48", "A", ("lo", "hi"))),
    ("e25.u48.smooth.pass_at_1", E25, ("bootstrap_points", "u48", "B", "point")),
    ("e25.u48.smooth.ci95", E25, ("bootstrap_points", "u48", "B", ("lo", "hi"))),
    ("e25.u48.smooth_minus_strict", E25, ("bootstrap_points", "u48", "B_minus_A", "point")),
    (
        "e25.u48.smooth_minus_strict.ci95",
        E25,
        ("bootstrap_points", "u48", "B_minus_A", ("lo", "hi")),
    ),
    ("e25.u48.seed_paired_smooth_minus_strict", E25, ("per_seed_pair_diff_u48_points",)),
    ("e25.u48.per_run_pass_at_1", E25, ("per_seed_u48_points",)),
    ("e19.tasks", E19, ("G1", "n_tasks")),
    ("e19.mixed_tasks", E19, ("G1", "mixed_tasks")),
    ("e19.auc_irt_2pl", E19, ("G1", "auc_primary_vs_gate", "estimate")),
    ("e19.auc_irt_2pl.ci95", E19, ("G1", "auc_primary_vs_gate", "ci95")),
    ("e19.auc_gate", E19, ("G1", "auc_primary_vs_gate", "gate")),
    ("e19.auc_features_only", E19, ("G1", "estimates", "auc_mixed", "q8_features_only")),
    (
        "e19.auc_irt_minus_panel_strict_rate",
        E19,
        ("G1", "auc_contrasts", "q8_irt_2pl_minus_panel_strict_rate", "estimate"),
    ),
    (
        "e19.auc_irt_minus_panel_strict_rate_ci95",
        E19,
        ("G1", "auc_contrasts", "q8_irt_2pl_minus_panel_strict_rate", "ci95"),
    ),
    ("e19.verdict_g1", E19, ("verdicts", "G1")),
    ("e19.irt_beats_baselines_strict", E19, ("verdicts", "E1_strict_irt_beats_baselines")),
]
# Added for the scope, interval, and provenance statements.
FIGURES += [
    ("e01.qwen3-14b.namespace_rewrite.cells", E01_NAMESPACE, ("n_cells",)),
    (
        "e01.qwen3-14b.namespace_rewrite.compiling_proved_cells",
        E01_NAMESPACE,
        ("as_written", "cells_IC_tests_x_IC_proofs_positive", 0),
    ),
    ("e01.qwen3-14b.namespace_rewrite.work_dirs", E01_NAMESPACE, ("work_dirs",)),
    (
        "e01.qwen3-14b.namespace_rewrite.limitation",
        E01_NAMESPACE,
        ("historical_rewrite_audit", "limitation"),
    ),
    (
        "e01.qwen3-14b.namespace_rewrite.guarded_counterfactual",
        E01_NAMESPACE,
        ("historical_rewrite_audit", "guarded_counterfactual"),
    ),
    ("e08.split.decision", E08_SPLIT_SUMMARY, ("decision",)),
    ("e08.split.tasks", E08_SPLIT_SUMMARY, ("tasks",)),
    ("e08.split.counts", E08_SPLIT_SUMMARY, ("counts",)),
    ("e08.split.manifest_sha256", E08_SPLIT_SUMMARY, ("manifest_sha256",)),
    ("e08.split.veribench_commit", E08_SPLIT_SUMMARY, ("veribench_commit",)),
    ("e08.scorer_commit", E08_SCORER, ("scorer", "commit")),
    ("e08.test.aggregate_rule", E08_TEST, ("aggregate_rule",)),
    ("e08.test.bootstrap", E08_TEST, ("bootstrap",)),
    ("e08.validation.tasks", E08_LADDER, ("n_tasks",)),
    ("e08.validation.samples_per_task", E08_LADDER, ("samples_per_task",)),
    ("e19.groups", E19, ("G1", "n_groups")),
    ("e19.auc_interval_method", E19, ("G1", "auc_primary_vs_gate", "p_test")),
    ("e19.bootstrap_draws", E19, ("settings", "boot")),
    ("e19.strict.cells", E19, ("E1", "strict", "cells")),
    ("e19.strict.positives", E19, ("E1", "strict", "positives")),
    ("e19.systems", E19, ("panel", "systems")),
    ("e19.start_policy_sha256", E19, ("inputs", "start_policy")),
    ("e19.start_policy_path", E19_PINS, ("paths", "start_policy")),
    ("e19.start_policy_pinned_sha256", E19_PINS, ("sha256", "start_policy")),
    ("e25.groups", E25, ("groups",)),
    ("e25.u48.strict.groups", E25, ("bootstrap_points", "u48", "A", "groups")),
    ("e25.u48.smooth.groups", E25, ("bootstrap_points", "u48", "B", "groups")),
    ("e25.u48.smooth_minus_strict.groups", E25, ("bootstrap_points", "u48", "B_minus_A", "groups")),
    ("e25.u48.smooth_minus_strict.tasks", E25, ("bootstrap_points", "u48", "B_minus_A", "tasks")),
    ("e25.u0.samples", E25, ("runs", "u0", "samples_scored")),
    ("e25.u48.samples", E25, ("runs", "A_s0_u048", "samples_scored")),
]
FIGURES += [
    ("e08.training.precision", E08_TRAINING_DONE, ("recipe", "precision")),
    ("e08.training.nemo_revision", E08_TRAINING_DONE, ("pins", "nemo_revision")),
    ("e08.judge.identity_evidence", E08_JUDGE_CONTROLS, ("identity_evidence",)),
]
for _size, _label in E08_JUDGE_SIZES.items():
    for _field in ("configs", "repeats", "rule"):
        FIGURES.append(
            (
                f"e08.judge.{_size}.{_field}",
                E08_JUDGE_FSC.format(size=_label),
                (_field,),
            )
        )
for _model in ("qwen3-1.7b-base", "qwen3-4b-base", "qwen3-8b-base"):
    FIGURES.append(
        (
            f"e05.{_model}.tasks_measured",
            E05,
            ("models", _model, "channels", "kernel_binary", "all_896", "tasks_measured"),
        )
    )


def permutation_p(per_run: dict[str, float]) -> float:
    """Exact two-sided permutation p over run means: arm A against arm B, three runs each."""
    values = [per_run[name] for name in sorted(per_run)]
    arm_a = [per_run[name] for name in sorted(per_run) if name.startswith("A")]
    observed = abs(
        sum(arm_a) / len(arm_a) - (sum(values) - sum(arm_a)) / (len(values) - len(arm_a))
    )
    extreme = total = 0
    for chosen in itertools.combinations(range(len(values)), len(arm_a)):
        mean_a = sum(values[i] for i in chosen) / len(arm_a)
        rest = [values[i] for i in range(len(values)) if i not in chosen]
        total += 1
        extreme += abs(sum(rest) / len(rest) - mean_a) >= observed - 1e-9
    return extreme / total


def channel_names(channels: dict[str, dict]) -> list[str]:
    """Names of the reward channels that the analysis scored."""
    return sorted(channels)


def digit_leading_stems(rows: list[dict[str, str]]) -> dict[str, list[int]]:
    """Per task family with any such task: [tasks whose Python file stem starts with a digit,
    tasks in the family]. VeriBench suggests `namespace {file stem}`, and a Lean identifier
    cannot start with a digit."""
    digit = Counter(r["family"] for r in rows if Path(r["py_relpath"]).stem[0].isdigit())
    size = Counter(r["family"] for r in rows)
    return {family: [digit[family], size[family]] for family in sorted(digit)}


def clusters_spanning_splits(rows: list[dict[str, str]]) -> int:
    """Number of D-013 task clusters (`group_id`) whose tasks fall in more than one split."""
    splits: dict[str, set[str]] = {}
    for row in rows:
        splits.setdefault(row["group_id"], set()).add(row["split"])
    return sum(len(names) > 1 for names in splits.values())


def validation_clusters(rows: list[dict[str, str]]) -> list[int]:
    """[validation tasks, D-013 task clusters among them]."""
    validation = [row for row in rows if row["split"] == "validation"]
    return [len(validation), len({row["group_id"] for row in validation})]


def probe_tasks_per_family(families: dict[str, dict]) -> dict[str, int]:
    """Number of benchmark families with each count of probe tasks, keyed by that count."""
    counts = Counter(str(family["n_groups"]) for family in families.values())
    return dict(sorted(counts.items()))


def trained_checkpoints_per_size(systems: list[dict]) -> dict[str, int]:
    """Number of trained checkpoints on the validation ladder for each model size."""
    return dict(sorted(Counter(s["size"] for s in systems if s["role"] == "trained").items()))


def _one(pattern: str, text: str) -> str:
    found = re.findall(pattern, text, flags=re.MULTILINE)
    if len(set(found)) != 1:
        raise ValueError(f"expected one value for {pattern!r}, found {found}")
    return found[0]


def sft_seed(text: str) -> int:
    """The `seed` field of the `sft:` block of a training config."""
    return int(_one(r"^sft:\n(?:  .*\n)*?  seed: (\d+)$", text))


def bootstrap_note(text: str) -> list[object]:
    """[draws, comment] of the evaluation bootstrap setting `BOOT`."""
    draws, comment = re.findall(r"^BOOT = ([\d_]+)  # (.*)$", text, flags=re.MULTILINE)[0]
    return [int(draws), comment]


def bootstrap_interval_level(text: str) -> float:
    """Coverage of the percentile interval that the paired group bootstrap returns."""
    low, high = _one(r"np\.percentile\(boot, \[([\d.]+), ([\d.]+)\]\)", text)
    return float(high) - float(low)


def bootstrap_unit(text: str) -> str:
    """Docstring of the resampling function of the paired group bootstrap."""
    return _one(r'def group_bootstrap_indices\(.*\n\s+"""(.*)"""', text)


def sampler_seed(text: str) -> int:
    """Seed passed to the evaluation sampler."""
    return int(_one(r"--seed (\d+)", text))


def trainer_dtype(text: str) -> str:
    """Precision passed to the trainer."""
    return _one(r"--dtype (\S+)", text)


def kernel_binary_definition(text: str) -> str:
    """Docstring of the `kernel_binary` reward."""
    return _one(r'def reward_kernel_binary\(.*\n\s+"""(.*)"""', text)


def scored_response_reads_vacuity(text: str) -> bool:
    """Whether the scorer-row reader used by evaluation sets the vacuous-theorem count."""
    body = text[text.index("def scored_response(") :]
    body = body[: body.index("\ndef ", 1)]
    return "vacuous" in body


def start_checkpoint(text: str) -> str:
    """Directory name of the checkpoint that the launch script passes to the trainer as MODEL."""
    return _one(r"\bMODEL=\$R/ckpt/(\S+)", text)


def trainer_script(text: str) -> str:
    """Python file that the lane script starts as the trainer."""
    return _one(r"\$T/(\w+\.py) --arm", text)


def strict_function(text: str) -> str:
    """Name of the reward function that the experiment 25 analysis applies to each scored cell."""
    return _one(r"r = float\((\w+)\(scored_response\(row, gen\)\)\)", text)


def strict_rule(text: str) -> str:
    """Condition under which the experiment 19 panel loader sets strict success to 1."""
    return _one(r"strict\[i, j\] = float\((.*)\)$", text)


def allowed_axioms(text: str) -> list[str]:
    """Axioms that a kernel-accepted theorem may use, from the module docstring of the rewards."""
    found = _one(r"kernel axioms stay within \{([^}]*)\}", text)
    return [name.strip() for name in found.split(",")]


def kernel_binary_conditions(text: str) -> list[str]:
    """Conditions that `reward_kernel_binary` joins with `and`, in order."""
    body = text[text.index("def reward_kernel_binary(") :]
    expression = body[body.index("ok = (") + len("ok = (") : body.index("\n    )")]
    return [part.strip() for part in re.split(r"\band\b", expression)]


def vacuity_screen_comment(text: str) -> str:
    """Comment block above the heuristic vacuous-statement screen, on one line."""
    block = re.search(r"^# Heuristic screen.*?\n(?:#.*\n)+", text, flags=re.MULTILINE)
    if block is None:
        raise ValueError("no heuristic screen comment")
    return " ".join(line.lstrip("# ").strip() for line in block[0].splitlines())


def calls_collect(text: str) -> bool:
    """Whether the run script builds its scored rows with `rl4cv.veribench.collect`."""
    return "rl4cv.veribench.collect" in text


def ladder_sets_vacuity(text: str) -> bool:
    """Whether the experiment 08 ladder analysis fills the vacuous-theorem count from a screen."""
    return "from score_teacher_files import vacuity" in text and "vacuous_theorems=n_vac" in text


def screen_uses_statement_check(text: str) -> bool:
    """Whether the experiment 08 vacuity screen applies the syntactic `is_vacuous_statement`."""
    return (
        "from rl4cv.rewards import is_vacuous_statement" in text
        and "is_vacuous_statement(t)" in text
    )


def ladder_generation(text: str) -> dict[str, object]:
    """Generation module, thinking mode, and sampler seed of the experiment 08 ladder script."""
    return {
        "module": _one(r"-m (rl4cv\.veribench\.generate)", text),
        "thinking": _one(r"--thinking (\w+)", text),
        "seed": int(_one(r"--seed (\d+)", text)),
    }


def max_steps(text: str) -> int:
    """The `max_num_steps` field of the `sft:` block of a training config."""
    return int(_one(r"^sft:\n(?:  .*\n)*?  max_num_steps: (\d+)$", text))


def judge_requests(runs: dict[str, dict]) -> dict[str, list[str]]:
    """[agent, requested model] of each FSC judge run on the selected test models."""
    found = {}
    for name in sorted(runs):
        if name.startswith(("test_sft_8B_f1p0/", "test_sft_14B_f0p5/")):
            command = runs[name]["command"]
            found[name] = [command[command.index(flag) + 1] for flag in ("--agent", "--model")]
    return found


def judge_efforts(configs: dict[str, dict]) -> dict[str, str]:
    """Requested effort of each judge configuration in the controls check."""
    return {name: configs[name]["expected_envelope"]["effort"] for name in sorted(configs)}


# Derived figures: (id, source file, key path of the input, function of the input).
DERIVED = [
    (
        "e25.u48.run_level_permutation_p",
        E25,
        ("per_seed_u48_points",),
        permutation_p,
    ),
    *(
        (
            f"e05.{model}.channels",
            E05,
            ("models", model, "channels"),
            channel_names,
        )
        for model in ("qwen3-1.7b-base", "qwen3-4b-base", "qwen3-8b-base")
    ),
    ("e08.split.digit_leading_stems", E08_SPLIT_MANIFEST, (), digit_leading_stems),
    ("e08.split.clusters_spanning_splits", E08_SPLIT_MANIFEST, (), clusters_spanning_splits),
    ("e08.split.validation_clusters", E08_SPLIT_MANIFEST, (), validation_clusters),
    ("e01.probe_tasks_per_family", E01_PROBE_FAMILIES, (), probe_tasks_per_family),
    (
        "e08.validation.trained_checkpoints_per_size",
        E08_LADDER,
        ("systems",),
        trained_checkpoints_per_size,
    ),
    ("e08.8B.training_seed", E08_CONFIG.format(size="8B"), (), sft_seed),
    ("e08.14B.training_seed", E08_CONFIG.format(size="14B"), (), sft_seed),
    ("e19.bootstrap_note", E19_CODE, (), bootstrap_note),
    ("e25.bootstrap_interval_level", E25_STATS, (), bootstrap_interval_level),
    ("e25.bootstrap_unit", E25_STATS, (), bootstrap_unit),
    ("e25.eval_sampler_seed", E25_EVAL, (), sampler_seed),
    ("e25.trainer_dtype.seeds_0_1", E25_LAUNCH_S01, (), trainer_dtype),
    ("e25.trainer_dtype.seed_2", E25_LAUNCH_S2, (), trainer_dtype),
    ("kernel_binary.definition", REWARDS, (), kernel_binary_definition),
    ("e25.evaluation_reads_vacuity", JOBS, (), scored_response_reads_vacuity),
    ("e25.start_checkpoint.seeds_0_1", E25_LAUNCH_S01, (), start_checkpoint),
    ("e25.start_checkpoint.seed_2", E25_LAUNCH_S2, (), start_checkpoint),
    ("e25.trainer_script", E25_LANE, (), trainer_script),
    ("e25.strict_function", E25_ANALYZE, (), strict_function),
    ("e19.strict_rule", E19_DATA, (), strict_rule),
    ("e08.1.7B.max_steps", E08_CONFIG.format(size="1.7B"), (), max_steps),
    ("kernel_binary.allowed_axioms", REWARDS, (), allowed_axioms),
    ("kernel_binary.conditions", REWARDS, (), kernel_binary_conditions),
    ("rewards.vacuity_screen_comment", REWARDS, (), vacuity_screen_comment),
    ("e01.run_uses_collect", E01_RUN, (), calls_collect),
    ("e05.run_uses_collect", E05_RUN, (), calls_collect),
    ("e08.ladder_sets_vacuity", E08_ANALYZE_LADDER, (), ladder_sets_vacuity),
    ("e08.screen_uses_statement_check", E08_SCREEN, (), screen_uses_statement_check),
    ("e08.ladder_generation", E08_RUN_LADDER, (), ladder_generation),
    ("e08.judge.requests", E08_JUDGE_STATE, ("runs",), judge_requests),
    ("e08.judge.efforts", E08_JUDGE_CONTROLS, ("configs",), judge_efforts),
]


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def pick(document: object, keys: tuple) -> object:
    """Follow a key path. A final tuple of keys picks several values as a list."""
    for key in keys:
        if isinstance(key, tuple):
            return [document[name] for name in key]  # type: ignore[index]
        document = document[key]  # type: ignore[index]
    return document


def parse(relative: str, payload: bytes) -> object:
    """JSON as a document, CSV as a list of rows, and any other file as text."""
    suffix = Path(relative).suffix
    if suffix == ".json":
        return json.loads(payload)
    text = payload.decode("utf-8")
    if suffix == ".csv":
        return list(csv.DictReader(io.StringIO(text)))
    return text


def read_at_pin(source: Path, relative: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(source), "show", f"{PIN}:{relative}"],
        check=True,
        capture_output=True,
    ).stdout


def extract(source: Path) -> dict[str, object]:
    cache: dict[str, tuple[bytes, object]] = {}

    def load(relative: str) -> object:
        if relative not in cache:
            payload = read_at_pin(source, relative)
            cache[relative] = (payload, parse(relative, payload))
        return cache[relative][1]

    figures = []
    for figure_id, relative, keys in FIGURES:
        figures.append(
            {
                "id": figure_id,
                "file": relative,
                "key": "/".join(
                    k if isinstance(k, str) else str(k) if isinstance(k, int) else "+".join(k)
                    for k in keys
                ),
                "value": pick(load(relative), keys),
            }
        )
    for figure_id, relative, keys, function in DERIVED:
        figures.append(
            {
                "id": figure_id,
                "file": relative,
                "key": f"{function.__name__}({'/'.join(keys)})",
                "derivation": " ".join((function.__doc__ or "").split()),
                "value": function(pick(load(relative), keys)),  # type: ignore[arg-type]
            }
        )
    files = []
    for relative in sorted(cache):
        payload = cache[relative][0]
        experiment, run = PRODUCED_BY[relative]
        files.append(
            {
                "path": relative,
                "sha256": digest(payload),
                "size": len(payload),
                "media_type": MEDIA_TYPES[Path(relative).suffix],
                "license": LICENSE,
                "producing_experiment": experiment,
                "producing_run": run,
            }
        )
    return {
        "repository": REPOSITORY,
        "commit": PIN,
        "license": LICENSE,
        "files": files,
        "figures": figures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    text = json.dumps(extract(args.source), indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    if args.check:
        if RECORDS.read_text() != text:
            print("results/records.json differs from the extraction", file=sys.stderr)
            return 1
        print("results/records.json matches the extraction")
        return 0
    RECORDS.write_text(text)
    print(f"wrote {RECORDS.relative_to(ROOT)} with {len(FIGURES) + len(DERIVED)} figures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
