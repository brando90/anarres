#!/usr/bin/env python3
"""Check that the VeriBench study page agrees with its released records.

Usage:
    python3 scripts/audit_records.py [--source PATH_TO_CHECKOUT]

Reads results/records.json and README.md. It fails if a cited figure is missing,
a record lacks its artifact reference (digest, size, media type, license, producing
experiment), a link to the external repository does not carry the pinned commit,
or a number or count in the README differs from the record after rounding. With
`--source`, it also recomputes each source digest and size from the pinned commit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_FIELDS = (
    "sha256",
    "size",
    "media_type",
    "license",
    "producing_experiment",
    "producing_run",
)
SINGLE_CALL = (
    "qwen3.5-0.8b",
    "qwen3.5-2b",
    "qwen3.5-4b",
    "qwen3.5-9b",
    "qwen3-1.7b",
    "qwen3-4b",
    "qwen3-8b",
    "qwen3-14b",
    "qwen3.6-27b-local",
)
PROBED = SINGLE_CALL[:-1]
BASE_MODELS = ("qwen3-1.7b-base", "qwen3-4b-base", "qwen3-8b-base")
EXPERIMENT_LINKS = ("01", "05", "08", "09", "19", "25")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS  {message}")


def interval(values: list[float], places: int, sign: bool = False) -> str:
    flag = "+" if sign else ""
    return f"[{values[0]:{flag}.{places}f}, {values[1]:{flag}.{places}f}]"


def audit_provenance(records: dict, readme: str) -> None:
    commit = records["commit"]
    require(re.fullmatch(r"[0-9a-f]{40}", commit) is not None, "records name a full commit")
    require(f"`{commit}`" in readme, "README states the commit that records.json names")
    pins = re.findall(r"rl-4-code-verification/blob/([0-9a-zA-Z._-]+)/", readme)
    require(
        len(pins) >= len(EXPERIMENT_LINKS) and set(pins) == {commit},
        f"all {len(pins)} README links to the external repository carry the pinned commit",
    )
    for number in EXPERIMENT_LINKS:
        require(
            re.search(rf"blob/{commit}/experiments/{number}_[^)]*/results\.md\)", readme)
            is not None,
            f"README links the experiment {number} results file at the pin",
        )
    require(records.get("license") == "Apache-2.0", "records name the external license")
    for item in records["files"]:
        path = item["path"]
        require(
            all(field in item and item[field] not in (None, "") for field in ARTIFACT_FIELDS),
            f"{path} carries digest, size, media type, license, and producing run",
        )
        require(
            re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is not None
            and item["sha256"] != "0" * 64
            and isinstance(item["size"], int)
            and item["size"] > 0
            and item["media_type"] == "application/json",
            f"{path} has a plausible digest, a positive size, and a media type",
        )
        require(
            not path.startswith("/") and ".." not in Path(path).parts,
            f"{path} is a repository-relative path",
        )
    paths = {item["path"] for item in records["files"]}
    require(len(paths) == len(records["files"]), "source files are listed once")
    require(
        all(figure["file"] in paths for figure in records["figures"]),
        "every figure names a digested source file",
    )
    ids = [figure["id"] for figure in records["figures"]]
    require(len(set(ids)) == len(ids), "figure identifiers are unique")
    require("/home/" not in readme and "/Users/" not in readme, "README names no machine path")


def verify_digests(records: dict, source: Path) -> None:
    """Recompute each source file's digest and size from the pinned commit."""
    for item in records["files"]:
        payload = subprocess.run(
            ["git", "-C", str(source), "show", f"{records['commit']}:{item['path']}"],
            check=True,
            capture_output=True,
        ).stdout
        require(
            hashlib.sha256(payload).hexdigest() == item["sha256"] and len(payload) == item["size"],
            f"{item['path']} matches its recorded digest and size at the pin",
        )


def audit_numbers(records: dict, readme: str) -> None:
    g = {figure["id"]: figure["value"] for figure in records["figures"]}

    def states(text: str, why: str) -> None:
        require(text in readme, f"README states {text!r}: {why}")

    # Experiment 01.
    require(g["e01.gate_g1.verdict"] == "PASS", "experiment 01 gate G1 is recorded as PASS")
    states("gate G1 is PASS", "e01.gate_g1.verdict")
    require(g["e01.gate_g1.locked_channel"] == "kernel_binary", "the locked channel is recorded")
    require(
        all(g[f"e01.{m}.cells"] == 896 for m in SINGLE_CALL) and len(SINGLE_CALL) == 9,
        "nine models were run on 896 cells each",
    )
    states("Nine models were run once on all 896 tasks", "nine labels, 896 cells each")
    proved = {m: g[f"e01.{m}.compiling_proved_cells"] for m in SINGLE_CALL}
    require(
        proved["qwen3-14b"] == 1 and sum(proved.values()) == 1,
        "only Qwen3-14B has a cell with positive test and proof factors, and it has one",
    )
    states(
        "Qwen3-14B produced one cell with positive test and proof factors in 896, and the other"
        " eight models produced none",
        "e01 compiling_proved_cells",
    )
    require(
        all(g[f"e01.{m}.probe_tasks"] == 128 and g[f"e01.{m}.probe_rows"] == 1024 for m in PROBED),
        "eight models were probed on 128 tasks with eight samples each",
    )
    states("An eight-sample probe of 128 tasks (4 per split) covered eight of the nine models", "")
    states("Qwen3.6-27B was not probed", "e01 probed labels exclude qwen3.6-27b-local")
    shares = {m: g[f"e01.{m}.probe_mixed_share"] for m in PROBED}
    counts = {m: round(shares[m] * g[f"e01.{m}.probe_tasks"]) for m in PROBED}
    require(
        counts["qwen3-14b"] == 6 and counts["qwen3.5-9b"] == 4 and sum(counts.values()) == 10,
        "Qwen3-14B and Qwen3.5-9B have 6 and 4 mixed probe tasks and no other model has any",
    )
    states(
        f"Qwen3-14B had mixed groups on {counts['qwen3-14b']} of 128 probe tasks (share"
        f" {shares['qwen3-14b']:.3f}) and Qwen3.5-9B on {counts['qwen3.5-9b']}"
        f" (share {shares['qwen3.5-9b']:.3f})",
        "e01 probe_mixed_share",
    )
    best = [g["e01.qwen3-14b.kernel_binary_max_split"], g["e01.qwen3.5-9b.kernel_binary_max_split"]]
    require(all(value >= 0.20 for value in best), "both models reach 0.20 on some split")
    require(
        all(g[f"e01.{m}.kernel_binary_max_split"] == 0.0 for m in PROBED[:3] + PROBED[4:7]),
        "the other six probed models have a best split share of exactly 0.0",
    )
    states(
        f"with a best split share of {best[0]:.3f} and {best[1]:.3f}", "e01 kernel_binary_max_split"
    )
    states("The other six probed models had none.", "six zero shares")
    states("locked 0.20 `kernel_binary` per-split threshold", "e01 locked channel and threshold")

    # Experiment 05.
    cells = sum(g[f"e05.{m}.cells_scored"] for m in BASE_MODELS)
    require(
        all(
            g[f"e05.{m}.cells_declared"] == g[f"e05.{m}.cells_scored"] == 896 * 8
            for m in BASE_MODELS
        ),
        "experiment 05 scored every declared cell, 896 tasks with eight samples per model",
    )
    states(f"All {cells:,} cells (three Qwen3 Base models, 896 tasks each, eight samples", "e05")
    require(
        all(g[f"e05.{m}.verdict"] == "SFT warm start needed" for m in BASE_MODELS),
        "experiment 05 verdict is that a warm start is needed",
    )
    states("The verdict is that a supervised warm start is needed", "e05 verdict")
    share = {
        m: (g[f"e05.{m}.mixed_share"], g[f"e05.{m}.mixed_share_wilson95"]) for m in BASE_MODELS
    }
    low = f"{share['qwen3-1.7b-base'][0]:.3f} {interval(share['qwen3-1.7b-base'][1], 3)}"
    mid = f"{share['qwen3-4b-base'][0]:.3f} {interval(share['qwen3-4b-base'][1], 3)}"
    require(
        low == f"{share['qwen3-8b-base'][0]:.3f} {interval(share['qwen3-8b-base'][1], 3)}",
        "1.7B and 8B have the same mixed-group share and interval",
    )
    states(f"is {low} for 1.7B and 8B and {mid} for 4B", "e05 mixed_share_wilson95")
    states("against a 0.05 decision threshold", "experiment 05 protocol")

    # Experiment 08.
    require(g["e08.verdict"] == "PARTIAL", "experiment 08 verdict is PARTIAL")
    states(f"gives {g['e08.verdict']} on the frozen validation rule", "e08.verdict")
    require(
        g["e08.1.7B.earliest_passing_fraction"] is None
        and g["e08.4B.earliest_passing_fraction"] is None,
        "1.7B and 4B pass no rung",
    )
    states(
        f"8B first passes at step {g['e08.8B.first_passing_step']} and 14B at step"
        f" {g['e08.14B.first_passing_step']}. The 1.7B and 4B models pass no rung",
        "e08 gate table",
    )
    cells_all = g["e08.test.selected_8B.known_cells"]
    require(
        cells_all == 8 * g["e08.test.n_tasks"],
        "known cells are eight samples for each test task",
    )
    states(f"On {g['e08.test.n_tasks']} held-out test tasks with eight samples each", "e08 test")
    for label in ("selected_8B", "selected_14B", "base_8B", "base_14B"):
        point = f"{g[f'e08.test.{label}.scsc']:.4f}"
        bound = interval(g[f"e08.test.{label}.scsc_bootstrap95"], 4)
        states(point + (" " + bound if label != "base_8B" else ""), f"e08 {label} SCSC")
    core = g["e08.test.8B.core.shared_known_cells"] // 8
    industry = g["e08.test.8B.industryset.shared_known_cells"] // 8
    require(
        core + industry == g["e08.test.n_tasks"]
        and g["e08.test.14B.core.shared_known_cells"] == 8 * core
        and g["e08.test.14B.industryset.shared_known_cells"] == 8 * industry,
        "core and IndustrySet test tasks add up to the test split for both sizes",
    )
    require(
        g["e08.test.8B.core.scsc_difference"] > 0 and g["e08.test.14B.core.scsc_difference"] > 0,
        "the gain over Base is positive on the core for both sizes",
    )
    d8 = g["e08.test.8B.industryset.scsc_difference"]
    d14 = g["e08.test.14B.industryset.scsc_difference"]
    b14 = g["e08.test.14B.industryset.scsc_difference_bootstrap95"]
    states(
        f"The gain lies on the {core}-task core. On the {industry} IndustrySet test tasks the 8B"
        f" difference is {d8:.4f} and the 14B difference is {d14:.4f} {interval(b14, 4)}",
        "e08 paired differences",
    )
    fractions = (g["e08.8B.earliest_passing_fraction"], g["e08.14B.earliest_passing_fraction"])
    states(f"(8B at {float(fractions[0]):.1f}, 14B at {float(fractions[1]):.1f})", "e08 selection")

    # Experiment 09.
    require(
        g["e09.status"] == "FAILED_TECHNICAL_GATE" and g["e09.scientific_completion"] is False,
        "experiment 09 failed its technical gate",
    )
    match = re.match(r"(\d+)/(\d+) generated actions outside", g["e09.reason_detail"])
    require(match is not None, "experiment 09 failure detail names the actions outside support")
    states(
        f"{match[1]} of {int(match[2]):,} generated actions fell outside the recomputed"  # type: ignore[index]
        " old-policy support",
        "e09 reason_detail",
    )

    # Experiment 19.
    mixed, tasks = g["e19.mixed_tasks"], g["e19.tasks"]
    states(
        f"separates the {mixed} validation tasks with mixed groups from the other"
        f" {tasks - mixed} with AUC {g['e19.auc_irt_2pl']:.3f}"
        f" {interval(g['e19.auc_irt_2pl.ci95'], 3)}, above the {g['e19.auc_gate']:.2f} gate",
        "e19 AUC",
    )
    require(g["e19.auc_irt_2pl"] > g["e19.auc_gate"], "the IRT AUC is above the gate")
    states(
        f"{g['e19.auc_irt_minus_panel_strict_rate']:+.3f}"
        f" {interval(g['e19.auc_irt_minus_panel_strict_rate_ci95'], 3, sign=True)}",
        "e19 margin over the panel pass rate",
    )
    low_bound, high_bound = g["e19.auc_irt_minus_panel_strict_rate_ci95"]
    require(low_bound < 0 < high_bound, "the margin over the panel pass rate spans zero")
    states(f"the experiment's own verdict is {g['e19.verdict_g1']}", "e19 verdicts")
    states(f"task features alone reach {g['e19.auc_features_only']:.3f}", "e19 features-only AUC")
    require(g["e19.irt_beats_baselines_strict"] is False, "the second endpoint is not supported")
    states("was not supported", "e19 strict endpoint")
    states(f"Forecast on {tasks} validation tasks", "e19 tasks")

    # Experiment 25.
    start = g["e25.u0.strict_successes"] / g["e25.u0.cells"]
    require(abs(start - g["e25.u0.pass_at_1"]) < 1e-12, "update-0 pass@1 is successes over cells")
    per_run = g["e25.u48.cells_per_run"]
    require(per_run % g["e25.tasks"] == 0, "cells per run are a whole number of samples per task")
    states(
        f"strict pass@1 {100 * g['e25.u0.pass_at_1']:.2f}% at update 0",
        "e25 update-0 record",
    )
    states(
        f"{g['e25.tasks']} validation tasks with {per_run // g['e25.tasks']} samples each"
        f" ({per_run:,} cells per run)",
        "e25 evaluation size",
    )
    strict, smooth = g["e25.u48.strict.pass_at_1"], g["e25.u48.smooth.pass_at_1"]
    states(
        f"strict pass@1 is {strict:.2f}% {interval(g['e25.u48.strict.ci95'], 2)} with the strict"
        f" reward and {smooth:.2f}% {interval(g['e25.u48.smooth.ci95'], 2)} with the smooth reward",
        "e25 pooled pass@1",
    )
    states(
        f"Smooth minus strict is {g['e25.u48.smooth_minus_strict']:.2f} points"
        f" {interval(g['e25.u48.smooth_minus_strict.ci95'], 2)}",
        "e25 difference",
    )
    paired = g["e25.u48.seed_paired_smooth_minus_strict"]
    states(
        f"{paired['s0']:+.1f}, {paired['s1']:+.1f}, and {paired['s2']:+.1f} points",
        "e25 seed-paired differences",
    )
    states(
        "exact permutation test over the six run means gives"
        f" p={g['e25.u48.run_level_permutation_p']:.2f}",
        "e25 derived permutation test",
    )


def run(root: Path, source: Path | None = None) -> None:
    readme = (root / "README.md").read_text()
    records = json.loads((root / "results" / "records.json").read_text())
    audit_provenance(records, readme)
    if source is not None:
        verify_digests(records, source)
    audit_numbers(records, readme)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, help="checkout of the external repository")
    args = parser.parse_args()
    run(ROOT, args.source)
    print("All VeriBench record checks passed")


if __name__ == "__main__":
    main()
