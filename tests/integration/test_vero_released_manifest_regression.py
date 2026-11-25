"""Keep the released formal evidence byte-identical to the PR #66 baseline."""

import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# These are hashes of the actual manifests at d168e2a, not hashes regenerated
# from the files under test. Updating an evidence file and its manifest together
# must fail this regression just as updating an evidence file alone does.
RELEASES = (
    (
        "data/formal-verification/vero/results/repeated-measurement.codex-sol-v2",
        "c143f2918434cf85fb61785f6e1dbe26b5cfed1d587f194e3611d9a4068e5a6f",
        98,
    ),
    (
        "experiments/cyber/formal-verification/public-evidence",
        "89d404d5fb0435d37bd2d413213f82b9b50d47ef9310965ffbfb7da60e3c07be",
        12,
    ),
)


class VeroReleasedManifestRegressionTest(unittest.TestCase):
    def assert_release_unchanged(self, root: Path, manifest_digest: str, count: int) -> None:
        manifest = root / "MANIFEST.sha256"
        self.assertEqual(
            hashlib.sha256(manifest.read_bytes()).hexdigest(),
            manifest_digest,
            f"released manifest changed: {manifest}",
        )
        entries = manifest.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(entries), count)
        seen = set()
        for entry in entries:
            expected, relative = entry.split("  ", 1)
            path = (root / relative).resolve()
            self.assertTrue(path.is_relative_to(root.resolve()), relative)
            self.assertNotIn(path, seen, f"duplicate released file: {relative}")
            seen.add(path)
            self.assertTrue(path.is_file(), f"released file missing: {relative}")
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(),
                expected,
                f"released file changed: {relative}",
            )

    def test_every_released_manifest_entry_is_byte_identical(self) -> None:
        for relative, manifest_digest, count in RELEASES:
            with self.subTest(release=relative):
                self.assert_release_unchanged(ROOT / relative, manifest_digest, count)

    def test_evidence_tampering_fails_without_reading_record_fields(self) -> None:
        for relative, manifest_digest, count in RELEASES:
            with self.subTest(release=relative), tempfile.TemporaryDirectory() as directory:
                release = Path(directory) / "release"
                shutil.copytree(ROOT / relative, release)
                first = (release / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines()[0]
                _, filename = first.split("  ", 1)
                path = release / filename
                path.write_bytes(path.read_bytes() + b"\n")
                with self.assertRaisesRegex(AssertionError, "released file changed"):
                    self.assert_release_unchanged(release, manifest_digest, count)

    def test_rewriting_manifest_to_match_tampered_evidence_still_fails(self) -> None:
        for relative, manifest_digest, count in RELEASES:
            with self.subTest(release=relative), tempfile.TemporaryDirectory() as directory:
                release = Path(directory) / "release"
                shutil.copytree(ROOT / relative, release)
                manifest = release / "MANIFEST.sha256"
                entries = manifest.read_text(encoding="utf-8").splitlines()
                _, filename = entries[0].split("  ", 1)
                path = release / filename
                path.write_bytes(path.read_bytes() + b"\n")
                entries[0] = f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {filename}"
                manifest.write_text("\n".join(entries) + "\n", encoding="utf-8")
                with self.assertRaisesRegex(AssertionError, "released manifest changed"):
                    self.assert_release_unchanged(release, manifest_digest, count)


if __name__ == "__main__":
    unittest.main()
