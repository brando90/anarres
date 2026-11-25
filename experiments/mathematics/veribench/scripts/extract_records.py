#!/usr/bin/env python3
"""Rebuild results/records.json from a pinned rl-4-code-verification checkout.

Usage:
    python3 scripts/extract_records.py --source PATH_TO_CHECKOUT [--check]

The checkout must be at the commit named in `PIN`. Without `--check`, the script
writes `results/records.json`. With `--check`, it compares the extraction with
the released file and exits nonzero on any difference.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / "results" / "records.json"
PIN = "139e8d9b47d44626035594c19d708d6b26a856cc"
REPOSITORY = "https://github.com/brando90/rl-4-code-verification"

E01 = (
    "experiments/01_small_open_models_veribench_v1_single_call_baseline"
    "/expt_v1/results/probe_channels_summary.json"
)
E05 = (
    "experiments/05_qwen3_base_models_vbv1_g8_pass_signal_sft_derisk"
    "/expt_v1/results/analysis_e05.json"
)
_E08 = (
    "experiments/08_qwen3_base_matched_lean_sft_opus55_astra_teachers_vbv1_train_val_test"
    "/expt_v1/results/"
)
E08_SELECTION = _E08 + "selection.json"
E08_TEST = _E08 + "test_eval.json"
E09 = (
    "experiments/09_qwen3_1p7b_grpo_scsc_scalar_vs_factor_feedback_vbv1_d013"
    "/expt_v1/results/terminal_receipt.json"
)
E19 = (
    "experiments/19_interpretable_irt_scsc_factors_predict_and_guide_strict_pass1_vbv1_d013"
    "/expt_v1/results/analysis_e19.json"
)
E25 = (
    "experiments/25_smooth_vs_strict_reward_grpo_qwen3_1p7b_sft_vbv1_3_d013"
    "/expt_v1/results/full_run_at2925/analysis_e25.json"
)

# Each figure: (id, source file, key path inside the JSON file).
FIGURES: list[tuple[str, str, tuple]] = [
    ("e01.gate_g1.verdict", E01, ("gate_g1", "verdict")),
    (
        "e01.qwen3-14b.kernel_binary_max_split",
        E01,
        ("gate_g1", "per_model", "qwen3-14b", "kernel_binary_max_split"),
    ),
    (
        "e01.qwen3.5-9b.kernel_binary_max_split",
        E01,
        ("gate_g1", "per_model", "qwen3.5-9b", "kernel_binary_max_split"),
    ),
    (
        "e01.qwen3.5-0.8b.kernel_binary_max_split",
        E01,
        ("gate_g1", "per_model", "qwen3.5-0.8b", "kernel_binary_max_split"),
    ),
    (
        "e01.qwen3.5-2b.kernel_binary_max_split",
        E01,
        ("gate_g1", "per_model", "qwen3.5-2b", "kernel_binary_max_split"),
    ),
    (
        "e01.qwen3.5-4b.kernel_binary_max_split",
        E01,
        ("gate_g1", "per_model", "qwen3.5-4b", "kernel_binary_max_split"),
    ),
    (
        "e01.qwen3-1.7b.kernel_binary_max_split",
        E01,
        ("gate_g1", "per_model", "qwen3-1.7b", "kernel_binary_max_split"),
    ),
    (
        "e01.qwen3-4b.kernel_binary_max_split",
        E01,
        ("gate_g1", "per_model", "qwen3-4b", "kernel_binary_max_split"),
    ),
    (
        "e01.qwen3-8b.kernel_binary_max_split",
        E01,
        ("gate_g1", "per_model", "qwen3-8b", "kernel_binary_max_split"),
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
FIGURES += [
    ("e09.status", E09, ("status",)),
    ("e09.reason", E09, ("reason",)),
    ("e09.reason_detail", E09, ("reason_detail",)),
    ("e09.scientific_completion", E09, ("scientific_completion",)),
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
    ("e19.auc_irt_2pl", E19, ("G1", "auc_primary_vs_gate", "estimate")),
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
]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pick(document: object, keys: tuple) -> object:
    """Follow a key path. A final tuple of keys picks several values as a list."""
    for key in keys:
        if isinstance(key, tuple):
            return [document[name] for name in key]  # type: ignore[index]
        document = document[key]  # type: ignore[index]
    return document


def extract(source: Path) -> dict[str, object]:
    head = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if head != PIN:
        raise SystemExit(f"checkout is at {head}, expected {PIN}")
    cache: dict[str, object] = {}
    files: dict[str, str] = {}
    figures = []
    for figure_id, relative, keys in FIGURES:
        if relative not in cache:
            path = source / relative
            cache[relative] = json.loads(path.read_text())
            files[relative] = digest(path)
        figures.append(
            {
                "id": figure_id,
                "file": relative,
                "key": "/".join(k if isinstance(k, str) else "+".join(k) for k in keys),
                "value": pick(cache[relative], keys),
            }
        )
    return {
        "repository": REPOSITORY,
        "commit": PIN,
        "files": [{"path": path, "sha256": files[path]} for path in sorted(files)],
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
    print(f"wrote {RECORDS.relative_to(ROOT)} with {len(FIGURES)} figures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
