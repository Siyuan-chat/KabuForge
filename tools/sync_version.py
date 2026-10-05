"""Synchronize generated homepage version blocks from pyproject.toml."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import tomllib


START = "<!-- KABUFORGE:VERSION:START -->"
END = "<!-- KABUFORGE:VERSION:END -->"
HOMEPAGES = {
    "README.md": "en_US",
    "README.zh_CN.md": "zh_CN",
    "README.ja_JP.md": "ja_JP",
}
SITE_VERSION_FILE = Path("website/src/data/version.json")
SITE_PAGES_FILE = Path("website/src/data/pages.json")
SITE_ASTRO_FILES = {
    Path("website/src/pages/index.astro"): "../data/version.json",
    Path("website/src/pages/ja/index.astro"): "../../data/version.json",
}
SITE_PAGE_MARKERS = ("QUICKSTART_EN", "QUICKSTART_JA", "RELEASES_EN", "RELEASES_JA")


def project_version(root: Path) -> str:
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    version = data.get("project", {}).get("version")
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9A-Za-z]+)+(?:[-+][0-9A-Za-z.-]+)?", version):
        raise ValueError("pyproject.toml must contain a valid project.version")
    return version


def version_block(locale: str, version: str) -> str:
    if locale == "zh_CN":
        status = (f"当前包版本为 **{version}**。这是候选元数据，不表示该版本已发布。"
                 "本项目用于研究与本地模拟；真实终端连通性尚未验证，真实订单提交与撤销保持禁用。")
    elif locale == "ja_JP":
        status = (f"現在のパッケージ版は **{version}** です。この候補メタデータは公開済みリリースを意味しません。"
                  "研究とローカルシミュレーション用です。実端末の接続は未検証で、実注文の submit と cancel は無効です。")
    else:
        status = (f"Current package version: **{version}**. This candidate metadata does not mean the version has been released. "
                  "Research and local simulation only; actual terminal connectivity is unverified, and real order submission/cancel remain disabled.")
    badge = f"[![Package](https://img.shields.io/badge/package-{version}-E65324)](https://github.com/Siyuan-chat/KabuForge/releases)"
    return f"{START}\n{status}\n\n{badge}\n{END}"


def check_version_sync(root: Path) -> list[str]:
    version = project_version(root)
    errors = []
    for name, locale in HOMEPAGES.items():
        path = root / name
        text = path.read_text(encoding="utf-8")
        pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)
        matches = list(pattern.finditer(text))
        if len(matches) != 1:
            errors.append(f"{name}: expected exactly one generated version block")
            continue
        if matches[0].group(0) != version_block(locale, version):
            errors.append(f"{name}: generated version block differs from pyproject.toml {version}")
    errors.extend(check_site_version_sync(root, version))
    return errors


def _page_marker_block(name: str, version: str) -> str:
    return (f"<!-- KABUFORGE:VERSION:{name}:START -->{version}"
            f"<!-- KABUFORGE:VERSION:{name}:END -->")


def _replace_page_markers(text: str, version: str, *, check: bool) -> tuple[str, list[str]]:
    errors = []
    for name in SITE_PAGE_MARKERS:
        start = f"<!-- KABUFORGE:VERSION:{name}:START -->"
        end = f"<!-- KABUFORGE:VERSION:{name}:END -->"
        pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
        matches = list(pattern.finditer(text))
        if len(matches) != 1:
            errors.append(f"pages.json: expected exactly one {name} version marker")
            continue
        expected = _page_marker_block(name, version)
        if check:
            if matches[0].group(0) != expected:
                errors.append(f"pages.json: {name} version marker differs from pyproject.toml {version}")
        else:
            text = pattern.sub(lambda _match, block=expected: block, text)
    return text, errors


def _version_json(version: str) -> dict[str, str]:
    return {"version": version, "release_status": "UNPUBLISHED"}


def check_site_version_sync(root: Path, version: str) -> list[str]:
    errors = []
    version_path = root / SITE_VERSION_FILE
    try:
        actual = json.loads(version_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{SITE_VERSION_FILE.as_posix()}: invalid version data: {exc}"]
    if actual != _version_json(version):
        errors.append(f"{SITE_VERSION_FILE.as_posix()}: version data differs from pyproject.toml {version}")
    pages_path = root / SITE_PAGES_FILE
    try:
        pages_text = pages_path.read_text(encoding="utf-8")
        json.loads(pages_text)
        _, marker_errors = _replace_page_markers(pages_text, version, check=True)
        errors.extend(marker_errors)
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{SITE_PAGES_FILE.as_posix()}: invalid page data: {exc}")
    for path, import_path in SITE_ASTRO_FILES.items():
        try:
            source = (root / path).read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"{path.as_posix()}: cannot read homepage: {exc}")
            continue
        if f"import versionInfo from '{import_path}'" not in source:
            errors.append(f"{path.as_posix()}: missing dynamic version import")
        if "{versionInfo.version}" not in source or "{versionInfo.release_status}" not in source:
            errors.append(f"{path.as_posix()}: missing dynamic version and release status")
    return errors


def _prepare_site_sync(root: Path, version: str) -> tuple[Path, str]:
    pages_path = root / SITE_PAGES_FILE
    pages_text = pages_path.read_text(encoding="utf-8")
    pages_text, errors = _replace_page_markers(pages_text, version, check=False)
    if errors:
        raise ValueError("; ".join(errors))
    json.loads(pages_text)
    return pages_path, pages_text


def sync(root: Path) -> None:
    version = project_version(root)
    homepage_updates = {}
    for name, locale in HOMEPAGES.items():
        path = root / name
        text = path.read_text(encoding="utf-8")
        pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)
        if len(list(pattern.finditer(text))) != 1:
            raise ValueError(f"{name}: expected exactly one generated version block")
        homepage_updates[path] = pattern.sub(lambda _match: version_block(locale, version), text)
    pages_path, pages_text = _prepare_site_sync(root, version)
    # Validate every source before writing any generated file.
    for path, text in homepage_updates.items():
        path.write_text(text, encoding="utf-8", newline="\n")
    pages_path.write_text(pages_text, encoding="utf-8", newline="\n")
    (root / SITE_VERSION_FILE).write_text(
        json.dumps(_version_json(version), indent=2) + "\n", encoding="utf-8", newline="\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="check homepage blocks without writing files")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.check:
        errors = check_version_sync(root)
        if errors:
            for error in errors:
                print(error)
            return 1
        print(f"homepage version blocks match pyproject.toml ({project_version(root)})")
        return 0
    sync(root)
    print(f"synchronized homepage version blocks from pyproject.toml ({project_version(root)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
