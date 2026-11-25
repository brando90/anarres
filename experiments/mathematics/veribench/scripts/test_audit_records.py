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
        self.assertIn(old, text)
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
            ("128 tasks (4 per split)", "64 tasks (4 per split)"),
            ("Forecast on 135", "Forecast on 99"),
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
