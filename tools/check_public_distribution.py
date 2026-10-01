"""Fail closed when a KabuForge source tree, wheel, or sdist crosses its public boundary."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile
import zipfile


PRIVATE_TOP_LEVEL = {
    "historical_data.py", "topix_pool_runtime.py", "fundamental_factor_runtime.py",
    "dual_ma_factor_runtime.py", "residual_momentum_factor_runtime.py",
    "reversal_factor_runtime.py", "attention_factor_runtime.py", "behaviour_factor_runtime.py",
}
FORBIDDEN_PARTS = {
    ".git", ".aws", ".codex", "__pycache__", "build", "dist", "output",
    "secrets", "credentials", "keys",
}
SECRET_PATTERNS = (
    re.compile(r"\b(?:ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|secret|password)\s*[:=]\s*['\"][A-Za-z0-9_-]{24,}['\"]"),
)


class DistributionError(ValueError):
    pass


def _source_files(root: Path) -> dict[str, bytes]:
    if (root / ".git").is_dir():
        listed = subprocess.run(
            ["git", "-c", "safe.directory="+root.resolve().as_posix(), "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard"],
            check=False, capture_output=True, text=True,
        )
        if listed.returncode == 0:
            paths = [root / item for item in listed.stdout.splitlines()]
            return {
                path.relative_to(root).as_posix(): path.read_bytes()
                for path in paths if path.is_file()
            }
        raise DistributionError("Git source inventory unavailable")
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(root).parts
    }


def _archive_files(path: Path) -> dict[str, bytes]:
    if path.suffix == ".whl" or zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            files = {name: archive.read(name) for name in archive.namelist() if not name.endswith("/")}
            return files
    if path.suffixes[-2:] == [".tar", ".gz"] or path.suffix in {".tgz", ".tar"}:
        with tarfile.open(path) as archive:
            files = {
                item.name: archive.extractfile(item).read()
                for item in archive.getmembers() if item.isfile() and archive.extractfile(item) is not None
            }
            roots = {PurePosixPath(name).parts[0] for name in files if PurePosixPath(name).parts}
            if len(roots) == 1:
                return {"/".join(PurePosixPath(name).parts[1:]): data for name, data in files.items()}
            return files
    raise DistributionError("target must be a source directory, wheel, or sdist")


def _find(files: dict[str, bytes], logical_path: str) -> tuple[str, bytes] | None:
    exact = files.get(logical_path)
    if exact is not None:
        return logical_path, exact
    matches = [(path, data) for path, data in files.items() if path.endswith("/" + logical_path)]
    if len(matches) == 1:
        return matches[0]
    return None


def _metadata(files: dict[str, bytes]) -> str:
    candidates = [data for path, data in files.items() if path == "pyproject.toml" or path.endswith("/pyproject.toml")]
    candidates += [data for path, data in files.items() if path.endswith(".dist-info/METADATA")]
    return b"\n".join(candidates).decode("utf-8", "replace")


def _hash(raw: bytes, normalization: str | None) -> str:
    if normalization is None:
        payload = raw  # Compatibility with manifests created before LF normalization.
    elif normalization == "LF":
        payload = raw.replace(b"\r\n", b"\n")
    else:
        raise DistributionError("unknown manifest hash_normalization")
    return hashlib.sha256(payload).hexdigest()


def inspect_distribution(target: str | Path) -> list[dict[str, str]]:
    path = Path(target)
    files = _source_files(path) if path.is_dir() else _archive_files(path)
    findings: list[dict[str, str]] = []
    manifest_item = _find(files, "public_source_manifest.json")
    if manifest_item is None:
        findings.append({"category": "manifest", "path": "public_source_manifest.json"})
    else:
        try:
            manifest = json.loads(manifest_item[1])
            hashes = manifest["source_hashes"]
            if not isinstance(manifest.get("baseline_commit"), str) or not isinstance(hashes, dict):
                raise ValueError
            normalization = manifest.get("hash_normalization")
            if normalization is not None and not isinstance(normalization, str):
                raise ValueError
            _hash(b"", normalization)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            findings.append({"category": "manifest", "path": manifest_item[0]})
        except DistributionError:
            findings.append({"category": "hash_normalization", "path": manifest_item[0]})
        else:
            for logical_path, expected in sorted(hashes.items()):
                source = _find(files, logical_path)
                if source is None or _hash(source[1], normalization) != expected:
                    findings.append({"category": "manifest_hash", "path": logical_path})
    metadata = _metadata(files)
    if re.search(r"(?im)^Name:\s*kabuforge-local\s*$|name\s*=\s*['\"]kabuforge-local['\"]", metadata):
        findings.append({"category": "metadata_name", "path": "package metadata"})
    elif not re.search(r"(?im)^Name:\s*kabuforge\s*$|name\s*=\s*['\"]kabuforge['\"]", metadata):
        findings.append({"category": "metadata_name", "path": "package metadata"})
    if "Private :: Do Not Upload" in metadata:
        findings.append({"category": "metadata_classifier", "path": "package metadata"})
    for member, raw in files.items():
        parts = PurePosixPath(member).parts
        basename = parts[-1] if parts else ""
        if len(parts) == 1 and basename in PRIVATE_TOP_LEVEL:
            findings.append({"category": "private_runtime", "path": member})
        if any(part.lower() in FORBIDDEN_PARTS for part in parts) or basename.lower() in {".env", ".env.local"}:
            findings.append({"category": "generated_or_secret_path", "path": member})
        if basename.endswith((".py", ".json", ".toml", ".yml", ".yaml", ".ini")) and not any(part in {"docs", "tests"} for part in parts):
            text = raw.decode("utf-8", "ignore")
            if any(pattern.search(text) for pattern in SECRET_PATTERNS):
                findings.append({"category": "credential_literal", "path": member})
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", default=".", help="source directory, wheel, or sdist")
    args = parser.parse_args(argv)
    findings = inspect_distribution(args.target)
    print(json.dumps({"ok": not findings, "findings": findings}, ensure_ascii=False))
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
