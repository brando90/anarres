import copy
import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import fields, replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
FORMAL_SRC = ROOT / "data/formal-verification/vero/src"
sys.path.insert(0, str(FORMAL_SRC))
CONTRACTS = importlib.import_module("anarres_formal_adapter.contracts")
FIXTURE = importlib.import_module("anarres_formal_adapter.fixture")
VERO = importlib.import_module("anarres_formal_adapter.vero_drivers")
POLICY_REVISION = "sha256:" + "1" * 64


class PortableFormalContractsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / "native"
        self.record = FIXTURE.create_source(self.root)
        self.source = SimpleNamespace(
            source=self.root,
            revision=self.record["content_id"],
            license=self.record["license"],
        )

    def write_record(self, record: dict, *, reseal: bool = True) -> None:
        if reseal:
            record = CONTRACTS.seal(record)
        (self.root / "fixture.json").write_bytes(CONTRACTS.canonical(record) + b"\n")
        self.source.revision = record["content_id"]

    def plan(self, source: SimpleNamespace | None = None) -> dict:
        return FIXTURE.plan(source or self.source, "fixture-policy", POLICY_REVISION, [7, 3])

    def test_fixture_qualification_and_plan_are_deterministic_across_directories(self) -> None:
        qualified = FIXTURE.FixtureSourceDriver().qualify(self.source)
        first = self.plan()
        relocated = Path(self.directory.name) / "relocated"
        record = FIXTURE.create_source(relocated)
        second_source = SimpleNamespace(
            source=relocated, revision=record["content_id"], license=record["license"]
        )
        self.assertEqual(self.record, record)
        self.assertEqual(qualified, FIXTURE.FixtureSourceDriver().qualify(second_source))
        self.assertEqual(first, self.plan())
        self.assertEqual(first, self.plan(second_source))
        self.assertEqual(
            [(attempt["task"]["task_id"], attempt["seed"]) for attempt in first["attempts"]],
            [("a", 7), ("a", 3), ("b", 7), ("b", 3)],
        )
        self.assertEqual([step["order"] for step in first["steps"]], list(range(1, 7)))
        self.assertEqual(first["excluded_partitions"], ["held-out"])
        self.assertFalse(first["execution_available"])
        self.assertEqual(first["gates"]["task_containment"], "unqualified")
        self.assertEqual(first["gates"]["policy_support"], "unmeasured")
        self.assertEqual(first["gates"]["measurement_readiness"], "unqualified")
        self.assertEqual(first["gates"]["downstream_evidence"], "none")
        for value in (qualified, first, *first["attempts"]):
            CONTRACTS.verify_seal(value)
        self.assertNotIn(str(self.root), json.dumps(first))

    def test_fixture_rejects_source_and_task_byte_tampering(self) -> None:
        record = copy.deepcopy(self.record)
        record["repository"] = "tampered"
        self.write_record(record, reseal=False)
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            FIXTURE.FixtureSourceDriver().qualify(self.source)
        self.write_record(self.record)
        (self.root / "development/a.txt").write_bytes(b"tampered\n")
        with self.assertRaisesRegex(ValueError, "artifact identity mismatch"):
            self.plan()

    def test_fixture_rejects_resealed_toolchains_assumptions_and_endpoint_changes(self) -> None:
        mutations = {
            "toolchain": "different-verifier-v2",
            "language": "Lean",
            "trusted_axioms": ["invented_axiom"],
            "unsafe_features": ["unsafe"],
            "admitted_proofs": "allowed",
            "endpoint": "code-and-proof",
        }
        for key, value in mutations.items():
            with self.subTest(field=key):
                record = copy.deepcopy(self.record)
                record[key] = value
                self.write_record(record)
                with self.assertRaises(ValueError):
                    FIXTURE.FixtureSourceDriver().qualify(self.source)

    def test_fixture_rejects_manifest_revision_and_license_changes(self) -> None:
        for key, value in (("revision", POLICY_REVISION), ("license", "MIT")):
            with self.subTest(field=key):
                source = copy.copy(self.source)
                setattr(source, key, value)
                with self.assertRaisesRegex(ValueError, "revision or license mismatch"):
                    FIXTURE.FixtureSourceDriver().qualify(source)

    def test_fixture_rejects_path_escape_and_held_out_aliases_before_reading(self) -> None:
        for path in (
            "../outside.txt",
            "/outside.txt",
            "development/../../outside.txt",
            "development/../held-out/sealed.txt",
            "held-out/sealed.txt",
            "development\\a.txt",
        ):
            with self.subTest(path=path):
                record = copy.deepcopy(self.record)
                record["tasks"][0]["artifact"].update(path=path, uri=path)
                self.write_record(record)
                with self.assertRaises(ValueError):
                    FIXTURE.FixtureSourceDriver().qualify(self.source)

    def test_fixture_rejects_symlinks_to_external_and_held_out_files(self) -> None:
        development = self.root / "development/a.txt"
        targets = [Path(self.directory.name) / "external.txt", self.root / "held-out/sealed.txt"]
        for target in targets:
            with self.subTest(target=target.name):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(FIXTURE.TASK_BYTES)
                development.unlink()
                development.symlink_to(target)
                with self.assertRaisesRegex(ValueError, "symlink"):
                    self.plan()
                development.unlink()
                development.write_bytes(FIXTURE.TASK_BYTES)

    def test_fixture_rejects_symlinked_development_directory(self) -> None:
        development = self.root / "development"
        relocated = self.root / "relocated-development"
        development.rename(relocated)
        development.symlink_to(relocated, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            FIXTURE.FixtureSourceDriver().qualify(self.source)

    def test_fixture_rejects_hard_link_to_held_out_payload_before_reading(self) -> None:
        held_out = self.root / "held-out/sealed.txt"
        held_out.parent.mkdir()
        held_out.write_bytes(FIXTURE.TASK_BYTES)
        development = self.root / "development/a.txt"
        development.unlink()
        os.link(held_out, development)
        original = Path.read_bytes

        def guarded(path):
            if path in (held_out, development):
                raise AssertionError("qualification opened a task alias before rejecting it")
            return original(path)

        with (
            mock.patch.object(Path, "read_bytes", guarded),
            self.assertRaisesRegex(ValueError, "hard link"),
        ):
            self.plan()

    def test_plan_never_opens_held_out_tasks_or_calls_network_processes_or_runner(self) -> None:
        held_out = self.root / "held-out/sealed.txt"
        self.assertFalse(held_out.exists())
        originals = {name: getattr(Path, name) for name in ("open", "stat", "lstat", "resolve")}

        def guarded(name):
            def call(path, *args, **kwargs):
                if "held-out" in path.parts:
                    raise AssertionError(f"planning touched a held-out path via {name}")
                return originals[name](path, *args, **kwargs)

            return call

        with (
            mock.patch.object(Path, "open", guarded("open")),
            mock.patch.object(Path, "stat", guarded("stat")),
            mock.patch.object(Path, "lstat", guarded("lstat")),
            mock.patch.object(Path, "resolve", guarded("resolve")),
            mock.patch("socket.socket", side_effect=AssertionError("network call")),
            mock.patch("socket.create_connection", side_effect=AssertionError("network call")),
            mock.patch("subprocess.Popen", side_effect=AssertionError("process call")),
            mock.patch.object(
                FIXTURE.FixtureRunner, "run", side_effect=AssertionError("runner call")
            ),
        ):
            plan = self.plan()
        self.assertEqual(plan["provider_calls"], 0)
        self.assertFalse(plan["held_out_tasks_opened"])
        self.assertFalse(held_out.exists())

    def test_fixture_plan_requires_immutable_policy_and_unique_nonnegative_seeds(self) -> None:
        for revision, seeds in (
            ("latest", [0]),
            (POLICY_REVISION, []),
            (POLICY_REVISION, [0, 0]),
            (POLICY_REVISION, [-1]),
            (POLICY_REVISION, [True]),
        ):
            with self.subTest(revision=revision, seeds=seeds), self.assertRaises(ValueError):
                FIXTURE.plan(self.source, "fixture-policy", revision, seeds)

    def test_fixture_runner_round_trip_uses_stdin_and_preserves_artifact_identity(self) -> None:
        request = self.plan()["attempts"][0]
        env = {**os.environ, "PYTHONPATH": str(FORMAL_SRC)}
        command = [
            sys.executable,
            "-c",
            "from anarres_formal_adapter.fixture import runner_main; runner_main()",
        ]
        first = subprocess.run(
            command,
            input=json.dumps(request),
            capture_output=True,
            text=True,
            check=False,
            cwd=self.directory.name,
            env=env,
        )
        self.assertEqual(first.returncode, 0, first.stderr)
        second = subprocess.run(
            command,
            input=json.dumps(request),
            capture_output=True,
            text=True,
            check=False,
            cwd=self.directory.name,
            env=env,
        )
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(first.stdout, second.stdout)
        reply = json.loads(first.stdout)
        CONTRACTS.verify_seal(reply)
        self.assertEqual(
            reply["schema_version"],
            FIXTURE.FixtureRunner().descriptor()["contract"]["response_schema"],
        )
        attempt = reply["attempt"]
        CONTRACTS.verify_seal(attempt)
        self.assertEqual(attempt["request_id"], request["content_id"])
        self.assertEqual(attempt["seed"], 7)
        self.assertEqual(attempt["outcome"], "strict-success")
        self.assertEqual(attempt["cost"], {"model_tokens": 0, "wall_seconds": None})
        self.assertEqual(attempt["artifacts"][0]["sha256"], CONTRACTS.digest(b"true\n"))
        self.assertEqual(reply["outputs"], {"proof.txt": "true\n"})
        self.assertFalse((Path(self.directory.name) / "proof.txt").exists())
        request["seed"] = 9
        rejected = subprocess.run(
            command,
            input=json.dumps(request),
            capture_output=True,
            text=True,
            check=False,
            cwd=self.directory.name,
            env=env,
        )
        self.assertEqual(rejected.returncode, 1)
        self.assertEqual(rejected.stdout, "")
        self.assertIn("content identity mismatch", rejected.stderr)

    def test_external_runner_rejects_malformed_input_without_attempt_receipts(self) -> None:
        request = self.plan()["attempts"][0]
        invalid_values = [
            None,
            [],
            42,
            CONTRACTS.seal({**request, "task": None}),
            CONTRACTS.seal({**request, "task": {**request["task"], "artifact": None}}),
        ]
        for value in invalid_values:
            with self.subTest(value=value):
                completed = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        "from anarres_formal_adapter.fixture import runner_main; runner_main()",
                    ],
                    input=json.dumps(value),
                    capture_output=True,
                    text=True,
                    check=False,
                    cwd=self.directory.name,
                    env={**os.environ, "PYTHONPATH": str(FORMAL_SRC)},
                )
                self.assertEqual(completed.returncode, 1)
                self.assertEqual(completed.stdout, "")
                self.assertTrue(completed.stderr.startswith("error:"), completed.stderr)
                self.assertNotIn("Traceback", completed.stderr)

    def test_runner_refuses_held_out_network_tools_and_identity_tampering(self) -> None:
        request = self.plan()["attempts"][0]
        mutations = (
            ("task", {**request["task"], "partition": "held-out"}),
            ("tool_policy", {"network": True, "tools": []}),
            ("tool_policy", {"network": False, "tools": ["shell"]}),
            ("limits", {"wall_seconds": 10, "model_tokens": 1}),
            ("limits", {"wall_seconds": 0, "model_tokens": 0}),
            ("seed", -1),
            ("output_artifacts", ["../proof.txt"]),
            ("runner", CONTRACTS.seal({**request["runner"], "name": "different-runner"})),
            ("runtime", CONTRACTS.seal({**request["runtime"], "status": "unqualified"})),
            ("source_driver", CONTRACTS.seal({**request["source_driver"], "version": "2"})),
        )
        for key, value in mutations:
            with self.subTest(key=key, value=value):
                changed = CONTRACTS.seal({**request, key: value})
                with self.assertRaises(ValueError):
                    FIXTURE.FixtureRunner().run(changed)

    def test_runner_rejects_tampered_task_harness_and_partial_requests(self) -> None:
        request = self.plan()["attempts"][0]
        artifact = request["task"]["artifact"]
        task_changes = [
            {"task_id": "../escape"},
            {"task_id": "different-task"},
            {"artifact": {**artifact, "sha256": POLICY_REVISION}},
            {"artifact": {**artifact, "path": "held-out/sealed.txt", "uri": "held-out/sealed.txt"}},
            {"artifact": {**artifact, "size_bytes": 0}},
            {"artifact": {**artifact, "license": "MIT"}},
            {"dependencies": ["another-task"]},
            {"context": ["hidden-context"]},
            {"allowed_reference_material": ["reference-proof"]},
        ]
        for change in task_changes:
            with self.subTest(task_change=change):
                changed = CONTRACTS.seal({**request, "task": {**request["task"], **change}})
                with self.assertRaises(ValueError):
                    FIXTURE.FixtureRunner().run(changed)
        for field, value in (("identity", "different-harness"), ("revision", POLICY_REVISION)):
            with self.subTest(harness_field=field):
                changed = CONTRACTS.seal(
                    {**request, "harness": {**request["harness"], field: value}}
                )
                with self.assertRaisesRegex(ValueError, "harness identity"):
                    FIXTURE.FixtureRunner().run(changed)
        for omitted in ("source", "task", "seed", "runtime", "limits", "output_artifacts"):
            with self.subTest(omitted=omitted):
                changed = CONTRACTS.seal(
                    {key: value for key, value in request.items() if key != omitted}
                )
                with self.assertRaisesRegex(ValueError, "unsupported runner request"):
                    FIXTURE.FixtureRunner().run(changed)

    def test_generic_request_rejects_invalid_resource_tool_and_output_contracts(self) -> None:
        request = self.plan()["attempts"][0]
        CONTRACTS.validate_run_request(request)
        mutations = (
            ("limits", {"wall_seconds": True, "model_tokens": 0}),
            ("limits", {"wall_seconds": -1, "model_tokens": 0}),
            ("limits", {"wall_seconds": 10, "model_tokens": True}),
            ("limits", {"wall_seconds": 10, "model_tokens": -1}),
            ("limits", {"wall_seconds": 10, "model_tokens": 0, "extra": 1}),
            ("tool_policy", {"network": 1, "tools": []}),
            ("tool_policy", {"network": False, "tools": "shell"}),
            ("tool_policy", {"network": False, "tools": [""]}),
            ("tool_policy", {"network": False, "tools": [], "extra": False}),
            ("output_artifacts", []),
            ("output_artifacts", ["proof.txt", "proof.txt"]),
            ("output_artifacts", ["../proof.txt"]),
            ("output_artifacts", ["/proof.txt"]),
            ("output_artifacts", ["file://proof.txt"]),
        )
        for key, value in mutations:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                CONTRACTS.validate_run_request(CONTRACTS.seal({**request, key: value}))

    def test_failure_outcomes_do_not_become_strict_proof_failure(self) -> None:
        request = self.plan()["attempts"][0]
        for outcome in CONTRACTS.OUTCOMES:
            with self.subTest(outcome=outcome):
                attempt = CONTRACTS.attempt_record(request, outcome, artifacts=[])
                CONTRACTS.verify_seal(attempt)
                self.assertEqual(attempt["outcome"], outcome)
                self.assertEqual(attempt["strict_success"], outcome == "strict-success")
                self.assertEqual(attempt["proof_failure"], outcome == "strict-proof-failure")
                self.assertNotIn("reward", attempt)
                self.assertIsNone(attempt["cost"]["wall_seconds"])
                self.assertIsNone(attempt["cost"]["model_tokens"])
        verifier = FIXTURE.FixtureVerifierDriver()
        self.assertEqual(verifier.verify(b"true\n"), "strict-success")
        self.assertEqual(verifier.verify(b"false\n"), "strict-proof-failure")
        self.assertEqual(verifier.verify(b"malformed"), "parser-failure")
        with self.assertRaisesRegex(ValueError, "unsupported attempt outcome"):
            CONTRACTS.attempt_record(request, "failure", artifacts=[])

    def test_attempt_costs_preserve_measured_values_and_reject_invalid_costs(self) -> None:
        request = self.plan()["attempts"][0]
        record = CONTRACTS.attempt_record(
            request, "timeout", artifacts=[], model_tokens=11, wall_seconds=2.5
        )
        self.assertEqual(record["cost"], {"model_tokens": 11, "wall_seconds": 2.5})
        self.assertFalse(record["proof_failure"])
        for arguments in (
            {"model_tokens": -1},
            {"model_tokens": True},
            {"wall_seconds": -1},
            {"wall_seconds": True},
            {"wall_seconds": float("nan")},
            {"wall_seconds": float("inf")},
        ):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                CONTRACTS.attempt_record(request, "timeout", artifacts=[], **arguments)

    def test_attempt_record_requires_a_complete_valid_request(self) -> None:
        request = self.plan()["attempts"][0]
        missing_source = {key: value for key, value in request.items() if key != "source"}
        invalid_requests = [
            CONTRACTS.seal(missing_source),
            CONTRACTS.seal({**request, "source": "mutable-source"}),
            CONTRACTS.seal({**request, "task": None}),
        ]
        for invalid in invalid_requests:
            with self.subTest(request=invalid), self.assertRaises(ValueError):
                CONTRACTS.attempt_record(invalid, "strict-success", artifacts=[])

    def test_candidate_contract_rejects_each_incompatible_identity(self) -> None:
        candidate = CONTRACTS.CandidateContract(
            language="fixture",
            toolchain=FIXTURE.TOOLCHAIN,
            endpoint="proof-only",
            policy="fixture-policy",
            policy_revision=POLICY_REVISION,
            target="sha256:" + "2" * 64,
            verifier="sha256:" + "3" * 64,
            unit="task",
            measurement="sha256:" + "4" * 64,
            assumptions="sha256:" + "5" * 64,
        )
        CONTRACTS.require_compatible([candidate, replace(candidate)])
        self.assertEqual(candidate.record(), replace(candidate).record())
        for field in fields(candidate):
            value = getattr(candidate, field.name)
            changed = "sha256:" + "9" * 64 if value.startswith("sha256:") else value + "-different"
            if field.name == "endpoint":
                changed = "code-and-proof"
            with self.subTest(field=field.name), self.assertRaisesRegex(ValueError, field.name):
                CONTRACTS.require_compatible(
                    [candidate, replace(candidate, **{field.name: changed})]
                )
        for endpoint in ("specification-construction", "specification-faithfulness"):
            with self.subTest(endpoint=endpoint), self.assertRaisesRegex(ValueError, "endpoint"):
                CONTRACTS.require_compatible([candidate, replace(candidate, endpoint=endpoint)])
        with self.assertRaisesRegex(ValueError, "at least two"):
            CONTRACTS.require_compatible([candidate])

    def test_driver_descriptors_are_separately_versioned_and_bind_implementation_bytes(
        self,
    ) -> None:
        identities = set()
        for driver, kind in (
            (FIXTURE.FixtureSourceDriver(), "source-driver"),
            (FIXTURE.FixtureVerifierDriver(), "verifier-driver"),
            (FIXTURE.FixtureRunner(), "prover-runner"),
            (VERO.VeroSourceDriver(), "source-driver"),
            (VERO.VeroVerifierDriver(), "verifier-driver"),
        ):
            with self.subTest(driver=type(driver).__name__):
                descriptor = driver.descriptor()
                CONTRACTS.verify_seal(descriptor)
                self.assertEqual(descriptor["schema_version"], f"anarres.formal-{kind}.v1")
                self.assertEqual(descriptor["version"], "1")
                for module, identity in descriptor["implementation"].items():
                    package_root = FORMAL_SRC / descriptor["package"]
                    if module == "anarres_formal_adapter/contracts.py":
                        package_root = FORMAL_SRC
                    payload = (package_root / module).read_bytes()
                    self.assertEqual(identity, CONTRACTS.digest(payload))
                self.assertNotIn(descriptor["content_id"], identities)
                identities.add(descriptor["content_id"])
                descriptor["implementation"]["anarres_formal_adapter/contracts.py"] = (
                    POLICY_REVISION
                )
                with self.assertRaisesRegex(ValueError, "identity mismatch"):
                    CONTRACTS.verify_seal(descriptor)

    def test_vero_drivers_delegate_without_rewriting_released_reports(self) -> None:
        pin = VERO.source_qualification.load_source_pin()
        source = SimpleNamespace(
            source=self.root, revision=f"git:{pin['commit']}", license=pin["license"]
        )
        source_report = {"status": "qualified", "native_field": "preserved"}
        runtime_report = {"status": "runtime-qualified", "task_containment": "unqualified"}
        inputs = {
            "contract_path": self.root / "runtime.json",
            "source": self.root,
            "source_report": source_report,
            "source_revision": source.revision,
            "lean_executable": self.root / "lean",
            "lake_executable": self.root / "lake",
        }
        with mock.patch.object(
            VERO.source_qualification, "qualify", return_value=source_report
        ) as run:
            self.assertIs(VERO.VeroSourceDriver().qualify(source), source_report)
            run.assert_called_once_with(self.root)
        with mock.patch.object(
            VERO.runtime_qualification, "qualify", return_value=runtime_report
        ) as run:
            self.assertIs(VERO.VeroVerifierDriver().preflight(**inputs), runtime_report)
            run.assert_called_once_with(**inputs)
        self.assertFalse(VERO.VeroSourceDriver().descriptor()["contract"]["policy_probe"])
        for key, value in (("revision", POLICY_REVISION), ("license", "MIT")):
            with self.subTest(field=key):
                invalid = copy.copy(source)
                setattr(invalid, key, value)
                with (
                    mock.patch.object(VERO.source_qualification, "qualify") as run,
                    self.assertRaises(ValueError),
                ):
                    VERO.VeroSourceDriver().qualify(invalid)
                run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
