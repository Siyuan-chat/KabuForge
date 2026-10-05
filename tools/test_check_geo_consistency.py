"""Focused standard-library tests for the website/source GEO consistency rules."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import check_geo
import check_geo_consistency as website_geo


ROOT = Path(__file__).resolve().parents[1]
FACTS = json.loads((ROOT / "docs/geo-facts.json").read_text(encoding="utf-8"))
VERSION = FACTS["current_release"]["version"]
LICENSE = FACTS["current_license"]
REPOSITORY = FACTS["repository"]


class WebsiteGeoConsistencyTests(unittest.TestCase):
    def test_current_source_geo_and_all_readmes_pass(self) -> None:
        self.assertEqual(check_geo.check(ROOT), [])
        for path, language in (("README.md", "en"), ("README.ja_JP.md", "ja"), ("README.zh_CN.md", "zh")):
            text = (ROOT / path).read_text(encoding="utf-8")
            self.assertEqual(website_geo.current_readme_facts(text, language, VERSION, LICENSE, REPOSITORY), VERSION)

    def test_wrong_stable_version_is_rejected(self) -> None:
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        with self.assertRaises(website_geo.CheckFailure):
            website_geo.current_readme_facts(text, "en", "0.0.9", LICENSE, REPOSITORY)

    def test_release_candidate_is_not_accepted_as_stable(self) -> None:
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        rc_text = text.replace(f"Current stable package version: **{VERSION}**",
                               "Current stable package version: **0.1.0rc1**")
        self.assertNotEqual(rc_text, text)
        with self.assertRaises(website_geo.CheckFailure):
            website_geo.current_readme_facts(rc_text, "en", VERSION, LICENSE, REPOSITORY)

    def test_development_package_can_lead_stable_release(self) -> None:
        facts = dict(FACTS)
        facts["source_branch_package_version"] = "0.2.0.dev1"
        headings = {
            "changelog.en": ["Unreleased", "0.2.0.dev1 — development", f"{VERSION} — formal release"],
            "changelog.ja": ["Unreleased", "0.2.0.dev1 — development", f"{VERSION} — formal release"],
            "changelog.zh": ["Unreleased", "0.2.0.dev1 — development", f"{VERSION} — formal release"],
        }
        validated = website_geo.validate_source_release_inputs("0.2.0.dev1", facts, headings)
        self.assertEqual(set(validated.values()), {VERSION})
        self.assertEqual(facts["current_release"]["version"], VERSION)

    def test_each_release_page_must_link_to_current_release(self) -> None:
        section = {"version": VERSION, "license": LICENSE,
                   "release": f"{REPOSITORY}/releases/tag/v{VERSION}"}
        self.assertEqual(website_geo.validate_release_page(section, VERSION, f"v{VERSION}", LICENSE,
                                                           REPOSITORY, "release.en"), VERSION)
        section["release"] = f"{REPOSITORY}/releases"
        with self.assertRaises(website_geo.CheckFailure):
            website_geo.validate_release_page(section, VERSION, f"v{VERSION}", LICENSE,
                                              REPOSITORY, "release.en")


if __name__ == "__main__":
    unittest.main()
