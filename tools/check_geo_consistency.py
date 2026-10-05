#!/usr/bin/env python3
"""Deterministically compare release facts across source and website content."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

import check_geo


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = "https://kabuforge.com/"
REPOSITORY = "https://github.com/Siyuan-chat/KabuForge"
VERSION_RE = re.compile(r"(?<![\w.])v?(\d+\.\d+\.\d+)(?![\w.+-])")


class CheckFailure(Exception):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailure(message)


def read(path: Path) -> str:
    require(path.is_file(), f"missing required evidence file: {path}")
    return path.read_text(encoding="utf-8")


def versions(text: str) -> list[str]:
    return VERSION_RE.findall(text)


def assert_current_version(text: str, version: str, label: str) -> str:
    found = versions(text)
    require(bool(found), f"no version evidence found in {label}")
    require(found[0] == version, f"{label} identifies {found[0]} as current; expected {version}")
    return found[0]


def validate_package_version(package_version: str, facts: dict) -> str:
    require(package_version == facts.get("source_branch_package_version"),
            "pyproject.toml version differs from source_branch_package_version in GEO facts")
    require(bool(re.fullmatch(r"\d+\.\d+\.\d+(?:[a-zA-Z0-9.+!-]+)?", package_version)),
            f"invalid source package version: {package_version!r}")
    return package_version


def validate_source_release_inputs(package_version: str, facts: dict,
                                   changelogs: dict[str, list[str]]) -> dict[str, str]:
    validate_package_version(package_version, facts)
    version = str(facts["current_release"]["version"])
    validated: dict[str, str] = {}
    for label, headings in changelogs.items():
        stable_heading = next((heading for heading in headings if version in versions(heading)), None)
        require(stable_heading is not None,
                f"changelog {label} has no current stable release heading {version}")
        validated[label] = assert_current_version(stable_heading or "", version, f"stable changelog heading {label}")
    return validated


def validate_release_page(current_section: object, version: str, tag: str, license_id: str,
                          repository: str, label: str) -> str:
    current_text = json.dumps(current_section, ensure_ascii=False)
    detected = assert_current_version(current_text, version, label)
    require(license_id in current_text, f"{label} current release section lacks project license")
    require(f"{repository}/releases/tag/{tag}" in current_text,
            f"{label} current release section lacks stable release URL")
    return detected


def current_readme_facts(text: str, language: str, version: str, license_id: str,
                         repository: str = REPOSITORY) -> str:
    markers = {
        "en": "Current stable package version:",
        "ja": "現在の安定パッケージ版は",
        "zh": "当前稳定包版本为",
    }
    marker = markers[language]
    current_line = next((line for line in text.splitlines() if marker in line), None)
    require(current_line is not None, f"README {language} current stable release line missing")
    found = versions(current_line)
    require(bool(found), f"README {language} current stable line has no stable version")
    require(found[0] == version,
            f"README {language} current release is {found[0]}; expected {version}")
    require(license_id in text, f"README {language} does not state current license {license_id}")
    require(CANONICAL in text, f"README {language} lacks canonical homepage")
    require(f"{repository}/releases/tag/v{version}" in text, f"README {language} lacks current stable release link")
    require("ArcaViso" in text and "https://arcaviso.com/" in text,
            f"README {language} lacks the bounded ArcaViso research-context link")

    capability_terms = {
        "en": ["Factor → Strategy", "backtesting", "local paper", "MCP"],
        "ja": ["Factor → Strategy", "バックテスト", "ローカル paper", "MCP"],
        "zh": ["Factor → Strategy", "回测", "本地纸上模拟", "MCP"],
    }[language]
    for term in capability_terms:
        require(term in text, f"README {language} omits a major capability term: {term}")
    boundary_terms = {
        "en": ["real broker order submission is disabled", "no complete historical PIT certification", "Synthetic examples are labeled and do not establish performance"],
        "ja": ["実ブローカーへの発注は無効", "完全な過去 PIT 認証ではありません", "合成例は明示し、運用成績の証明には使いません"],
        "zh": ["真实券商下单未启用", "不代表完整历史 PIT 认证", "合成示例须明确标识，不能证明绩效"],
    }[language]
    for term in boundary_terms:
        require(term in text, f"README {language} omits an important operating boundary: {term}")
    return found[0]


def check_release_snapshot(path: Path, version: str, tag: str, repository: str = REPOSITORY) -> str:
    try:
        release = json.loads(read(path))
    except json.JSONDecodeError as error:
        raise CheckFailure(f"invalid release JSON: {error}") from error
    require(isinstance(release, dict), "release JSON must be an object")
    require(release.get("tag_name") == tag, f"GitHub latest tag is {release.get('tag_name')!r}, expected {tag}")
    require(release.get("prerelease") is False, "GitHub latest release is marked prerelease")
    require(release.get("draft") is not True, "GitHub latest release is a draft")
    name = str(release.get("name") or "")
    require(version in name or tag in name, f"GitHub latest release name does not identify {tag}: {name!r}")
    require(release.get("html_url") == f"{repository}/releases/tag/{tag}",
            "GitHub release URL does not match canonical repository and tag")
    return tag


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--website", type=Path, default=ROOT / "website", help="website source tree (default: ./website)")
    parser.add_argument("--release-json", type=Path, help="optional captured GitHub /releases/latest JSON snapshot")
    args = parser.parse_args()

    try:
        facts = json.loads(read(ROOT / "docs/geo-facts.json"))
        current = facts["current_release"]
        version = str(current["version"])
        tag = str(current["tag"])
        canonical = str(facts["website"])
        repository = str(facts["repository"])
        documentation_url = str(facts["documentation"])
        license_id = str(facts["current_license"])
        require(tag == f"v{version}", "GEO facts current release tag/version mismatch")
        require(re.search(r"\d+\.\d+\.\d+", version) is not None, "GEO facts current release version is invalid")
        source_errors = check_geo.check(ROOT)
        require(not source_errors, f"source GEO checker failed: {source_errors}")

        project_file = ROOT / "pyproject.toml"
        pyproject = tomllib.loads(read(project_file))
        project = pyproject.get("project", {})
        project_urls = project.get("urls", {})
        project_name = str(project.get("name", ""))
        package_version = str(project.get("version", ""))
        require(project_name == "kabuforge", f"unexpected project name in pyproject.toml: {project_name!r}")
        require(bool(license_id), "pyproject.toml must declare a project license")
        require(project.get("license") == license_id, "pyproject.toml license differs from GEO facts")
        require(project_urls.get("Homepage") == canonical, "pyproject.toml Homepage differs from GEO facts")
        require(project_urls.get("Documentation") == documentation_url, "pyproject.toml Documentation differs from GEO facts")
        require(project_urls.get("Repository") == repository, "pyproject.toml Repository differs from GEO facts")

        detected: dict[str, str | None] = {"sourceBranchPackage": package_version, "stableRelease": version}
        changelogs = [
            ("changelog.en", ROOT / "docs/en_US/CHANGELOG.md"),
            ("changelog.ja", ROOT / "docs/ja_JP/CHANGELOG.md"),
            ("changelog.zh", ROOT / "docs/zh_CN/CHANGELOG.md"),
        ]
        changelog_headings = {}
        for key, path in changelogs:
            headings = re.findall(r"^##\s+([^\n]+)", read(path), re.MULTILINE)
            require(bool(headings), f"changelog has no release heading: {path}")
            changelog_headings[key] = headings
        detected.update(validate_source_release_inputs(package_version, facts, changelog_headings))

        readmes = [
            ("readme.en", ROOT / "README.md", "en"),
            ("readme.ja", ROOT / "README.ja_JP.md", "ja"),
            ("readme.zh", ROOT / "README.zh_CN.md", "zh"),
        ]
        readme_texts: dict[str, str] = {}
        for key, path, language in readmes:
            text = read(path)
            readme_texts[key] = text
            detected[key] = current_readme_facts(text, language, version, license_id, repository)

        citation_text = read(ROOT / "CITATION.cff")
        require(re.search(rf"^url:\s*{re.escape(canonical)}\s*$", citation_text, re.MULTILINE) is not None,
                "CITATION.cff url must be the canonical website")
        require(re.search(rf"^repository-code:\s*{re.escape(repository)}\s*$", citation_text, re.MULTILINE) is not None,
                "CITATION.cff repository-code must be the source repository")
        require(re.search(rf"^license:\s*{re.escape(license_id)}\s*$", citation_text, re.MULTILINE) is not None,
                "CITATION.cff license differs from pyproject.toml")
        citation_version = re.search(r"^version:\s*['\"]?([^\s'\"]+)", citation_text, re.MULTILINE)
        if citation_version:
            require(citation_version.group(1) == version, "CITATION.cff version is stale")

        website = args.website.resolve()
        layout = read(website / "src/layouts/Layout.astro")
        pages = json.loads(read(website / "src/data/pages.json"))
        llms = read(website / "public/llms.txt")
        homes = {
            "homepage.en": read(website / "src/pages/index.astro"),
            "homepage.ja": read(website / "src/pages/ja/index.astro"),
        }
        require(canonical in layout and repository in layout, "website layout canonical/repository identity mismatch")
        schema_version = re.search(r"version:'([^']+)'", layout)
        require(schema_version is not None, "website SoftwareSourceCode schema has no version")
        detected["schema"] = schema_version.group(1)
        require(schema_version.group(1) == version, "website JSON-LD version differs from pyproject.toml")
        require(f"https://spdx.org/licenses/{license_id}.html" in layout, "website JSON-LD license differs from pyproject.toml")
        software_schema = re.search(r"'@type':'SoftwareSourceCode',(.*?),isPartOf:", layout, re.DOTALL)
        require(software_schema is not None, "website SoftwareSourceCode schema missing")
        require("description:" in software_schema.group(0), "website SoftwareSourceCode schema needs a factual description")
        require("mentions:{'@type':'WebSite',name:'ArcaViso',url:'https://arcaviso.com/'}" in layout,
                "website must express the ArcaViso reference through WebSite mentions")
        require("name:'KabuForge'" in software_schema.group(0) and "programmingLanguage:'Python'" in software_schema.group(0),
                "website SoftwareSourceCode name/language missing")

        for key, home in homes.items():
            detected[key] = assert_current_version(home, version, key)
            require(f"{version} · tag {tag}" in home and license_id in home, f"{key} header version/license is stale")

        require(isinstance(pages, list), "website page source must be a JSON array")
        find_page = lambda slug: next((page for page in pages if page.get("slug") == slug), None)
        releases = find_page("releases")
        ja_releases = find_page("ja/releases")
        docs = [find_page("docs"), find_page("ja/docs")]
        quickstarts = [find_page("docs/quickstart"), find_page("ja/docs/quickstart")]
        require(releases is not None and ja_releases is not None and all(docs) and all(quickstarts),
                "website localized docs, quickstarts, or release pages are missing")
        for key, release_page in (("releases.en", releases), ("releases.ja", ja_releases)):
            current_section = release_page.get("sections", [{}])[0]
            detected[key] = validate_release_page(current_section, version, tag, license_id, repository, key)
        for key, doc, quickstart in zip(("docs.en", "docs.ja"), docs, quickstarts, strict=True):
            doc_text = json.dumps(doc, ensure_ascii=False)
            detected[key] = assert_current_version(doc_text, version, key)
            require("does not submit real orders" in doc_text or "実注文" in doc_text, f"{key} omits order boundary")
            quickstart_text = json.dumps(quickstart, ensure_ascii=False)
            assert_current_version(quickstart_text, version, f"quickstart.{key[-2:]}")
            require(f"git checkout {tag}" in quickstart_text, f"quickstart.{key[-2:]} does not checkout stable tag")

        detected["llms"] = assert_current_version(llms, version, "llms.txt")
        require(license_id in llms, "llms.txt current project license is stale")
        require(f"{repository}/releases/tag/{tag}" in llms, "llms.txt lacks current stable release URL")

        if args.release_json:
            detected["releaseSnapshot"] = check_release_snapshot(args.release_json, version, tag, repository)
        else:
            detected["releaseSnapshot"] = None
        print(json.dumps({"passed": True, "project": project_name, "version": version, "tag": tag,
                          "license": license_id, "website": str(website), "detectedVersion": detected,
                          "releaseSnapshot": str(args.release_json) if args.release_json else None,
                          "historicalVersions": "checked only as history; not compared to current facts"}, ensure_ascii=False))
        return 0
    except (CheckFailure, KeyError, TypeError, tomllib.TOMLDecodeError, json.JSONDecodeError, OSError) as error:
        print(f"GEO consistency check failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
