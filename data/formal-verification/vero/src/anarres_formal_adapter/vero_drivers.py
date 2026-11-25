"""Portable interfaces around the unchanged Vero qualification implementations."""

from __future__ import annotations

from typing import Any

from anarres_formal_adapter import runtime_qualification, source_qualification
from anarres_formal_adapter.contracts import driver_identity


class VeroSourceDriver:
    def descriptor(self) -> dict[str, Any]:
        pin = source_qualification.load_source_pin()
        return driver_identity(
            "source-driver",
            "vero-checkout-v1",
            ("vero_drivers.py", "source_qualification.py", "source-pin.json"),
            language="Lean",
            toolchain=f"leanprover/lean4:v{pin['lean_version']}",
            source_pin=pin,
            endpoints=["proof-only", "code-and-proof"],
            native_modes={"proof-only": "proof", "code-and-proof": "codeproof"},
            source_qualification=True,
            policy_probe=False,
            decision=False,
        )

    def qualify(self, source: Any) -> dict[str, Any]:
        pin = source_qualification.load_source_pin()
        expected = f"git:{pin['commit']}"
        if source.revision != expected:
            raise ValueError(f"manifest revision must identify the released Vero commit {expected}")
        if source.license != pin["license"]:
            raise ValueError(
                "manifest license must preserve Vero's benchmark-specific upstream licenses"
            )
        return source_qualification.qualify(source.source)


class VeroVerifierDriver:
    def descriptor(self) -> dict[str, Any]:
        return driver_identity(
            "verifier-driver",
            "vero-strict-lean-v1",
            ("vero_drivers.py", "runtime_qualification.py", "source-pin.json"),
            language="Lean",
            endpoints=["proof-only", "code-and-proof"],
            runtime_qualification=True,
            task_containment=False,
            strict_success="exit-zero-and-all-specifications-verified",
            native_command="runtime-contract.verifier.command",
            trusted_assumptions="source manifests; no new axiom audit in preflight",
        )

    def preflight(self, **inputs: Any) -> dict[str, Any]:
        return runtime_qualification.qualify(**inputs)
