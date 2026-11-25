"""A synthetic source and external runner for model-free contract conformance."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from anarres_formal_adapter.contracts import (
    OUTCOMES,
    attempt_record,
    canonical,
    contained_file,
    digest,
    driver_identity,
    relative_path,
    require_digest,
    require_revision,
    seal,
    validate_run_request,
    verify_seal,
)

FORMAT = "formal-fixture-v1"
TOOLCHAIN = "anarres-fixture-equality-v1"
TASK_BYTES = b"prove literal true\n"
PROOF_BYTES = b"true\n"
LICENSE = "Apache-2.0"
PRODUCING_RUN = "fixture-generator-v1"


def artifact(path: str, payload: bytes, run: str) -> dict[str, Any]:
    return {
        "path": path,
        "uri": path,
        "sha256": digest(payload),
        "size_bytes": len(payload),
        "media_type": "text/plain",
        "license": LICENSE,
        "producing_run": run,
    }


def create_source(root: Path) -> dict[str, Any]:
    """Write native fixture data; never create or open the held-out task."""
    root.mkdir(parents=True, exist_ok=False)
    (root / "development").mkdir()
    tasks = []
    for name, partition in (("a", "development"), ("b", "development"), ("sealed", "held-out")):
        path = f"{partition}/{name}.txt"
        if partition == "development":
            (root / path).write_bytes(TASK_BYTES)
        tasks.append(
            {
                "task_id": name,
                "partition": partition,
                "artifact": artifact(path, TASK_BYTES, PRODUCING_RUN),
                "groups": {
                    "theorem": name,
                    "specification": name,
                    "function": None,
                    "module": "literal",
                    "repository": "synthetic-fixture",
                    "generation_family": "literal-true-v1",
                },
                "dependencies": [],
                "context": [],
                "allowed_reference_material": [],
            }
        )
    record = seal(
        {
            "schema_version": "anarres.formal-fixture-source.v1",
            "repository": "synthetic-fixture",
            "task_set": "literal-true-v1",
            "license": LICENSE,
            "language": "fixture",
            "toolchain": TOOLCHAIN,
            "endpoint": "proof-only",
            "trusted_axioms": [],
            "unsafe_features": [],
            "admitted_proofs": "forbidden",
            "tasks": tasks,
        }
    )
    (root / "fixture.json").write_bytes(canonical(record) + b"\n")
    return record


class FixtureSourceDriver:
    def descriptor(self) -> dict[str, Any]:
        return driver_identity(
            "source-driver",
            FORMAT,
            ("fixture.py",),
            language="fixture",
            toolchain=TOOLCHAIN,
            endpoints=["proof-only"],
            source_qualification=True,
            policy_probe=False,
            decision=False,
            fixture_only=True,
        )

    def qualify(self, source: Any) -> dict[str, Any]:
        record = json.loads(contained_file(source.source, "fixture.json").read_bytes())
        verify_seal(record)
        if source.revision != record["content_id"] or source.license != record["license"]:
            raise ValueError("fixture source revision or license mismatch")
        required = {
            "schema_version",
            "repository",
            "task_set",
            "license",
            "language",
            "toolchain",
            "endpoint",
            "trusted_axioms",
            "unsafe_features",
            "admitted_proofs",
            "tasks",
            "content_id",
        }
        if set(record) != required:
            raise ValueError("fixture source has unknown or missing fields")
        if record["schema_version"] != "anarres.formal-fixture-source.v1":
            raise ValueError("unsupported fixture source schema")
        if record["language"] != "fixture" or record["toolchain"] != TOOLCHAIN:
            raise ValueError("wrong fixture toolchain")
        if record["endpoint"] != "proof-only":
            raise ValueError("unsupported fixture endpoint")
        if record["trusted_axioms"] != [] or record["unsafe_features"] != []:
            raise ValueError("fixture forbids axioms and unsafe features")
        if record["admitted_proofs"] != "forbidden":
            raise ValueError("fixture forbids admitted proofs")
        if any(
            not isinstance(record[key], str) or not record[key]
            for key in ("repository", "task_set")
        ):
            raise ValueError("fixture source lacks lineage")
        tasks = record["tasks"]
        if not isinstance(tasks, list) or not tasks:
            raise ValueError("fixture source requires tasks")
        task_ids: set[str] = set()
        paths: set[str] = set()
        development = []
        for task in tasks:
            if set(task) != {
                "task_id",
                "partition",
                "artifact",
                "groups",
                "dependencies",
                "context",
                "allowed_reference_material",
            }:
                raise ValueError("fixture task has unknown or missing fields")
            task_id = task["task_id"]
            relative_path(task_id)
            if "/" in task_id or task_id in task_ids:
                raise ValueError("invalid or duplicate task identity")
            task_ids.add(task_id)
            partition = task["partition"]
            if partition not in {"development", "held-out"}:
                raise ValueError("unsupported fixture partition")
            item = task["artifact"]
            if set(item) != {
                "path",
                "uri",
                "sha256",
                "size_bytes",
                "media_type",
                "license",
                "producing_run",
            }:
                raise ValueError("artifact metadata missing or unknown")
            path = relative_path(item["path"])
            if path.parts[0] != partition or str(path) in paths:
                raise ValueError("artifact partition mismatch or duplicate path")
            paths.add(str(path))
            require_digest(item["sha256"])
            if (
                item["uri"] != item["path"]
                or type(item["size_bytes"]) is not int
                or item["size_bytes"] < 0
                or item["media_type"] != "text/plain"
                or item["license"] != record["license"]
                or not item["producing_run"]
            ):
                raise ValueError("invalid artifact identity")
            if task["dependencies"] or task["context"] or task["allowed_reference_material"]:
                raise ValueError("fixture permits no dependencies, context, or reference material")
            if (
                set(task["groups"])
                != {
                    "theorem",
                    "specification",
                    "function",
                    "module",
                    "repository",
                    "generation_family",
                }
                or task["groups"]["repository"] != record["repository"]
                or any(
                    not isinstance(task["groups"][key], str) or not task["groups"][key]
                    for key in ("repository", "generation_family")
                )
            ):
                raise ValueError("fixture grouping keys are incomplete")
            # Metadata is enough for excluded tasks. Do not stat, resolve, or read them.
            if partition == "held-out":
                continue
            # Qualify only metadata that the fixture runner accepts, so no plan names an
            # attempt the runner would reject.
            if item["path"] != f"development/{task_id}.txt":
                raise ValueError("fixture runner requires development/<task_id>.txt artifacts")
            if item["producing_run"] != PRODUCING_RUN:
                raise ValueError(f"fixture runner requires producing run {PRODUCING_RUN}")
            if item["license"] != LICENSE:
                raise ValueError(f"fixture runner requires license {LICENSE}")
            payload = contained_file(source.source, item["path"]).read_bytes()
            if digest(payload) != item["sha256"] or len(payload) != item["size_bytes"]:
                raise ValueError("task artifact identity mismatch")
            if payload != TASK_BYTES:
                raise ValueError("unsupported fixture task syntax")
            development.append(task)
        if not development:
            raise ValueError("fixture has no development tasks")
        return seal(
            {
                "schema_version": "anarres.formal-source-qualification.v1",
                "status": "qualified",
                "source": record,
                "source_driver": self.descriptor(),
                "development_tasks": sorted(development, key=lambda task: task["task_id"]),
                "gates": {
                    "source_qualification": "qualified",
                    "runtime_qualification": "pending",
                    "task_containment": "unqualified",
                    "policy_support": "unmeasured",
                    "measurement_readiness": "unqualified",
                    "downstream_evidence": "none",
                },
                "held_out_tasks_opened": False,
                "model_execution_started": False,
            }
        )


class FixtureVerifierDriver:
    def descriptor(self) -> dict[str, Any]:
        return driver_identity(
            "verifier-driver",
            TOOLCHAIN,
            # fixture_cli.py implements the advertised native command.
            ("fixture.py", "fixture_cli.py"),
            language="fixture",
            toolchain=TOOLCHAIN,
            endpoints=["proof-only"],
            strict_success="exact bytes true followed by newline",
            outcomes=list(OUTCOMES),
            trusted_axioms=[],
            admitted_proofs="forbidden",
            unsafe_features=[],
            native_command=["anarres-formal-fixture", "verify-fixture"],
        )

    def preflight(self, **inputs: Any) -> dict[str, Any]:
        if inputs:
            raise ValueError("fixture runtime accepts no external configuration")
        return seal(
            {
                "schema_version": "anarres.formal-fixture-runtime.v1",
                "verifier_driver": self.descriptor(),
                "status": "qualified",
                "scope": "in-process deterministic fixture only",
                "task_containment": "unqualified",
                "network": False,
                "accelerator": False,
                "proof_assistant": False,
                "model_execution_started": False,
            }
        )

    def verify(self, proof: bytes) -> str:
        if proof == PROOF_BYTES:
            return "strict-success"
        # Blank output is not a proof, so it cannot count as a strict proof failure.
        if proof == b"false\n":
            return "strict-proof-failure"
        return "parser-failure"


class FixtureRunner:
    def descriptor(self) -> dict[str, Any]:
        return driver_identity(
            "prover-runner",
            "literal-fixture-runner-v1",
            ("fixture.py",),
            command=["formal-fixture-runner"],
            request_schema="anarres.formal-run-request.v1",
            response_schema="anarres.formal-run-response.v1",
            transport="one JSON object on stdin; one JSON object on stdout",
            fixture_only=True,
            network=False,
            model=False,
        )

    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        validate_request(request)
        verifier = FixtureVerifierDriver()
        if request["runner"] != self.descriptor() or request["runtime"] != verifier.preflight():
            raise ValueError("runner or runtime identity mismatch")
        if request["source_driver"] != FixtureSourceDriver().descriptor():
            raise ValueError("source driver identity mismatch")
        if request["harness"] != {
            "identity": request["runner"]["name"],
            "revision": request["runner"]["content_id"],
        }:
            raise ValueError("harness identity mismatch")
        task = request["task"]
        task_id = task["task_id"]
        relative_path(task_id)
        if "/" in task_id or task["artifact"] != artifact(
            f"development/{task_id}.txt", TASK_BYTES, PRODUCING_RUN
        ):
            raise ValueError("runner only supports the literal fixture task")
        if task["dependencies"] or task["context"] or task["allowed_reference_material"]:
            raise ValueError("runner permits no extra task inputs")
        return attempt_record(
            request,
            verifier.verify(PROOF_BYTES),
            artifacts=[artifact("proof.txt", PROOF_BYTES, request["content_id"])],
            model_tokens=0,
        )


def validate_request(request: dict[str, Any]) -> None:
    validate_run_request(request)
    if request["tool_policy"] != {"network": False, "tools": []}:
        raise ValueError("fixture runner forbids network access and external tools")
    limits = request["limits"]
    if set(limits) != {"wall_seconds", "model_tokens"} or limits["model_tokens"] != 0:
        raise ValueError("fixture runner requires zero model tokens")
    if type(limits["wall_seconds"]) is not int or limits["wall_seconds"] <= 0:
        raise ValueError("wall limit must be positive")
    if request["output_artifacts"] != ["proof.txt"]:
        raise ValueError("unsupported output artifacts")


def plan(source: Any, policy: str, policy_revision: str, seeds: list[int]) -> dict[str, Any]:
    require_revision(policy_revision)
    if not policy or not seeds or len(set(seeds)) != len(seeds):
        raise ValueError("plan requires a policy and unique seeds")
    if any(type(seed) is not int or seed < 0 for seed in seeds):
        raise ValueError("seeds must be nonnegative integers")
    qualified = FixtureSourceDriver().qualify(source)
    runtime = FixtureVerifierDriver().preflight()
    runner = FixtureRunner().descriptor()
    attempts = []
    for task in qualified["development_tasks"]:
        for seed in seeds:
            attempts.append(
                seal(
                    {
                        "schema_version": "anarres.formal-run-request.v1",
                        "source": qualified["source"]["content_id"],
                        "source_driver": qualified["source_driver"],
                        "task": task,
                        "policy": {"identity": policy, "revision": policy_revision},
                        "harness": {"identity": runner["name"], "revision": runner["content_id"]},
                        "seed": seed,
                        "runtime": runtime,
                        "runner": runner,
                        "limits": {"wall_seconds": 10, "model_tokens": 0},
                        "tool_policy": {"network": False, "tools": []},
                        "output_artifacts": ["proof.txt"],
                    }
                )
            )
    return seal(
        {
            "schema_version": "anarres.formal-probe-plan.v1",
            "dry_run": True,
            "source_qualification": qualified["content_id"],
            "gates": {**qualified["gates"], "runtime_qualification": "fixture-qualified"},
            "steps": [
                {"order": 1, "operation": "qualify-source", "executed": True},
                {"order": 2, "operation": "qualify-runtime", "executed": True},
                {"order": 3, "operation": "require-task-containment", "executed": False},
                {"order": 4, "operation": "require-explicit-execution", "executed": False},
                {"order": 5, "operation": "run-ordered-attempts", "executed": False},
                {"order": 6, "operation": "verify-and-capture-attempts", "executed": False},
            ],
            "attempt_order": "task_id ascending, then seeds in supplied order",
            "attempts": attempts,
            "excluded_partitions": ["held-out"],
            "execution_available": False,
            "provider_calls": 0,
            "held_out_tasks_opened": False,
        }
    )


def runner_main() -> None:
    """Model-free external process conformance runner; never dispatch arbitrary code."""
    try:
        result = FixtureRunner().run(json.load(sys.stdin))
        # The tiny fixture proof is returned inline with its artifact reference.
        response = seal(
            {
                "schema_version": "anarres.formal-run-response.v1",
                "attempt": result,
                "outputs": {"proof.txt": "true\n"},
            }
        )
        print(json.dumps(response, sort_keys=True))
    except (ValueError, KeyError, TypeError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
