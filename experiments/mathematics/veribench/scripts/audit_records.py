#!/usr/bin/env python3
"""Check that the VeriBench study page agrees with its released records.

Usage:
    python3 scripts/audit_records.py [--source PATH_TO_CHECKOUT]

Reads results/records.json and README.md. It fails if a cited figure is missing,
a record lacks its artifact reference (digest, size, media type, license, producing
experiment), a link to the external repository does not carry the pinned commit,
or a statement in the README differs from the record after rounding. Each statement
is checked inside the table row and scope item of the experiment it describes, or
inside its named paragraph, with the model, update, and scope it names. With
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
# Named paragraphs, found by their opening words.
PARAGRAPHS = {
    "tasks": "**Tasks and splits.**",
    "outcomes": "**Outcomes.**",
    "exposure": "These measurements are retrospective development evidence",
    "namespace": "The VeriBench task instruction suggests",
}
NUMBER_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 8: "eight"}
LANDSCAPE = ROOT.parents[1] / "cyber" / "formal-verification" / "SOURCE_LANDSCAPE.md"
MEDIA_TYPES = {
    "application/json",
    "text/csv",
    "text/x-python",
    "text/x-shellscript",
    "application/yaml",
}


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
            and item["media_type"] in MEDIA_TYPES,
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


def number_word(value: int) -> str:
    return NUMBER_WORDS.get(value, f"{value:,}")


def series(items: list[str]) -> str:
    """Join items as an English series with a serial comma."""
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + ", and " + items[-1]


def sections(readme: str) -> dict[str, str]:
    """Each experiment's table row and scope item, and each named paragraph, keyed by name.

    A statement is checked only inside the section it describes, so a figure that is correct
    for one model or experiment cannot vouch for a sentence about another.
    """
    lines = readme.splitlines()
    found: dict[str, str] = {}
    for number in EXPERIMENT_LINKS:
        rows = [
            line for line in lines if line.startswith("| [") and f"/experiments/{number}_" in line
        ]
        items = [line for line in lines if line.startswith(f"- **Experiment {number}.**")]
        require(
            len(rows) == 1 and len(items) == 1,
            f"README has one table row and one scope item for experiment {number}",
        )
        found[number] = rows[0] + "\n" + items[0]
    for name, prefix in PARAGRAPHS.items():
        matches = [line for line in lines if line.startswith(prefix)]
        require(len(matches) == 1, f"README has one {name} paragraph")
        found[name] = matches[0]
    return found


def update_of(key: str) -> int:
    """Update number named in a record key such as bootstrap_points/u48/A/point."""
    match = re.search(r"(?:^|/|_)u0*(\d+)(?:/|$)", key)
    if match is None:
        raise AssertionError(f"record key {key!r} names no update")
    return int(match[1])


def audit_numbers(records: dict, readme: str) -> None:
    g = {figure["id"]: figure["value"] for figure in records["figures"]}
    keys = {figure["id"]: figure["key"] for figure in records["figures"]}
    sources = {figure["id"]: figure["file"] for figure in records["figures"]}
    files = {item["path"]: item for item in records["files"]}
    text = sections(readme)

    def states(section: str, claim: str, why: str) -> None:
        require(claim in text[section], f"README {section} states {claim!r}: {why}")

    # Tasks, versions, and the D-013 split.
    counts = g["e08.split.counts"]
    tasks = g["e08.split.tasks"]
    core, industry = sum(counts["core_614"].values()), sum(counts["industryset_282"].values())
    families = g["e01.probe_tasks_per_family"]
    require(core + industry == tasks == sum(counts["all"].values()), "core and IndustrySet add up")
    states(
        "tasks",
        f"VeriBench V1 has {tasks} tasks, a {core}-task core and a {industry}-task IndustrySet,"
        f" in {sum(families.values())} benchmark families",
        "e08 split summary and e01 probe families",
    )
    states(
        "tasks",
        f"task packs at VeriBench commit `{g['e08.split.veribench_commit'][:8]}` and the scorer at"
        f" `{g['e08.scorer_commit'][:8]}`",
        "e08 split summary and scorer adapter check",
    )
    states("tasks", "The external experiments label this task set `veribench@1.3`", "prose")
    require(
        re.search(
            rf"\[experiment 25 protocol\]\([^)]*blob/{records['commit']}/experiments/25_[^)]*"
            r"/PROTOCOL\.md#L9\)",
            text["tasks"],
        )
        is not None,
        "the version label links the experiment 25 protocol line at the pin",
    )
    candidate = re.search(
        r"unmerged\s+Harbor\s+v1\.3\s+candidate\s+at\s+commit\s+`([0-9a-f]+)`",
        LANDSCAPE.read_text(),
    )
    require(candidate is not None, "the source landscape records the Harbor v1.3 candidate")
    states(
        "tasks",
        f"unmerged Harbor v1.3 candidate at commit `{candidate[1]}`",  # type: ignore[index]
        "SOURCE_LANDSCAPE.md",
    )
    require(
        not g["e08.split.veribench_commit"].startswith(candidate[1]),  # type: ignore[index]
        "the external task-pack pin differs from the Harbor candidate commit",
    )
    states("tasks", "source qualification remains pending for both", "no qualification yet")
    split = counts["all"]
    require(g["e08.split.decision"] == "D-013", "the split summary is decision D-013")
    states(
        "tasks",
        f"D-013 is the external repository's split of the {tasks} tasks into {split['train']}"
        f" train, {split['validation']} validation, and {split['test']} test tasks",
        "e08 split counts",
    )
    require(g["e08.split.clusters_spanning_splits"] == 0, "no task cluster spans two splits")
    states("tasks", "every task cluster lies in one split", "e08 split manifest")
    manifest = files[sources["e08.split.digit_leading_stems"]]
    require(
        manifest["sha256"] == g["e08.split.manifest_sha256"],
        "the split manifest digest equals the digest the split summary records",
    )

    # Outcome definitions.
    rule = g["e08.test.aggregate_rule"]
    require(
        "(mean IC_tests · mean IC_proofs · mean fsc_compiled)^(1/3)" in rule
        and "fsc_compiled = FSC when IC_tests = 1 else 0" in rule,
        "experiment 08 defines SCSC as the cube root of three factor means",
    )
    states(
        "outcomes",
        "It is the cube root of the product of the mean IC_tests, the mean IC_proofs, and the mean"
        " FSC over a model's cells, with FSC counted as 0 when IC_tests is 0",
        "e08 aggregate rule",
    )
    require(
        g["kernel_binary.definition"]
        == "1 only for a fully verified file: typechecks, has an example, every stated theorem"
        " proved, none vacuous.",
        "the kernel_binary reward keeps its definition",
    )
    axioms = g["kernel_binary.allowed_axioms"]
    require(
        axioms == ["propext", "Classical.choice", "Quot.sound"],
        "the rewards restrict kernel axioms to propext, Classical.choice, and Quot.sound",
    )
    states(
        "outcomes",
        "IC_proofs is the fraction of stated theorems that the Lean kernel accepts with axioms"
        f" restricted to {series([f'`{name}`' for name in axioms])}",
        "rl4cv rewards docstring",
    )
    require(
        g["kernel_binary.conditions"]
        == [
            "s.ic_tests == 1.0",
            "s.n_theorems_stated >= 1",
            "s.n_theorems_proved == s.n_theorems_stated",
            "s.vacuous_theorems == 0",
        ],
        "kernel_binary joins typechecking with an example, a theorem, all proved, and zero vacuity",
    )
    states(
        "outcomes",
        "`kernel_binary` is 1 when the extracted file typechecks, has an example, states at least"
        " one theorem, every stated theorem is proved with those axioms only, and the recorded"
        " vacuous-theorem count is zero",
        "rl4cv rewards",
    )
    require(
        g["e01.run_uses_collect"] and g["e05.run_uses_collect"] and not g["e25.evaluation_reads_vacuity"],
        "experiments 01, 05, and 25 build rows with a reader that leaves the vacuity count at zero",
    )
    require(
        g["e08.ladder_sets_vacuity"]
        and g["e08.screen_uses_statement_check"]
        and "literally True or a syntactic self-equality" in g["rewards.vacuity_screen_comment"],
        "experiment 08 fills the vacuity count with the syntactic statement screen",
    )
    states(
        "outcomes",
        "Experiments 01, 05, and 25 read scorer rows without setting it, so it stays zero there,"
        " and experiment 08 fills it with a syntactic screen that flags a theorem whose conclusion"
        " is literally `True` or a self-equality. A `kernel_binary` value of 1 therefore does not"
        " establish that a theorem is non-vacuous.",
        "scorer-row reader and experiment 08 screen",
    )
    require(
        g["e19.strict_rule"] == "ict == 1.0 and icp == 1.0",
        "experiment 19 strict success is IC_tests = 1 and IC_proofs = 1",
    )
    require(
        g["e25.strict_function"] == "reward_kernel_binary",
        "experiment 25 strict success is the kernel_binary reward of each scored cell",
    )
    states(
        "outcomes",
        "Experiment 19 reports strict success, which is 1 when IC_tests and IC_proofs both equal 1."
        " Experiment 25 reports strict success as the `kernel_binary` value of each scored cell.",
        "e19 panel loader and e25 analysis",
    )
    states("outcomes", "Neither `kernel_binary` nor strict success includes FSC", "definitions")
    states("outcomes", "A group is the eight responses sampled for one task", "G = 8")

    # Test exposure.
    require(
        all(g[f"e01.{m}.cells"] == tasks for m in SINGLE_CALL)
        and all(g[f"e05.{m}.tasks_measured"] == tasks for m in BASE_MODELS)
        and g["e08.test.n_tasks"] == split["test"],
        "experiments 01 and 05 measured every task, and experiment 08 tested the D-013 test split",
    )
    states(
        "exposure",
        f"Experiments 01 and 05 evaluated all {tasks} tasks before D-013. Experiment 08 used D-013"
        " train and validation for training and selection, then evaluated each selected trained"
        f" checkpoint once on its {g['e08.test.n_tasks']} test tasks. Historical baseline and"
        " teacher outcomes on those tasks had already been inspected.",
        "e01 cells, e05 tasks, e08 test tasks",
    )

    # Experiment 01.
    require(g["e01.gate_g1.verdict"] == "PASS", "experiment 01 gate G1 is recorded as PASS")
    states("01", "gate G1 is PASS", "e01.gate_g1.verdict")
    require(g["e01.gate_g1.locked_channel"] == "kernel_binary", "the locked channel is recorded")
    require(len(SINGLE_CALL) == 9, "nine single-call models")
    states("01", f"Nine models were run once on all {tasks} tasks", "nine labels, 896 cells each")
    proved = {m: g[f"e01.{m}.compiling_proved_cells"] for m in SINGLE_CALL}
    require(
        proved["qwen3-14b"] == 1 and sum(proved.values()) == 1,
        "only Qwen3-14B has a cell with positive IC_tests and IC_proofs, and it has one",
    )
    states(
        "01",
        f"Qwen3-14B produced one cell with positive IC_tests and IC_proofs in {tasks}, and the"
        " other eight models produced none",
        "e01 compiling_proved_cells",
    )
    probe = g["e01.qwen3-14b.probe_tasks"]
    require(
        all(
            g[f"e01.{m}.probe_tasks"] == probe and g[f"e01.{m}.probe_rows"] == 8 * probe
            for m in PROBED
        ),
        "eight models were probed on the same tasks with eight samples each",
    )
    per_family = {int(size): count for size, count in families.items()}
    require(
        sum(size * count for size, count in per_family.items()) == probe,
        "the probe tasks per benchmark family add up to the probe",
    )
    states(
        "01",
        f"An eight-sample probe of {probe} tasks (up to {max(per_family)} per benchmark family)"
        " covered eight of the nine models",
        "e01 probe families",
    )
    states(
        "01",
        series(
            [
                (f"{count} families hold {size}" if count > 1 else f"one holds {size}")
                + (" probe tasks" if index == 0 else "")
                for index, (size, count) in enumerate(sorted(per_family.items(), reverse=True))
            ]
        ),
        "e01 probe tasks per benchmark family",
    )
    states("01", "Qwen3.6-27B was not probed", "e01 probed labels exclude qwen3.6-27b-local")
    shares = {m: g[f"e01.{m}.probe_mixed_share"] for m in PROBED}
    mixed = {m: round(shares[m] * g[f"e01.{m}.probe_tasks"]) for m in PROBED}
    require(
        mixed["qwen3-14b"] == 6 and mixed["qwen3.5-9b"] == 4 and sum(mixed.values()) == 10,
        "Qwen3-14B and Qwen3.5-9B have 6 and 4 mixed probe tasks and no other model has any",
    )
    states(
        "01",
        f"Qwen3-14B had mixed groups on {mixed['qwen3-14b']} of {probe} probe tasks (share"
        f" {shares['qwen3-14b']:.3f}) and Qwen3.5-9B on {mixed['qwen3.5-9b']}"
        f" (share {shares['qwen3.5-9b']:.3f})",
        "e01 probe_mixed_share",
    )
    best = [g["e01.qwen3-14b.kernel_binary_max_split"], g["e01.qwen3.5-9b.kernel_binary_max_split"]]
    require(all(value >= 0.20 for value in best), "both models reach 0.20 on some family")
    require(
        all(g[f"e01.{m}.kernel_binary_max_split"] == 0.0 for m in PROBED[:3] + PROBED[4:7]),
        "the other six probed models have a best family share of exactly 0.0",
    )
    states(
        "01",
        "Each reached the locked 0.20 `kernel_binary` threshold in at least one benchmark family,"
        f" with a best family share of {best[0]:.3f} and {best[1]:.3f}",
        "e01 kernel_binary_max_split",
    )
    states("01", "The other six probed models had none.", "six zero shares")

    # Experiment 05.
    cells = sum(g[f"e05.{m}.cells_scored"] for m in BASE_MODELS)
    require(
        all(
            g[f"e05.{m}.cells_declared"] == g[f"e05.{m}.cells_scored"] == tasks * 8
            for m in BASE_MODELS
        ),
        "experiment 05 scored every declared cell, 896 tasks with eight samples per model",
    )
    states(
        "05",
        f"All {cells:,} cells (three Qwen3 Base models, {tasks} tasks each, eight samples per task)"
        " were kernel-scored",
        "e05 execution",
    )
    require(
        all(
            not any("fsc" in name or "scsc" in name for name in g[f"e05.{m}.channels"])
            for m in BASE_MODELS
        ),
        "experiment 05 records no FSC or SCSC channel",
    )
    states("05", "FSC and SCSC were not measured", "e05 channels")
    require(
        all(g[f"e05.{m}.verdict"] == "SFT warm start needed" for m in BASE_MODELS),
        "experiment 05 verdict is that a warm start is needed",
    )
    states("05", "The verdict is that a supervised warm start is needed", "e05 verdict")
    share = {
        m: (g[f"e05.{m}.mixed_share"], g[f"e05.{m}.mixed_share_wilson95"]) for m in BASE_MODELS
    }
    low = f"{share['qwen3-1.7b-base'][0]:.3f} {interval(share['qwen3-1.7b-base'][1], 3)}"
    mid = f"{share['qwen3-4b-base'][0]:.3f} {interval(share['qwen3-4b-base'][1], 3)}"
    require(
        low == f"{share['qwen3-8b-base'][0]:.3f} {interval(share['qwen3-8b-base'][1], 3)}",
        "1.7B and 8B have the same mixed-group share and interval",
    )
    states(
        "05",
        f"mixed-group share over {tasks} tasks per model is {low} for 1.7B and 8B and {mid} for 4B",
        "e05 mixed_share_wilson95",
    )
    require(
        all(keys[f"e05.{m}.mixed_share_wilson95"].endswith("wilson95") for m in BASE_MODELS),
        "experiment 05 intervals are 95% Wilson intervals",
    )
    states("05", "The intervals are 95% Wilson intervals over tasks", "e05 interval key")
    states("05", "against a 0.05 decision threshold", "experiment 05 protocol")

    # Experiment 08.
    require(g["e08.verdict"] == "PARTIAL", "experiment 08 verdict is PARTIAL")
    states("08", f"gives {g['e08.verdict']} on the frozen validation rule", "e08.verdict")
    require(
        g["e08.1.7B.earliest_passing_fraction"] is None
        and g["e08.4B.earliest_passing_fraction"] is None,
        "1.7B and 4B pass no rung",
    )
    states(
        "08",
        f"8B first passes at step {g['e08.8B.first_passing_step']} and 14B at step"
        f" {g['e08.14B.first_passing_step']}. The 1.7B and 4B models pass no rung",
        "e08 gate table",
    )
    require(
        g["e08.test.selected_8B.known_cells"] == 8 * g["e08.test.n_tasks"],
        "known cells are eight samples for each test task",
    )
    test_tasks = g["e08.test.n_tasks"]
    states("08", f"On {test_tasks} held-out test tasks with eight samples each", "e08 test")

    def scored(label: str) -> str:
        point = f"{g[f'e08.test.{label}.scsc']:.4f}"
        return (
            point
            if label == "base_8B"
            else f"{point} {interval(g[f'e08.test.{label}.scsc_bootstrap95'], 4)}"
        )

    states(
        "08",
        f"SCSC is {scored('selected_8B')} for the selected 8B model against {scored('base_8B')}"
        f" for Base 8B, and {scored('selected_14B')} for the selected 14B model against"
        f" {scored('base_14B')} for Base 14B",
        "e08 SCSC per model",
    )
    require(
        g["e08.test.base_8B.scsc_bootstrap95"] == [0.0, 0.0],
        "the Base 8B interval is degenerate at zero, so the page omits it",
    )
    core_test = g["e08.test.8B.core.shared_known_cells"] // 8
    industry_test = g["e08.test.8B.industryset.shared_known_cells"] // 8
    require(
        core_test + industry_test == test_tasks
        and core_test == counts["core_614"]["test"]
        and g["e08.test.14B.core.shared_known_cells"] == 8 * core_test
        and g["e08.test.14B.industryset.shared_known_cells"] == 8 * industry_test,
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
        "08",
        f"The gain lies on the {core_test}-task core. On the {industry_test} IndustrySet test tasks"
        f" the 8B difference is {d8:.4f} and the 14B difference is {d14:.4f} {interval(b14, 4)}",
        "e08 paired differences",
    )
    states(
        "08",
        "Retrospective. Each selected trained checkpoint was evaluated once after selection.",
        "e08 test exposure",
    )
    seeds = {g["e08.8B.training_seed"], g["e08.14B.training_seed"]}
    require(len(seeds) == 1, "the selected 8B and 14B configs share one training seed")
    states("08", f"one training run per size, with training seed {seeds.pop()}", "e08 configs")
    revision = g["e08.training.nemo_revision"][:8]
    require(g["e08.training.precision"] == "bf16", "experiment 08 trained in bf16")
    states(
        "08",
        f"trained by supervised fine-tuning in bf16 with NeMo RL at revision `{revision}`",
        "e08 training completion record",
    )
    generation = g["e08.ladder_generation"]
    require(
        generation["module"] == "rl4cv.veribench.generate" and generation["thinking"] == "on",
        "experiment 08 generates through rl4cv.veribench.generate with thinking on",
    )
    states(
        "08",
        f"Evaluation used `{generation['module']}` with thinking {generation['thinking']} and"
        f" sampler seed {generation['seed']}",
        "e08 ladder script",
    )
    requests = g["e08.judge.requests"]
    efforts = g["e08.judge.efforts"]
    require(
        len(requests) == 4
        and {tuple(request) for request in requests.values()}
        == {
            ("vb103_judge", "anthropic/claude-opus-5-5-no-fallback"),
            ("vb103_judge", "openai/gpt-6-sol-high"),
        }
        and efforts == {"H2_opus55_max": "max", "H2_sol_high": "high"},
        "both selected-model FSC runs request Sol at high effort and Opus 5.5 at max effort",
    )
    for size in ("8B", "14B"):
        require(
            sorted(g[f"e08.judge.{size}.configs"]) == ["H2_opus55_max", "H2_sol_high"]
            and g[f"e08.judge.{size}.repeats"] == [1, 2, 3]
            and "median of all 3 declared ratings per member" in g[f"e08.judge.{size}.rule"]
            and "mean of the two member medians / 5" in g[f"e08.judge.{size}.rule"],
            f"the {size} FSC is the mean of two judges' medians of three ratings, divided by five",
        )
    require(
        "provider-returned model/effort fields are unavailable"
        in g["e08.judge.identity_evidence"],
        "the judge identity evidence is a request envelope and receipt, not returned fields",
    )
    states(
        "08",
        "FSC came from the `vb103_judge` agent, which requested GPT-6 Sol at high effort and Claude"
        " Opus 5.5 at max effort, with three ratings per judge. FSC is the mean of the two judges'"
        " median ratings divided by five. The judge identities are as requested: the validated"
        " bundle holds the frozen request envelope and a no-fallback receipt, and the"
        " provider-returned model and effort fields are unavailable.",
        "e08 judge state and controls",
    )
    rungs = set(g["e08.validation.trained_checkpoints_per_size"].values())
    require(len(rungs) == 1, "every size has the same number of trained checkpoints")
    states(
        "08",
        f"Selection used {number_word(rungs.pop())} checkpoints (rungs) per size, each evaluated on"
        f" {g['e08.validation.tasks']} validation tasks with"
        f" {number_word(g['e08.validation.samples_per_task'])} samples per task",
        "e08 validation ladder",
    )
    fractions = (g["e08.8B.earliest_passing_fraction"], g["e08.14B.earliest_passing_fraction"])
    states(
        "08",
        f"(8B at {float(fractions[0]):.1f}, 14B at {float(fractions[1]):.1f})",
        "e08 selection",
    )
    unit = g["e08.test.bootstrap"]["unit"]
    require(
        unit.startswith("task")
        and "all 8 samples carried together" in unit
        and all(
            keys[f"e08.test.{label}.scsc_bootstrap95"].endswith("bootstrap95_task/SCSC")
            for label in ("selected_8B", "selected_14B", "base_14B")
        ),
        "experiment 08 intervals are 95% task bootstrap intervals carrying all eight samples",
    )
    states(
        "08",
        "The intervals are 95% task bootstrap intervals. They resample test tasks with their eight"
        " samples",
        "e08 bootstrap unit",
    )

    # Experiment 09.
    require(
        g["e09.status"] == "FAILED_TECHNICAL_GATE" and g["e09.scientific_completion"] is False,
        "experiment 09 failed its technical gate",
    )
    match = re.match(r"(\d+)/(\d+) generated actions outside", g["e09.reason_detail"])
    require(match is not None, "experiment 09 failure detail names the actions outside support")
    states(
        "09",
        f"{match[1]} of {int(match[2]):,} generated actions fell outside the recomputed"  # type: ignore[index]
        " old-policy support",
        "e09 reason_detail",
    )

    # Experiment 19.
    mixed_tasks, validation = g["e19.mixed_tasks"], g["e19.tasks"]
    states(
        "19",
        f"separates the {mixed_tasks} validation tasks with mixed groups from the other"
        f" {validation - mixed_tasks} with an area under the ROC curve (AUC) of"
        f" {g['e19.auc_irt_2pl']:.3f} {interval(g['e19.auc_irt_2pl.ci95'], 3)}, above the"
        f" {g['e19.auc_gate']:.2f} gate",
        "e19 AUC",
    )
    require(g["e19.auc_irt_2pl"] > g["e19.auc_gate"], "the IRT AUC is above the gate")
    require(
        keys["e19.auc_irt_minus_panel_strict_rate"].endswith(
            "q8_irt_2pl_minus_panel_strict_rate/estimate"
        )
        and keys["e19.auc_irt_minus_panel_strict_rate_ci95"].endswith(
            "q8_irt_2pl_minus_panel_strict_rate/ci95"
        ),
        "the contrast is the IRT AUC minus the AUC of ranking by the panel strict pass rate",
    )
    states(
        "19",
        "Its AUC margin over ranking by the panel strict pass rate is"
        f" {g['e19.auc_irt_minus_panel_strict_rate']:+.3f}"
        f" {interval(g['e19.auc_irt_minus_panel_strict_rate_ci95'], 3, sign=True)}",
        "e19 margin over the panel strict pass rate",
    )
    low_bound, high_bound = g["e19.auc_irt_minus_panel_strict_rate_ci95"]
    require(low_bound < 0 < high_bound, "the margin over the panel pass rate spans zero")
    states("19", f"the experiment's own verdict is {g['e19.verdict_g1']}", "e19 verdicts")
    states("19", f"task features alone reach {g['e19.auc_features_only']:.3f}", "e19 features")
    require(g["e19.irt_beats_baselines_strict"] is False, "the second endpoint is not supported")
    states("19", "was not supported", "e19 strict endpoint")
    policy = Path(g["e19.start_policy_path"]).stem.removesuffix("_validation_per_task")
    require(
        "/ladder/" in g["e19.start_policy_path"]
        and g["e19.start_policy_sha256"] == g["e19.start_policy_pinned_sha256"],
        "the forecast reads the pinned experiment 08 validation-ladder file of its policy",
    )
    require(
        policy.startswith("sft_4B_") and g["e08.4B.earliest_passing_fraction"] is None,
        "the forecast policy is a 4B checkpoint, and no 4B checkpoint passed a rung",
    )
    require(
        validation == g["e08.validation.tasks"], "the forecast uses the validation ladder tasks"
    )
    states(
        "19",
        f"one starting policy, `{policy}`, an experiment 08 4B checkpoint that passed no validation"
        f" rung, on {validation} validation tasks with"
        f" {number_word(g['e08.validation.samples_per_task'])} samples each",
        "e19 input pins and e08 ladder",
    )
    systems = len(g["e19.systems"])
    states(
        "19",
        f"The second endpoint uses {g['e19.strict.cells']:,} measured system-task outcomes from {systems}"
        " systems in leave-one-system-out prediction",
        "e19 E1 strict cells and panel systems",
    )
    draws, note = g["e19.bootstrap_note"]
    require(
        "validation task groups" in g["e19.auc_interval_method"]
        and "fitted models held fixed" in note
        and draws == g["e19.bootstrap_draws"]
        and g["e08.split.validation_clusters"] == [validation, g["e19.groups"]],
        "experiment 19 intervals resample validation task clusters with the fitted models fixed",
    )
    states(
        "19",
        f"The 95% intervals resample the {g['e19.groups']} D-013 task clusters that contain the"
        f" {validation} validation tasks and condition on the fitted models",
        "e19 bootstrap",
    )
    states("19", f"are not {systems} independent interventions", "e19 folds")

    # Experiment 25.
    start = g["e25.u0.strict_successes"] / g["e25.u0.cells"]
    require(abs(start - g["e25.u0.pass_at_1"]) < 1e-12, "update-0 pass@1 is successes over cells")
    require(
        g["e25.u0.cells"] == g["e25.tasks"] * g["e25.u0.samples"]
        and g["e25.u48.cells_per_run"] == g["e25.tasks"] * g["e25.u48.samples"],
        "cells are tasks times samples at both updates",
    )
    checkpoint = g["e25.start_checkpoint.seeds_0_1"]
    step = re.fullmatch(r"step_(\d+)_float16", checkpoint)
    require(
        step is not None
        and checkpoint == g["e25.start_checkpoint.seed_2"]
        and int(step[1]) == g["e08.1.7B.max_steps"],  # type: ignore[index]
        "every seed starts from the float16 copy of the experiment 08 1.7B final-step checkpoint",
    )
    folder = re.search(r"/experiments/25_[^/]*?_qwen3_(\d+)p(\d+)b_", text["25"])
    require(folder is not None, "the experiment 25 link names the Qwen3 size of its folder")
    states(
        "25",
        f"on the Qwen3-{folder[1]}.{folder[2]}B Lean fine-tuned model (experiment 08 step"  # type: ignore[index]
        f" {step[1]}), {number_word(3)} seeds per arm",  # type: ignore[index]
        "e25 launch scripts, e08 1.7B config, and experiment folder",
    )
    states(
        "25",
        f"The harness is `{g['e25.trainer_script']}` started from the starting checkpoint"
        f" `{checkpoint}`",
        "e25 lane script and launch scripts",
    )
    states(
        "25",
        f"Strict pass@1 was {100 * g['e25.u0.pass_at_1']:.2f}% at update"
        f" {update_of(keys['e25.u0.pass_at_1'])}.",
        "e25 update-0 record",
    )
    update = update_of(keys["e25.u48.strict.pass_at_1"])
    require(
        {
            update_of(keys[name])
            for name in (
                "e25.u48.cells_per_run",
                "e25.u48.samples",
                "e25.u48.smooth.pass_at_1",
                "e25.u48.smooth_minus_strict",
            )
        }
        == {update},
        "the update-48 figures come from one update",
    )
    states(
        "25",
        f"At update {update}, on {g['e25.tasks']} validation tasks with {g['e25.u48.samples']}"
        f" samples each ({g['e25.u48.cells_per_run']:,} cells per run)",
        "e25 evaluation size",
    )
    strict, smooth = g["e25.u48.strict.pass_at_1"], g["e25.u48.smooth.pass_at_1"]
    states(
        "25",
        f"strict pass@1 is {strict:.2f}% {interval(g['e25.u48.strict.ci95'], 2)} with the strict"
        f" reward and {smooth:.2f}% {interval(g['e25.u48.smooth.ci95'], 2)} with the smooth reward",
        "e25 pooled pass@1",
    )
    states(
        "25",
        f"Smooth minus strict is {g['e25.u48.smooth_minus_strict']:.2f} percentage points"
        f" {interval(g['e25.u48.smooth_minus_strict.ci95'], 2)}",
        "e25 difference",
    )
    paired = g["e25.u48.seed_paired_smooth_minus_strict"]
    states(
        "25",
        f"{paired['s0']:+.1f}, {paired['s1']:+.1f}, and {paired['s2']:+.1f} percentage points",
        "e25 seed-paired differences",
    )
    runs = g["e25.u48.per_run_pass_at_1"]
    seed_numbers = sorted(int(name[1:]) for name in paired)
    require(
        sorted(runs) == sorted(f"{arm}_s{n}" for arm in "AB" for n in seed_numbers),
        "both arms ran the same seeds",
    )
    states(
        "25",
        f"{number_word(len(seed_numbers))} seeds per arm",
        "e25 per-run keys",
    )
    states("25", f"seeds {series([str(n) for n in seed_numbers])} in each arm", "e25 per-run keys")
    states(
        "25",
        f"exact permutation test over the {number_word(len(runs))} run means gives"
        f" p={g['e25.u48.run_level_permutation_p']:.2f}",
        "e25 derived permutation test",
    )
    require(
        g["e25.trainer_dtype.seeds_0_1"] == g["e25.trainer_dtype.seed_2"] == "float16",
        "every seed trained in float16",
    )
    states("25", "with fp16 training and evaluation", "e25 launch scripts")
    states("25", f"evaluation sampler seed {g['e25.eval_sampler_seed']}", "e25 evaluation script")
    states("25", "No DT (differential testing).", "e25 harness")
    states(
        "25",
        "Strict pass@1 measures the local Lean/kernel criterion and does not include formal"
        " specification coverage.",
        "e25 strict criterion",
    )
    require(g["e25.evaluation_reads_vacuity"] is False, "evaluation leaves vacuity at zero")
    states("25", "The evaluation leaves the vacuous-theorem count at zero", "rl4cv scorer reader")
    states("25", "The smooth reward is a [three-factor declaration proxy]", "e25 README")
    states(
        "25",
        f"The update-0 baseline used {number_word(g['e25.u0.samples'])} samples per task, and the"
        f" update-{update} evaluation used {g['e25.u48.samples']}",
        "e25 samples per update",
    )
    level = g["e25.bootstrap_interval_level"]
    require(
        level == 95.0 and "cluster bootstrap" in g["e25.bootstrap_unit"],
        "experiment 25 intervals are 95% cluster bootstrap intervals",
    )
    require(
        g["e25.groups"]
        == g["e25.u48.strict.groups"]
        == g["e25.u48.smooth.groups"]
        == g["e25.u48.smooth_minus_strict.groups"]
        and g["e25.u48.smooth_minus_strict.tasks"] == g["e25.tasks"]
        and g["e08.split.validation_clusters"] == [g["e25.tasks"], g["e25.groups"]],
        "experiment 25 resamples the validation task clusters",
    )
    states(
        "25",
        f"The {level:.0f}% cluster bootstrap intervals resample the {g['e25.groups']} D-013 task"
        f" clusters containing these {g['e25.tasks']} tasks, with the"
        f" {number_word(len(runs))} trained models held fixed",
        "e25 bootstrap",
    )
    require(
        re.search(
            r"Open at the pin: \[a fourth smooth-reward seed is running\]\([^)]*"
            rf"blob/{records['commit']}/experiments/25_[^)]*/full_run_at3558/results\.md#L6\)",
            text["25"],
        )
        is not None,
        "the running fourth seed links its launch record at the pin",
    )

    # Namespace diagnostic.
    stems = g["e08.split.digit_leading_stems"]
    require(
        all(digit == size for digit, size in stems.values()), "whole families start with digits"
    )
    states(
        "namespace",
        f"{sum(d for d, _ in stems.values())} of the {tasks} file stems start with a digit",
        "e08 split manifest",
    )
    states(
        "namespace",
        series([f"all {d} `{family}`" for family, (d, _) in stems.items()]) + " tasks",
        "e08 split manifest",
    )
    require(
        g["e01.qwen3-14b.namespace_rewrite.work_dirs"][-1].endswith("nsfix")
        and g["e01.qwen3-14b.namespace_rewrite.cells"] == g["e01.qwen3-14b.cells"] == tasks,
        "the rewrite summary covers the namespace-rewritten files over all tasks",
    )
    states(
        "namespace",
        f"raised Qwen3-14B from {g['e01.qwen3-14b.compiling_proved_cells']} to"
        f" {g['e01.qwen3-14b.namespace_rewrite.compiling_proved_cells']} of {tasks} cells with"
        " positive IC_tests and IC_proofs",
        "e01 diagnostics",
    )
    require(
        "not guaranteed a pure identifier intervention"
        in g["e01.qwen3-14b.namespace_rewrite.limitation"]
        and g["e01.qwen3-14b.namespace_rewrite.guarded_counterfactual"].startswith(
            "not recompiled"
        ),
        "the rewrite record states its limitation and the unrecompiled counterfactual",
    )
    states(
        "namespace",
        "This count is a diagnostic with the task as its unit. The legacy rewrite was not"
        " guaranteed to change identifiers only, and the guarded counterfactual was not"
        " recompiled.",
        "e01 rewrite audit",
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
