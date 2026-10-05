"""Negative fixtures for the deterministic GEO consistency checker."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import check_geo


class GeoCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for relative in ("README.md", "README.ja_JP.md", "README.zh_CN.md", "CITATION.cff",
                         "pyproject.toml", "docs/en_US/README.md", "docs/ja_JP/README.md",
                         "docs/zh_CN/README.md", "docs/geo-facts.json",
                         "docs/GEO_RELEASE_PROCESS.md", "docs/GEO_EVAL.md",
                         "docs/en_US/RELEASE_PROCESS.md", "docs/en_US/RESEARCH_METHODOLOGY.md",
                         "docs/en_US/ARCHITECTURE.md", "docs/en_US/AGENT_API.md",
                         "docs/en_US/EXECUTION.md", "docs/en_US/BROKER_API.md"):
            source = check_geo.ROOT / relative
            dest = self.root / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, dest)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_current_files_pass(self) -> None:
        self.assertEqual(check_geo.check(self.root), [])

    def test_homepage_current_version_drift_fails_but_historical_version_is_allowed(self) -> None:
        path = self.root / "README.md"
        facts = json.loads((self.root / "docs/geo-facts.json").read_text(encoding="utf-8"))
        version = facts["current_release"]["version"]
        text = path.read_text(encoding="utf-8")
        mutated = text.replace(f"Current stable package version: **{version}**",
                               f"Current stable package version: **{version}-drift**")
        self.assertNotEqual(mutated, text)
        path.write_text(mutated, encoding="utf-8")
        self.assertTrue(any("current stable version statement drift" in item for item in check_geo.check(self.root)))

    def test_wrong_citation_website_fails(self) -> None:
        path = self.root / "CITATION.cff"
        path.write_text(path.read_text(encoding="utf-8").replace("https://kabuforge.com/", "https://example.invalid/"), encoding="utf-8")
        self.assertTrue(any("citation URL must be the official website" in item for item in check_geo.check(self.root)))

    def test_current_license_drift_fails(self) -> None:
        path = self.root / "pyproject.toml"
        path.write_text(path.read_text(encoding="utf-8").replace("AGPL-3.0-only", "MIT"), encoding="utf-8")
        self.assertTrue(any("current license drift" in item for item in check_geo.check(self.root)))

    def test_current_readme_license_section_drift_fails_with_badge_intact(self) -> None:
        path = self.root / "README.md"
        text = path.read_text(encoding="utf-8")
        text = text.replace("Current project-owned code, documentation and assets are licensed under **AGPL-3.0-only**",
                            "Current project-owned code, documentation and assets are licensed under **MIT**")
        path.write_text(text, encoding="utf-8")
        self.assertTrue(any("current license statement drift" in item for item in check_geo.check(self.root)))

    def test_homepage_wrong_website_and_documentation_urls_fail(self) -> None:
        path = self.root / "README.md"
        text = path.read_text(encoding="utf-8").replace("[Website](https://kabuforge.com/)",
                                                          "[Website](https://kabuforge.com/evil)")
        text = text.replace("[Documentation](https://kabuforge.com/docs/)",
                            "[Documentation](https://example.invalid/docs/)")
        path.write_text(text, encoding="utf-8")
        errors = check_geo.check(self.root)
        self.assertTrue(any("homepage Website link drift" in item for item in errors))
        self.assertTrue(any("homepage Documentation link drift" in item for item in errors))

    def test_navigation_line_may_move_without_breaking_url_checks(self) -> None:
        path = self.root / "README.md"
        text = path.read_text(encoding="utf-8")
        moved = "Introductory text before navigation.\n\n" + text
        self.assertNotEqual(moved, text)
        path.write_text(moved, encoding="utf-8")
        self.assertEqual(check_geo.check(self.root), [])

    def test_documentation_current_version_statement_drift_fails(self) -> None:
        path = self.root / "docs/en_US/README.md"
        facts = json.loads((self.root / "docs/geo-facts.json").read_text(encoding="utf-8"))
        version = facts["current_release"]["version"]
        original = path.read_text(encoding="utf-8")
        mutated = original.replace(f"Package release `v{version}` is the current stable release",
                                   f"Package release `v{version}-drift` is the current stable release")
        self.assertNotEqual(mutated, original)
        path.write_text(mutated, encoding="utf-8")
        self.assertTrue(any("current stable version statement drift" in item for item in check_geo.check(self.root)))

    def test_citation_url_suffix_fails(self) -> None:
        path = self.root / "CITATION.cff"
        path.write_text(path.read_text(encoding="utf-8").replace("https://kabuforge.com/", "https://kabuforge.com/evil"), encoding="utf-8")
        self.assertTrue(any("citation URL must be the official website" in item for item in check_geo.check(self.root)))

    def test_development_package_can_lead_stable_release(self) -> None:
        facts_path = self.root / "docs/geo-facts.json"
        facts = json.loads(facts_path.read_text(encoding="utf-8"))
        current_package_version = facts["source_branch_package_version"]
        facts["source_branch_package_version"] = "0.2.0.dev1"
        facts_path.write_text(json.dumps(facts), encoding="utf-8")
        pyproject = self.root / "pyproject.toml"
        old = pyproject.read_text(encoding="utf-8")
        updated = old.replace(f'version = "{current_package_version}"', 'version = "0.2.0.dev1"')
        self.assertNotEqual(updated, old)
        pyproject.write_text(updated, encoding="utf-8")
        self.assertEqual(check_geo.check(self.root), [])

    def test_old_version_and_mit_history_do_not_fail(self) -> None:
        path = self.root / "README.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nHistorical `v0.0.9` was MIT.\n", encoding="utf-8")
        self.assertEqual(check_geo.check(self.root), [])


if __name__ == "__main__":
    unittest.main()
