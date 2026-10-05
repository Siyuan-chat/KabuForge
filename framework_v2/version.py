"""Resolve the version for this exact source tree or owning distribution."""
from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class VersionInfo:
    version: str
    distribution: str
    source: str
    identity: str


def _source_project(module_path: Path) -> VersionInfo | None:
    """Read project metadata only when this file belongs to that project tree."""
    for root in module_path.parents:
        if (root / "framework_v2" / "version.py").resolve(strict=False) != module_path:
            continue
        project_file = root / "pyproject.toml"
        if not project_file.is_file():
            continue
        with project_file.open("rb") as stream:
            document = tomllib.load(stream)
        project = document.get("project")
        if not isinstance(project, dict):
            raise RuntimeError(f"Project metadata is missing in {project_file}")
        name, version = project.get("name"), project.get("version")
        if not isinstance(name, str) or not name.strip() or not isinstance(version, str) or not version.strip():
            raise RuntimeError(f"Project name/version is invalid in {project_file}")
        return VersionInfo(version=version, distribution=name, source="pyproject",
                           identity=str(project_file.resolve()))
    return None


def _installed_distribution(module_path: Path) -> VersionInfo:
    """Resolve installed metadata by file ownership instead of distribution name."""
    matches: dict[tuple[str, str], VersionInfo] = {}
    for dist in metadata.distributions():
        for entry in dist.files or ():
            if str(entry).replace("\\", "/") != "framework_v2/version.py":
                continue
            try:
                owned_path = Path(dist.locate_file(entry)).resolve(strict=False)
            except (OSError, RuntimeError, TypeError):
                continue
            if owned_path != module_path:
                continue
            name, version = dist.metadata.get("Name"), dist.version
            if not isinstance(name, str) or not name.strip() or not isinstance(version, str) or not version.strip():
                continue
            info = VersionInfo(version=version, distribution=name, source="distribution-metadata",
                               identity=f"{name}=={version}")
            matches[(name.casefold(), version)] = info
    if len(matches) != 1:
        raise RuntimeError("Could not identify one installed distribution owning framework_v2/version.py")
    return next(iter(matches.values()))


def get_version_info(module_file: str | Path | None = None) -> VersionInfo:
    """Return metadata for this module's source project or owning distribution."""
    module_path = Path(module_file if module_file is not None else __file__).expanduser().resolve(strict=False)
    source_info = _source_project(module_path)
    return source_info if source_info is not None else _installed_distribution(module_path)


def get_version() -> str:
    """Return this installation's application version."""
    return get_version_info().version
