"""Installed, model-free conformance path for the portable formal contracts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from anarres.core import consume_adapter_invocation, load_source_manifest

from anarres_formal_adapter import fixture


def adapter_descriptor() -> dict:
    return {
        "schema_version": "anarres.adapter-descriptor.v1",
        "name": "formal-fixture",
        "version": "0.2.0",
        "protocol_version": 2,
        "domain": "formal-verification",
        "executable": "anarres-formal-fixture",
        "profile_schema_versions": ["anarres.environment-profile-input.v1"],
        "capabilities": ["probe-plan", "source-qualification"],
        "measurement_contracts": [],
        "source_formats": [fixture.FORMAT],
    }


def main() -> None:
    raw = sys.argv[1:]
    if raw == ["--anarres-adapter-descriptor"]:
        print(json.dumps(adapter_descriptor(), sort_keys=True))
        return
    try:
        raw = consume_adapter_invocation(raw, expected_name="formal-fixture")
        parser = argparse.ArgumentParser(description=__doc__)
        commands = parser.add_subparsers(dest="command", required=True)
        create = commands.add_parser("create", help="Create native synthetic fixture files.")
        create.add_argument("directory", type=Path)
        verify = commands.add_parser(
            "verify-fixture", help="Check a literal fixture proof on stdin."
        )
        verify.add_argument("--json", action="store_true")
        qualify = commands.add_parser("qualify-source")
        qualify.add_argument("--manifest", type=Path, required=True)
        qualify.add_argument("--json", action="store_true")
        probe = commands.add_parser("probe-source", help="Print the full ordered fixture plan.")
        probe.add_argument("--manifest", type=Path, required=True)
        probe.add_argument("--policy", required=True)
        probe.add_argument("--policy-revision", required=True)
        probe.add_argument("--output", type=Path, required=True)
        probe.add_argument("--dry-run", action="store_true", required=True)
        probe.add_argument("--seed", type=int, action="append")
        probe.add_argument("--force", action="store_true")
        probe.add_argument("--json", action="store_true")
        args = parser.parse_args(raw)
        if args.command == "create":
            record = fixture.create_source(args.directory)
            result = {"revision": record["content_id"], "license": record["license"]}
        elif args.command == "verify-fixture":
            result = {"outcome": fixture.FixtureVerifierDriver().verify(sys.stdin.buffer.read())}
        else:
            source = load_source_manifest(
                args.manifest,
                expected_adapter="formal-fixture",
                expected_version="0.2.0",
                expected_domain="formal-verification",
                accepted_formats=(fixture.FORMAT,),
            )
            if args.command == "qualify-source":
                result = fixture.FixtureSourceDriver().qualify(source)
            else:
                result = fixture.plan(source, args.policy, args.policy_revision, args.seed or [0])
                # A plan cannot overwrite native data, including through a parent symlink.
                if args.output.resolve().is_relative_to(source.source.resolve()):
                    raise ValueError("plan output must be outside the native source")
                if args.output.is_symlink() or (
                    args.output.exists() and args.output.stat().st_nlink != 1
                ):
                    raise ValueError("plan output must not be a symbolic or hard link")
                args.output.parent.mkdir(parents=True, exist_ok=True)
                with args.output.open("w" if args.force else "x", encoding="utf-8") as stream:
                    stream.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
        # Planning always prints every step and request, even without --json.
        print(json.dumps(result, indent=2, sort_keys=True))
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
