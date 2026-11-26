"""Versioned, content-addressed boundaries for formal source integrations.

Drivers are trusted installed code. These contracts describe identities and
evidence boundaries; they do not provide a process sandbox or authorize a run.
"""

from __future__ import annotations

import hashlib
import json
import re
import stat
from dataclasses import asdict, dataclass
from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

ENDPOINTS = (
    "proof-only",
    "code-and-proof",
    "specification-construction",
    "specification-faithfulness",
)
OUTCOMES = (
    "strict-success",
    "strict-proof-failure",
    "parser-failure",
    "build-failure",
    "verifier-failure",
    "timeout",
    "unsupported",
    "infrastructure-failure",
)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def seal(value: dict[str, Any]) -> dict[str, Any]:
    """Bind every field except the identity field itself."""
    if not isinstance(value, dict):
        raise ValueError("contract must be a JSON object")
    body = {key: item for key, item in value.items() if key != "content_id"}
    return {**body, "content_id": digest(canonical(body))}


def verify_seal(value: dict[str, Any]) -> None:
    if not isinstance(value, dict):
        raise ValueError("contract must be a JSON object")
    if value.get("content_id") != seal(value)["content_id"]:
        raise ValueError("content identity mismatch")


def require_digest(value: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise ValueError("expected a SHA-256 identity")


def require_revision(value: str) -> None:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"(?:sha256:[0-9a-f]{64}|git:[0-9a-f]{40})", value) is None
    ):
        raise ValueError("revision must be an immutable git or SHA-256 identity")


def relative_path(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValueError("invalid relative artifact path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or str(path) != value or value == ".":
        raise ValueError("artifact path escapes its source or is not canonical")
    return path


def contained_file(root: Path, relative: str) -> Path:
    path = root / relative_path(relative)
    # Reject symlinks before reading, including links to another task in the source.
    for parent in (path, *path.parents):
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError("artifact path uses a symlink")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("artifact path escapes its source")
    # Classify the path from its metadata alone. Opening a FIFO blocks until a writer appears.
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("artifact path is not a regular file")
    if metadata.st_nlink != 1:
        raise ValueError("artifact path uses a hard link")
    return path


def driver_identity(
    kind: str,
    name: str,
    modules: tuple[str, ...],
    *,
    package: str = "anarres_formal_adapter",
    **contract: Any,
) -> dict:
    """Address the interface, declared semantics, and installed implementation bytes."""
    if kind not in {"source-driver", "verifier-driver", "prover-runner"}:
        raise ValueError("unknown formal interface")
    resources = files(package)
    implementation = {
        module: digest(resources.joinpath(module).read_bytes()) for module in sorted(set(modules))
    }
    implementation["anarres_formal_adapter/contracts.py"] = digest(
        files("anarres_formal_adapter").joinpath("contracts.py").read_bytes()
    )
    return seal(
        {
            "schema_version": f"anarres.formal-{kind}.v1",
            "name": name,
            "version": "1",
            "package": package,
            "implementation": implementation,
            "contract": contract,
        }
    )


class SourceDriver(Protocol):
    def descriptor(self) -> dict[str, Any]: ...

    def qualify(self, source: Any) -> dict[str, Any]: ...


class VerifierDriver(Protocol):
    def descriptor(self) -> dict[str, Any]: ...

    def preflight(self, **inputs: Any) -> dict[str, Any]: ...


class ProverRunner(Protocol):
    def descriptor(self) -> dict[str, Any]: ...

    def run(self, request: dict[str, Any]) -> dict[str, Any]: ...


def validate_run_request(request: dict[str, Any]) -> None:
    """Validate an external request without opening its source or outputs."""
    verify_seal(request)
    if (
        set(request)
        != {
            "schema_version",
            "source",
            "source_driver",
            "task",
            "policy",
            "harness",
            "seed",
            "runtime",
            "runner",
            "limits",
            "tool_policy",
            "output_artifacts",
            "content_id",
        }
        or request["schema_version"] != "anarres.formal-run-request.v1"
    ):
        raise ValueError("unsupported runner request")
    require_digest(request["source"])
    for key in ("source_driver", "runtime", "runner"):
        verify_seal(request[key])
    for key in ("policy", "harness"):
        if (
            set(request[key]) != {"identity", "revision"}
            or not isinstance(request[key]["identity"], str)
            or not request[key]["identity"]
        ):
            raise ValueError(f"invalid {key} identity")
        require_revision(request[key]["revision"])
    if type(request["seed"]) is not int or request["seed"] < 0:
        raise ValueError("seed must be a nonnegative integer")
    task = request["task"]
    if not isinstance(task, dict):
        raise ValueError("task must be a JSON object")
    if not isinstance(task.get("task_id"), str) or not task["task_id"]:
        raise ValueError("missing task identity")
    if task.get("partition") != "development":
        raise ValueError("runner refuses held-out or undeclared tasks")
    item = task["artifact"]
    if not isinstance(item, dict):
        raise ValueError("task artifact must be a JSON object")
    relative_path(item["path"])
    require_digest(item["sha256"])
    if (
        item.get("uri") != item["path"]
        or type(item.get("size_bytes")) is not int
        or item["size_bytes"] < 0
        or any(
            not isinstance(item.get(key), str) or not item[key]
            for key in ("media_type", "license", "producing_run")
        )
    ):
        raise ValueError("invalid task artifact reference")
    limits = request["limits"]
    if set(limits) != {"wall_seconds", "model_tokens"}:
        raise ValueError("unsupported resource limits")
    if type(limits["wall_seconds"]) is not int or limits["wall_seconds"] <= 0:
        raise ValueError("wall limit must be positive")
    if type(limits["model_tokens"]) is not int or limits["model_tokens"] < 0:
        raise ValueError("model token limit must be nonnegative")
    policy = request["tool_policy"]
    if (
        set(policy) != {"network", "tools"}
        or type(policy["network"]) is not bool
        or not isinstance(policy["tools"], list)
        or any(not isinstance(tool, str) or not tool for tool in policy["tools"])
    ):
        raise ValueError("invalid tool policy")
    outputs = request["output_artifacts"]
    if not isinstance(outputs, list) or not outputs or len(set(outputs)) != len(outputs):
        raise ValueError("output artifacts must be unique relative paths")
    for path in outputs:
        relative_path(path)


@dataclass(frozen=True)
class CandidateContract:
    """Comparison identity only; no score, selection rule, or downstream outcome."""

    language: str
    toolchain: str
    endpoint: str
    policy: str
    policy_revision: str
    target: str
    verifier: str
    unit: str
    measurement: str
    assumptions: str

    def record(self) -> dict[str, Any]:
        if any(not isinstance(value, str) or not value for value in asdict(self).values()):
            raise ValueError("candidate identity fields must be nonempty strings")
        if self.endpoint not in ENDPOINTS:
            raise ValueError("unsupported endpoint")
        require_revision(self.policy_revision)
        for value in (self.target, self.verifier, self.measurement, self.assumptions):
            require_digest(value)
        return seal({"schema_version": "anarres.formal-candidate-contract.v1", **asdict(self)})


def require_compatible(candidates: list[CandidateContract]) -> None:
    if len(candidates) < 2:
        raise ValueError("comparison requires at least two candidates")
    first = candidates[0].record()
    for candidate in candidates[1:]:
        other = candidate.record()
        changed = [key for key in asdict(candidate) if first[key] != other[key]]
        if changed:
            raise ValueError(f"incompatible candidate contracts: {', '.join(changed)}")


def attempt_record(
    request: dict[str, Any],
    outcome: str,
    *,
    artifacts: list[dict],
    model_tokens: int | None = None,
    wall_seconds: float | None = None,
) -> dict:
    """Keep invalid execution distinct from a valid unsuccessful proof attempt."""
    validate_run_request(request)
    if outcome not in OUTCOMES:
        raise ValueError("unsupported attempt outcome")
    if model_tokens is not None and (type(model_tokens) is not int or model_tokens < 0):
        raise ValueError("model tokens must be a nonnegative integer or unmeasured")
    if wall_seconds is not None and (
        isinstance(wall_seconds, bool)
        or not isinstance(wall_seconds, (int, float))
        or wall_seconds < 0
    ):
        raise ValueError("wall time must be nonnegative or unmeasured")
    return seal(
        {
            "schema_version": "anarres.formal-attempt.v1",
            "request_id": request["content_id"],
            "task_id": request["task"]["task_id"],
            "seed": request["seed"],
            "outcome": outcome,
            "strict_success": outcome == "strict-success",
            "proof_failure": outcome == "strict-proof-failure",
            "cost": {"model_tokens": model_tokens, "wall_seconds": wall_seconds},
            "artifacts": artifacts,
        }
    )
