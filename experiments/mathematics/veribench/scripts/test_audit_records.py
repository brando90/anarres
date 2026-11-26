"""Negative tests for audit_records.py: each change to the page or the records must fail it.

Run from this directory: python3 -m unittest discover -p test_audit_records.py
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import audit_records

ROOT = Path(__file__).resolve().parents[1]


def quiet(function, *arguments):
    with contextlib.redirect_stdout(io.StringIO()):
        return function(*arguments)


class AuditFailsOnChangedInput(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = Path(tempfile.mkdtemp())
        (self.directory / "results").mkdir()
        shutil.copy(ROOT / "README.md", self.directory / "README.md")
        shutil.copy(ROOT / "results" / "records.json", self.directory / "results" / "records.json")
        self.addCleanup(shutil.rmtree, self.directory)

    def edit_readme(self, old: str, new: str) -> None:
        path = self.directory / "README.md"
        text = path.read_text()
        self.assertTrue(old in text, f"{old!r} is not in the README")
        path.write_text(text.replace(old, new, 1))

    def edit_records(self, change) -> None:
        path = self.directory / "results" / "records.json"
        records = json.loads(path.read_text())
        change(records)
        path.write_text(json.dumps(records))

    def assert_fails(self) -> None:
        with self.assertRaises(AssertionError):
            quiet(audit_records.run, self.directory)

    def test_unchanged_copy_passes(self) -> None:
        quiet(audit_records.run, self.directory)

    def test_prose_integers_are_checked(self) -> None:
        for old, new in (
            ("at step 658", "at step 659"),
            ("On 222 held-out", "On 223 held-out"),
            ("All 21,504 cells", "All 20,000 cells"),
            ("all 896 tasks", "all 500 tasks"),
            ("128 tasks (up to 4", "64 tasks (up to 4"),
            ("on 135 validation tasks with eight", "on 99 validation tasks with eight"),
            ("at update 0", "at update 1"),
            ("(4,320 cells per run)", "(2,000 cells per run)"),
            ("152-task core", "150-task core"),
            ("gives PARTIAL", "gives PASS"),
            ("p=0.50", "p=0.04"),
        ):
            with self.subTest(change=old):
                self.setUp()
                self.edit_readme(old, new)
                self.assert_fails()

    def test_figures_are_tied_to_their_model_and_update(self) -> None:
        """The three counterexamples of the 11-25-2026 review, each of which the earlier
        README-wide search accepted."""
        selected_8b = "0.1116 [0.0823, 0.1435] for the selected 8B model"
        selected_14b = "0.0869 [0.0651, 0.1095] for the selected 14B model"
        for name, changes in (
            ("Base 8B score", [("against 0.0000 for Base 8B", "against 0.7777 for Base 8B")]),
            (
                "selected pairs swapped",
                [
                    (selected_8b, "PLACEHOLDER"),
                    (selected_14b, selected_14b.replace("14B", "8B")),
                    ("PLACEHOLDER", selected_8b.replace("8B", "14B")),
                ],
            ),
            ("update number", [("At update 48", "At update 49")]),
        ):
            with self.subTest(change=name):
                self.setUp()
                for old, new in changes:
                    self.edit_readme(old, new)
                self.assert_fails()

    def test_new_claims_are_checked(self) -> None:
        commit = json.loads((ROOT / "results" / "records.json").read_text())["commit"]
        for old, new in (
            # Item 2: test exposure and the row 08 evaluation statement.
            ("evaluated all 896 tasks before D-013", "evaluated all 895 tasks before D-013"),
            ("once on its 222 test tasks", "once on its 221 test tasks"),
            (" Historical baseline and teacher outcomes on those tasks had already been", " The"),
            ("was evaluated once after selection.", "was evaluated twice after selection."),
            # Item 3: namespace counts.
            ("from 1 to 25 of 896", "from 1 to 24 of 896"),
            ("533 of the 896 file stems", "532 of the 896 file stems"),
            ("all 460 `security_set`", "all 459 `security_set`"),
            ("guarded counterfactual was not recompiled", "guarded counterfactual was recompiled"),
            # Item 4: outcome definitions and the experiment 25 harness.
            (", with FSC counted as 0 when IC_tests is 0", ""),
            (", and the recorded vacuous-theorem count is zero", ""),
            ("were kernel-scored", "were scored"),
            ("No DT (differential testing). ", ""),
            ("does not include formal specification coverage", "includes coverage"),
            ("leaves the vacuous-theorem count at zero", "checks vacuous theorems"),
            ("with fp16 training and evaluation", "with bf16 training and evaluation"),
            # Item 5: the resampling unit.
            (
                "resample the 100 D-013 task clusters containing",
                "resample the 99 D-013 task clusters containing",
            ),
            ("and condition on the fitted models", "and refit the models"),
            # Item 6: the forecast policy and the second endpoint.
            ("`sft_4B_f1p0`", "`sft_8B_f1p0`"),
            ("1,308 measured system-task outcomes", "1,309 measured system-task outcomes"),
            ("from 11 systems", "from 12 systems"),
            # Item 7: probe tasks per benchmark family.
            ("(up to 4 per benchmark family)", "(4 per split)"),
            ("31 families hold 4", "32 families hold 4"),
            # Item 8: interval, seed, and sample labels.
            ("95% Wilson intervals", "90% Wilson intervals"),
            ("95% task bootstrap intervals", "95% cluster bootstrap intervals"),
            ("training seed 20260830", "training seed 20260831"),
            ("five checkpoints (rungs) per size", "four checkpoints (rungs) per size"),
            ("seeds 0, 1, and 2 in each arm", "seeds 0, 1, and 3 in each arm"),
            ("sampler seed 91", "sampler seed 92"),
            ("baseline used eight samples per task", "baseline used 32 samples per task"),
            ("-16.25 percentage points", "-16.25 points"),
            ("area under the ROC curve (AUC)", "AUC"),
            # Item 9: release pins and the Harbor candidate.
            ("VeriBench commit `c11b99ba`", "VeriBench commit `c9dfd8e3`"),
            ("candidate at commit `c9dfd8e3b535`", "candidate at commit `c11b99badfa3`"),
            ("label this task set `veribench@1.3`", "label this task set `veribench@1.2`"),
            # Item 10: the running fourth seed.
            ("full_run_at3558/results.md#L6", "full_run_at3558/results.md#L3"),
            ("Open at the pin: [a fourth", "[A fourth"),
            # A correct statement moved into another experiment's row.
            ("8B first passes at step 658 and 14B at step 334. ", ""),
            (f"blob/{commit}/docs/FACTS", "blob/main/docs/FACTS"),
        ):
            with self.subTest(change=old):
                self.setUp()
                self.edit_readme(old, new)
                self.assert_fails()

    def test_model_checkpoint_harness_and_definitions_are_tied(self) -> None:
        """The counterexamples of the 11-26-2026 review, each of which the earlier audit accepted,
        and the statements added with the fixes."""
        for old, new in (
            ("(experiment 08 step 658)", "(experiment 08 step 659)"),
            ("on the Qwen3-1.7B Lean", "on the Qwen3-8B Lean"),
            ("The harness is `train_e25.py`", "The harness is `train_other.py`"),
            ("starting checkpoint `step_658_float16`", "starting checkpoint `step_659_float16`"),
            (
                "strict success as the `kernel_binary` value",
                "strict success as the `proof_fraction` value",
            ),
            ("IC_proofs both equal 1", "IC_proofs both equal 0"),
            (
                "Its AUC margin over ranking by the panel strict pass rate",
                "Its AUC margin over the features-only predictor",
            ),
            (
                "`propext`, `Classical.choice`, and `Quot.sound`",
                "`propext` and `Classical.choice`",
            ),
            (
                "and the recorded vacuous-theorem count is zero",
                "and has no vacuous theorem",
            ),
            ("so it stays zero there, and experiment 08 fills it", "so it is filled there, and experiment 08 fills it"),
            ("at revision `c751f811`", "at revision `c751f812`"),
            ("thinking on and sampler seed 91", "thinking off and sampler seed 91"),
            ("GPT-6 Sol at high effort", "GPT-6 Sol at max effort"),
            ("with three ratings per judge", "with five ratings per judge"),
            ("median ratings divided by five", "median ratings divided by four"),
            ("and a no-fallback receipt", "and returned model fields"),
        ):
            with self.subTest(change=old):
                self.setUp()
                self.edit_readme(old, new)
                self.assert_fails()

    def test_changed_definition_record_is_checked(self) -> None:
        for figure_id, value in (
            ("e25.strict_function", "reward_proof_fraction"),
            ("e19.strict_rule", "ict == 0.0 and icp == 0.0"),
            ("e25.trainer_script", "train_other.py"),
            ("e25.start_checkpoint.seed_2", "step_659_float16"),
            ("kernel_binary.allowed_axioms", ["propext"]),
        ):
            with self.subTest(figure=figure_id):
                self.setUp()

                def change(records: dict, name=figure_id, new=value) -> None:
                    for figure in records["figures"]:
                        if figure["id"] == name:
                            figure["value"] = new

                self.edit_records(change)
                self.assert_fails()

    def test_statement_in_another_row_is_rejected(self) -> None:
        moved = "Strict pass@1 was 4.26% at update 0. "
        self.edit_readme(moved, "")
        self.edit_readme(
            "The 1.7B and 4B models pass no rung.", moved + "The 1.7B and 4B models pass no rung."
        )
        self.assert_fails()

    def test_manifest_digest_is_checked(self) -> None:
        def change(records: dict) -> None:
            for item in records["files"]:
                if item["path"].endswith("vbv1_split_manifest.csv"):
                    item["sha256"] = "1" * 64

        self.edit_records(change)
        self.assert_fails()

    def test_pin_in_a_link_is_checked(self) -> None:
        commit = json.loads((ROOT / "results" / "records.json").read_text())["commit"]
        self.edit_readme(f"blob/{commit}/experiments/25_", "blob/main/experiments/25_")
        self.assert_fails()

    def test_missing_artifact_fields_are_checked(self) -> None:
        for field in ("media_type", "size", "license", "producing_run"):
            with self.subTest(field=field):
                self.setUp()
                self.edit_records(lambda records, name=field: records["files"][0].pop(name))
                self.assert_fails()

    def test_zero_digest_is_checked(self) -> None:
        self.edit_records(lambda records: records["files"][0].update(sha256="0" * 64))
        self.assert_fails()

    def test_missing_figure_is_checked(self) -> None:
        self.edit_records(
            lambda records: records["figures"].remove(
                next(f for f in records["figures"] if f["id"] == "e19.auc_features_only")
            )
        )
        with self.assertRaises(KeyError):
            quiet(audit_records.run, self.directory)

    def test_changed_figure_is_checked(self) -> None:
        def change(records: dict) -> None:
            for figure in records["figures"]:
                if figure["id"] == "e08.8B.first_passing_step":
                    figure["value"] = 659

        self.edit_records(change)
        self.assert_fails()


class DigestVerification(unittest.TestCase):
    def test_recomputed_digest_must_match_the_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            payload = b'{"a": 1}\n'
            (repository / "a.json").write_bytes(payload)
            for command in (
                ["git", "init", "-q"],
                ["git", "add", "a.json"],
                ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x"],
            ):
                subprocess.run(command, cwd=repository, check=True)
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repository,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            item = {
                "path": "a.json",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size": len(payload),
            }
            records = {"commit": commit, "files": [item]}
            quiet(audit_records.verify_digests, records, repository)
            for change in ({"sha256": "1" * 64}, {"size": len(payload) + 1}):
                with self.subTest(change=change):
                    altered = {"commit": commit, "files": [{**item, **change}]}
                    with self.assertRaises(AssertionError):
                        quiet(audit_records.verify_digests, altered, repository)


if __name__ == "__main__":
    unittest.main()
