"""Check public release facts and discoverability claims without network access."""
from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOMEPAGES = ("README.md", "README.ja_JP.md", "README.zh_CN.md")
DOC_HOME = {
    "docs/en_US/README.md": "English documentation",
    "docs/ja_JP/README.md": "Japanese documentation",
    "docs/zh_CN/README.md": "Chinese documentation",
}


def check(root: Path = ROOT) -> list[str]:
    facts = json.loads((root / "docs/geo-facts.json").read_text(encoding="utf-8"))
    release = facts["current_release"]
    version, tag = release["version"], release["tag"]
    license_id = facts["current_license"]
    site, repo, documentation = facts["website"], facts["repository"], facts["documentation"]
    errors: list[str] = []

    def require(path: str, condition: bool, message: str) -> None:
        if not condition:
            errors.append(f"{path}: {message}")

    stable_link = f"{repo}/releases/tag/{tag}"
    if release.get("release_url") != stable_link:
        errors.append("docs/geo-facts.json: current release URL does not match repository and tag")
    stable_clone = f"git clone --branch {tag} --depth 1 {repo}.git"
    badge_license = "license-" + license_id.replace("-", "--")
    for name in HOMEPAGES:
        path = root / name
        if not path.exists():
            errors.append(f"missing homepage: {name}")
            continue
        text = path.read_text(encoding="utf-8")
        if name == "README.md":
            version_pattern = rf"^Current stable package version:\s*\*\*{re.escape(version)}\*\*\."
        elif name == "README.ja_JP.md":
            version_pattern = rf"^現在の安定パッケージ版は \*\*{re.escape(version)}\*\*"
        else:
            version_pattern = rf"^当前稳定包版本为 \*\*{re.escape(version)}\*\*"
        require(name, bool(re.search(version_pattern, text, re.M)), "current stable version statement drift")
        require(name, bool(re.search(rf"\[[^]]+\]\({re.escape(stable_link)}\)", text)), "current stable release link missing")
        require(name, stable_clone in text, "stable install must pin the current release tag")
        require(name, badge_license in text, "current license badge drift")
        nav_line = next((line for line in text.splitlines()
                         if "[Website]" in line and "[Documentation]" in line), None)
        links = ({label: url for label, url in re.findall(r"\[([^]]+)\]\(([^)]+)\)", nav_line)}
                 if nav_line is not None else {})
        require(name, links.get("Website") == site, "homepage Website link drift")
        require(name, links.get("Documentation") == documentation, "homepage Documentation link drift")
        license_section = re.search(r"^## (?:License|ライセンス|许可证)\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
        if name == "README.md":
            license_pattern = r"Current project-owned code, documentation and assets are licensed under \*\*(.*?)\*\*"
        elif name == "README.ja_JP.md":
            license_pattern = r"現在のプロジェクト所有のコード、文書、資産は \*\*(.*?)\*\*"
        else:
            license_pattern = r"当前项目自有代码、文档与资产采用 \*\*(.*?)\*\*"
        license_match = re.search(license_pattern, license_section.group(1) if license_section else "")
        require(name, bool(license_match and license_match.group(1) == license_id), "current license statement drift")
        require(name, facts["historical_release"]["version"] in text, "historical release context missing")
        require(name, "CITATION.cff" in text and "available_at" in text and "UNKNOWN" in text,
                "citation or research limitation markers missing")

    citation_path = root / "CITATION.cff"
    citation = citation_path.read_text(encoding="utf-8")
    def cff_value(key: str) -> str | None:
        match = re.search(rf"^{re.escape(key)}:\s*(.*?)\s*$", citation, re.M)
        return match.group(1) if match else None

    require("CITATION.cff", cff_value("url") == site, "citation URL must be the official website")
    require("CITATION.cff", cff_value("repository-code") == repo, "repository-code must remain GitHub")
    require("CITATION.cff", cff_value("version") == version, "citation version drift")
    require("CITATION.cff", cff_value("license") == license_id, "current license drift")

    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    urls = project.get("urls", {})
    require("pyproject.toml", project.get("version") == facts["source_branch_package_version"],
            "source branch package version differs from GEO facts")
    require("pyproject.toml", project.get("license") == license_id, "current license drift")
    require("pyproject.toml", urls.get("Homepage") == site, "Homepage URL drift")
    require("pyproject.toml", urls.get("Documentation") == documentation, "Documentation URL drift")
    require("pyproject.toml", urls.get("Repository") == repo, "Repository URL drift")

    for relative in DOC_HOME:
        path = root / relative
        if not path.exists():
            errors.append(f"missing documentation home: {relative}")
            continue
        text = path.read_text(encoding="utf-8")
        require(relative, stable_link in text, "current stable release link missing")
        require(relative, stable_clone in text, "stable install must pin the current release tag")
        require(relative, facts["source_branch"] in text, "development branch not identified")
        if relative == "docs/en_US/README.md":
            version_pattern = rf"^Package release `v{re.escape(version)}` is the current stable release"
        elif relative == "docs/ja_JP/README.md":
            version_pattern = rf"^package `v{re.escape(version)}` が現在の安定版です"
        else:
            version_pattern = rf"^`v{re.escape(version)}` 是当前稳定发行版"
        require(relative, bool(re.search(version_pattern, text, re.M)), "current stable version statement drift")

    current = release["version"]
    package_version = facts["source_branch_package_version"]
    require("docs/geo-facts.json", bool(re.fullmatch(r"v?\d+\.\d+\.\d+", current)), "invalid current release version")
    require("docs/geo-facts.json", tag == f"v{current}", "release tag/version mismatch")
    require("docs/geo-facts.json", bool(re.fullmatch(r"\d+\.\d+\.\d+(?:[a-zA-Z0-9.+!-]+)?", package_version)), "invalid source package version")

    for relative in ("docs/GEO_RELEASE_PROCESS.md", "docs/GEO_EVAL.md"):
        path = root / relative
        if not path.exists():
            errors.append(f"missing GEO document: {relative}")
            continue
        text = path.read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)]+)\)", text):
            if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("#"):
                continue
            destination = (path.parent / target.split("#", 1)[0]).resolve()
            if not destination.exists():
                errors.append(f"{relative}: broken local link {target}")
    return errors


if __name__ == "__main__":
    problems = check()
    print(json.dumps({"passed": not problems, "errors": problems}, ensure_ascii=False))
    raise SystemExit(bool(problems))
