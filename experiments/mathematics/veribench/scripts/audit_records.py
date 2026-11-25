#!/usr/bin/env python3
"""Check that the VeriBench study page agrees with its released records.

Reads results/records.json and README.md. It fails if a cited figure is missing,
a record is not tied to the pinned commit and a source digest, or a number in the
README differs from the record after rounding.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text()
RECORDS = json.loads((ROOT / "results" / "records.json").read_text())
FIGURES = {figure["id"]: figure["value"] for figure in RECORDS["figures"]}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS  {message}")


def number(value: float, places: int) -> str:
    return f"{value:.{places}f}"


def interval(values: list[float], places: int) -> str:
    return f"[{values[0]:.{places}f}, {values[1]:.{places}f}]"


def audit_provenance() -> None:
    require(
        re.fullmatch(r"[0-9a-f]{40}", RECORDS["commit"]) is not None, "records name a full commit"
    )
    require(RECORDS["commit"] in README, "README pins the commit that records.json names")
    require(
        all(re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) for item in RECORDS["files"]),
        "every source file has a SHA-256 digest",
    )
    paths = {item["path"] for item in RECORDS["files"]}
    require(
        all(figure["file"] in paths for figure in RECORDS["figures"]),
        "every figure names a digested source file",
    )
    require(len(FIGURES) == len(RECORDS["figures"]), "figure identifiers are unique")
    for path in sorted(paths):
        require(
            not path.startswith("/") and ".." not in Path(path).parts,
            f"{path} is a repository-relative path",
        )


def audit_text(claims: list[tuple[str, str]]) -> None:
    for figure_id, text in claims:
        require(figure_id in FIGURES, f"{figure_id} is recorded")
        require(text in README, f"README states {text} for {figure_id}")


def audit_numbers() -> None:
    g = FIGURES
    models = ("qwen3-1.7b", "qwen3-4b", "qwen3-8b", "qwen3.5-0.8b", "qwen3.5-2b", "qwen3.5-4b")
    require(g["e01.gate_g1.verdict"] == "PASS", "experiment 01 gate G1 passes")
    require(
        all(g[f"e01.{model}.kernel_binary_max_split"] == 0.0 for model in models),
        "six probed models have a mixed-group share of exactly 0.0",
    )
    require(
        g["e01.qwen3-14b.kernel_binary_max_split"] >= 0.20
        and g["e01.qwen3.5-9b.kernel_binary_max_split"] >= 0.20,
        "Qwen3-14B and Qwen3.5-9B reach 0.20 on some split",
    )
    shares = {
        m: g[f"e05.{m}.mixed_share"] for m in ("qwen3-1.7b-base", "qwen3-4b-base", "qwen3-8b-base")
    }
    require(
        sum(g[f"e05.{m}.cells_scored"] for m in shares) == 21504
        and all(g[f"e05.{m}.cells_declared"] == g[f"e05.{m}.cells_scored"] for m in shares),
        "experiment 05 scored all 21,504 declared cells",
    )
    require(
        all(g[f"e05.{m}.verdict"] == "SFT warm start needed" for m in shares),
        "experiment 05 verdict is that a warm start is needed",
    )
    require(
        "0.000 for 1.7B and 8B and 0.006 for 4B" in README, "README states the experiment 05 shares"
    )
    require(
        [number(shares[m], 3) for m in ("qwen3-1.7b-base", "qwen3-8b-base", "qwen3-4b-base")]
        == ["0.000", "0.000", "0.006"],
        "experiment 05 shares round to 0.000, 0.000, 0.006",
    )
    require(g["e08.verdict"] == "PARTIAL", "experiment 08 verdict is PARTIAL")
    require(
        g["e08.8B.first_passing_step"] == 658
        and g["e08.14B.first_passing_step"] == 334
        and g["e08.1.7B.earliest_passing_fraction"] is None
        and g["e08.4B.earliest_passing_fraction"] is None,
        "8B passes first at step 658, 14B at step 334, and 1.7B and 4B pass no rung",
    )
    require(
        g["e08.test.n_tasks"] == 222 and g["e08.test.selected_8B.known_cells"] == 1776,
        "222 test tasks, 1,776 known cells",
    )
    test_claims = []
    for label in ("selected_8B", "selected_14B", "base_8B", "base_14B"):
        point = number(g[f"e08.test.{label}.scsc"], 4)
        bounds = interval(g[f"e08.test.{label}.scsc_bootstrap95"], 4)
        test_claims.append(
            (f"e08.test.{label}.scsc", point + (" " + bounds if label != "base_8B" else ""))
        )
    audit_text(test_claims)
    require(
        g["e09.status"] == "FAILED_TECHNICAL_GATE" and g["e09.scientific_completion"] is False,
        "experiment 09 failed its technical gate",
    )
    require(
        "4/4077" in g["e09.reason_detail"], "experiment 09 failure detail matches the gate record"
    )
    audit_text(
        [
            ("e19.auc_irt_2pl", number(g["e19.auc_irt_2pl"], 3)),
            ("e19.auc_gate", number(g["e19.auc_gate"], 2)),
            ("e19.auc_features_only", number(g["e19.auc_features_only"], 3)),
            (
                "e25.u48.strict.pass_at_1",
                f"{g['e25.u48.strict.pass_at_1']:.2f}% " + interval(g["e25.u48.strict.ci95"], 2),
            ),
            (
                "e25.u48.smooth.pass_at_1",
                f"{g['e25.u48.smooth.pass_at_1']:.2f}% " + interval(g["e25.u48.smooth.ci95"], 2),
            ),
            (
                "e25.u48.smooth_minus_strict",
                f"{g['e25.u48.smooth_minus_strict']:.2f} points "
                + interval(g["e25.u48.smooth_minus_strict.ci95"], 2),
            ),
        ]
    )
    paired = g["e25.u48.seed_paired_smooth_minus_strict"]
    require(
        f"{paired['s0']:+.1f}, {paired['s1']:+.1f}, and {paired['s2']:+.1f} points" in README,
        "README states the seed-paired differences",
    )


def main() -> None:
    audit_provenance()
    audit_numbers()
    print("All VeriBench record checks passed")


if __name__ == "__main__":
    main()
