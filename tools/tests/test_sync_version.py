"""Source-level tests for the version generator; no website build or network."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "candidate_sync_version", REPO_ROOT / "tools" / "sync_version.py"
)
assert SPEC is not None and SPEC.loader is not None
sync_version = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync_version)

INPUT_FILES = (
    "pyproject.toml",
    "README.md",
    "README.zh_CN.md",
    "README.ja_JP.md",
    "website/src/data/version.json",
    "website/src/data/pages.json",
    "website/src/pages/index.astro",
    "website/src/pages/ja/index.astro",
)


class VersionSourceOfTruthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="kabuforge-version-source-")
        self.root = Path(self.temporary.name)
        for relative in INPUT_FILES:
            source = REPO_ROOT / relative
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _generated_sources(self) -> tuple[Path, ...]:
        return tuple(self.root / name for name in (
            "README.md", "README.zh_CN.md", "README.ja_JP.md",
            "website/src/data/version.json", "website/src/data/pages.json",
        ))

    def test_current_sources_match_pyproject_and_check_is_read_only(self) -> None:
        before = {path: path.read_bytes() for path in self._generated_sources()}
        self.assertEqual(sync_version.check_version_sync(self.root), [])
        after = {path: path.read_bytes() for path in self._generated_sources()}
        self.assertEqual(after, before)

    def test_version_change_is_detected_then_all_generated_surfaces_sync(self) -> None:
        pyproject = self.root / "pyproject.toml"
        text = pyproject.read_text(encoding="utf-8")
        self.assertEqual(text.count('version = "0.2.0rc1"'), 1)
        pyproject.write_text(text.replace('version = "0.2.0rc1"', 'version = "0.2.1rc1"', 1), encoding="utf-8")

        errors = sync_version.check_version_sync(self.root)
        self.assertTrue(any("pyproject.toml 0.2.1rc1" in error for error in errors))
        sync_version.sync(self.root)
        self.assertEqual(sync_version.check_version_sync(self.root), [])

        version_data = (self.root / "website/src/data/version.json").read_text(encoding="utf-8")
        pages = (self.root / "website/src/data/pages.json").read_text(encoding="utf-8")
        for locale in ("README.md", "README.zh_CN.md", "README.ja_JP.md"):
            self.assertIn("0.2.1rc1", (self.root / locale).read_text(encoding="utf-8"))
        self.assertIn('"version": "0.2.1rc1"', version_data)
        self.assertEqual(pages.count("0.2.1rc1"), 4)

    def test_history_remains_distinct_from_current_candidate_after_sync(self) -> None:
        pages_path = self.root / "website/src/data/pages.json"
        before = pages_path.read_text(encoding="utf-8")
        sync_version.sync(self.root)
        after = pages_path.read_text(encoding="utf-8")
        self.assertIn("c922d5439f6f018c140de14b6056f82b901dc434", after)
        self.assertIn("not the source identity for this candidate", after)
        self.assertIn("候補のソース識別情報ではありません", after)
        self.assertIn("v0.1.0", after)
        self.assertIn("0.1.0rc1", after)
        self.assertNotEqual(before, "")

    def test_bad_marker_fails_before_any_generated_file_changes(self) -> None:
        pages_path = self.root / "website/src/data/pages.json"
        pages_path.write_text(
            pages_path.read_text(encoding="utf-8").replace(
                "<!-- KABUFORGE:VERSION:RELEASES_EN:END -->", "", 1
            ), encoding="utf-8",
        )
        before = {path: path.read_bytes() for path in self._generated_sources()}
        with self.assertRaises(ValueError):
            sync_version.sync(self.root)
        after = {path: path.read_bytes() for path in self._generated_sources()}
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
