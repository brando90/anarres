"""Exercise the shared native command path from a temporary external directory."""

import importlib
import json
import os
import shlex
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data/formal-verification/vero/src"))
CONTRACTS = importlib.import_module("anarres_formal_adapter.contracts")


def build_cli(checkout: Path, environment: dict[str, str]) -> Path:
    """Build anarres-cli and return the anarres executable that Cargo reports.

    CARGO_TARGET_DIR and other Cargo settings can place the executable outside
    target/debug, where a binary from another revision may remain.
    """
    built = subprocess.run(
        ["cargo", "build", "--quiet", "--message-format=json", "-p", "anarres-cli"],
        cwd=checkout,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    messages = [json.loads(line) for line in built.stdout.splitlines() if line.startswith("{")]
    if built.returncode != 0:
        diagnostics = "".join(
            message["message"].get("rendered") or ""
            for message in messages
            if message.get("reason") == "compiler-message"
        )
        raise AssertionError(f"cargo build failed\n{diagnostics}{built.stderr}")
    manifest = (checkout / "crates/anarres-cli/Cargo.toml").resolve()
    executables = [
        Path(message["executable"])
        for message in messages
        if message.get("reason") == "compiler-artifact"
        and Path(message["manifest_path"]).resolve() == manifest
        and message["target"]["name"] == "anarres"
        and message["target"]["kind"] == ["bin"]
        and message["executable"]
    ]
    if len(executables) != 1:
        raise AssertionError(f"Cargo reported {len(executables)} anarres executables")
    return executables[0]


def run_cli(
    binary: Path, arguments: tuple[str, ...], cwd: Path, environment: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(binary), *arguments],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


@unittest.skipUnless(os.name == "posix", "executable wrappers require POSIX")
class CargoExecutableSelectionTest(unittest.TestCase):
    def test_stale_default_executable_cannot_mask_a_broken_current_build(self) -> None:
        # Real Cargo builds a minimal anarres-cli package into CARGO_TARGET_DIR while an
        # executable from an earlier default build remains at target/debug/anarres.
        with tempfile.TemporaryDirectory(prefix="formal-cargo-") as directory:
            checkout = Path(directory) / "checkout"
            package = checkout / "crates/anarres-cli"
            (package / "src").mkdir(parents=True)
            (checkout / "Cargo.toml").write_text(
                '[workspace]\nmembers = ["crates/anarres-cli"]\nresolver = "2"\n',
                encoding="utf-8",
            )
            (package / "Cargo.toml").write_text(
                '[package]\nname = "anarres-cli"\nversion = "0.0.0"\nedition = "2021"\n'
                'publish = false\n\n[[bin]]\nname = "anarres"\npath = "src/main.rs"\n',
                encoding="utf-8",
            )
            # The current source builds an anarres executable that fails every command.
            (package / "src/main.rs").write_text(
                'fn main() {\n    eprintln!("current build is broken");\n'
                "    std::process::exit(3);\n}\n",
                encoding="utf-8",
            )
            # An executable from an earlier default build succeeds for every command.
            stale = checkout / "target/debug/anarres"
            stale_script = "#!/bin/sh\nexit 0\n"
            stale.parent.mkdir(parents=True)
            stale.write_text(stale_script, encoding="utf-8")
            stale.chmod(stale.stat().st_mode | stat.S_IXUSR)
            target = Path(directory) / "configured-target"
            environment = {**os.environ, "CARGO_TARGET_DIR": str(target)}
            arguments = ("adapter", "doctor", "formal", "--json")
            self.assertEqual(run_cli(stale, arguments, checkout, environment).returncode, 0)

            binary = build_cli(checkout, environment)
            self.assertTrue(binary.resolve().is_relative_to(target.resolve()), binary)
            self.assertEqual(stale.read_text(encoding="utf-8"), stale_script)
            result = run_cli(binary, arguments, checkout, environment)
            self.assertEqual((result.returncode, result.stderr), (3, "current build is broken\n"))


@unittest.skipUnless(os.name == "posix", "executable wrappers require POSIX")
class FormalPortableCliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Always build, then run the executable Cargo reports. Neither a binary left from
        # another revision nor a configured target directory can decide the result.
        cls.binary = build_cli(ROOT, dict(os.environ))

    def test_outside_checkout_init_inspect_qualify_dry_run(self) -> None:
        with tempfile.TemporaryDirectory(prefix="formal-portable-") as directory:
            outside = Path(directory)
            self.assertFalse(outside.is_relative_to(ROOT))
            for name, module in (("formal", "cli"), ("formal-fixture", "fixture_cli")):
                executable = outside / f"anarres-{name}"
                executable.write_text(
                    f"#!/bin/sh\nexec {shlex.quote(sys.executable)} "
                    f'-m anarres_formal_adapter.{module} "$@"\n',
                    encoding="utf-8",
                )
                executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
            environment = {
                **os.environ,
                "PATH": os.pathsep.join([str(outside), os.environ.get("PATH", "")]),
                "PYTHONPATH": os.pathsep.join(
                    str(ROOT / path)
                    for path in (
                        "packages/core/src",
                        "packages/environments/src",
                        "data/formal-verification/vero/src",
                    )
                ),
            }

            def run(*arguments: str, ok: bool = True) -> subprocess.CompletedProcess[str]:
                result = run_cli(self.binary, arguments, outside, environment)
                if ok:
                    self.assertEqual(result.returncode, 0, result.stderr)
                else:
                    self.assertNotEqual(result.returncode, 0)
                return result

            doctor = json.loads(run("adapter", "doctor", "formal", "--json").stdout)
            self.assertTrue(doctor["valid"])
            self.assertNotIn("policy-probe", doctor["descriptor"]["capabilities"])
            self.assertEqual(doctor["descriptor"]["source_formats"], ["vero-checkout-v1"])
            contracts = run("formal", "contracts", "--json").stdout
            self.assertEqual(contracts, run("formal", "contracts", "--json").stdout)
            described = json.loads(contracts)
            self.assertIs(described["policy_probe"], False)
            for key in ("source_driver", "verifier_driver"):
                CONTRACTS.verify_seal(described[key])
            readable = run("formal", "contracts").stdout
            self.assertIn("Source Driver\n{\n", readable)
            self.assertIn("Policy probe  false", readable)
            created = json.loads(run("formal-fixture", "create", "source").stdout)
            run(
                "init",
                "source",
                "--adapter",
                "formal-fixture",
                "--revision",
                created["revision"],
                "--license",
                created["license"],
            )
            inspection = json.loads(run("inspect", "source", "--json").stdout)
            self.assertTrue(inspection["qualification_ready"])
            self.assertTrue(inspection["probe_plan_ready"])
            self.assertFalse(inspection["probe_ready"])
            qualified = run("qualify", "source", "--json").stdout
            self.assertEqual(qualified, run("qualify", "source", "--json").stdout)
            self.assertEqual(json.loads(qualified)["status"], "qualified")
            common = (
                "probe",
                "source",
                "--policy",
                "fixture-policy",
                "--policy-revision",
                created["revision"],
            )
            first = run(
                *common, "--output", "plan-a.json", "--dry-run", "--", "--seed", "3", "--seed", "1"
            )
            second = run(
                *common, "--output", "plan-b.json", "--dry-run", "--", "--seed", "3", "--seed", "1"
            )
            self.assertEqual(first.stdout, second.stdout)
            self.assertEqual(first.stdout, (outside / "plan-a.json").read_text())
            self.assertEqual(
                (outside / "plan-a.json").read_bytes(), (outside / "plan-b.json").read_bytes()
            )
            plan = json.loads(first.stdout)
            self.assertEqual(
                [(item["task"]["task_id"], item["seed"]) for item in plan["attempts"]],
                [("a", 3), ("a", 1), ("b", 3), ("b", 1)],
            )
            self.assertEqual([step["order"] for step in plan["steps"]], list(range(1, 7)))
            self.assertEqual(plan["provider_calls"], 0)
            self.assertFalse(plan["held_out_tasks_opened"])
            self.assertFalse((outside / "source/held-out").exists())
            self.assertFalse(plan["execution_available"])
            refused = run(*common, "--output", "executed.json", ok=False)
            self.assertIn("does not declare policy probing", refused.stderr)
            self.assertFalse((outside / "executed.json").exists())
            # A dry run cannot replace source inputs, even with --force.
            native_bytes = (outside / "source/fixture.json").read_bytes()
            refused = run(
                *common, "--output", "source/fixture.json", "--force", "--dry-run", ok=False
            )
            self.assertIn("outside the native source", refused.stderr)
            self.assertEqual((outside / "source/fixture.json").read_bytes(), native_bytes)
            alias = outside / "linked-plan.json"
            manifest = outside / "source/anarres.toml"
            manifest_bytes = manifest.read_bytes()
            alias.hardlink_to(manifest)
            refused = run(*common, "--output", "linked-plan.json", "--force", "--dry-run", ok=False)
            self.assertIn("symbolic or hard link", refused.stderr)
            self.assertEqual((outside / "source/fixture.json").read_bytes(), native_bytes)
            self.assertEqual(manifest.read_bytes(), manifest_bytes)
            # A manifest outside its native source is also protected from the plan output.
            outer = outside / "outer"
            outer.mkdir()
            (outside / "source").rename(outer / "native")
            outer_manifest = outer / "anarres.toml"
            outer_manifest.write_bytes(manifest_bytes.replace(b'uri = "."', b'uri = "native"'))
            (outer / "native/anarres.toml").unlink()
            outer_bytes = outer_manifest.read_bytes()
            self.assertNotEqual(outer_bytes, manifest_bytes)
            outer_common = ("probe", "outer", *common[2:])
            run(*outer_common, "--output", "outer-plan.json", "--dry-run")
            refused = run(
                *outer_common, "--output", "outer/anarres.toml", "--force", "--dry-run", ok=False
            )
            self.assertIn("must not replace the source manifest", refused.stderr)
            self.assertEqual(outer_manifest.read_bytes(), outer_bytes)


if __name__ == "__main__":
    unittest.main()
