from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from framework_v2.version import get_version, get_version_info


class _FixtureDistribution:
    """Explicit isolated metadata fixture for installed-package ownership tests."""

    def __init__(self, root: Path, name: str, version: str, files=()):
        self.root = root
        self.metadata = {"Name": name}
        self.version = version
        self.files = files

    def locate_file(self, entry):
        return self.root / Path(str(entry))


class VersionTests(unittest.TestCase):
    def test_source_version_comes_from_candidate_project_not_current_directory(self):
        info = get_version_info()
        source_file = Path(__file__).resolve().parents[1] / "version.py"
        candidate_root = Path(__file__).resolve().parents[2]
        with (candidate_root / "pyproject.toml").open("rb") as stream:
            project = tomllib.load(stream)["project"]
        self.assertEqual(info.source, "pyproject")
        self.assertEqual(info.version, project["version"])
        self.assertEqual(info.distribution, project["name"])
        self.assertEqual(Path(info.identity), candidate_root / "pyproject.toml")
        self.assertEqual(Path(get_version_info.__code__.co_filename).resolve(), source_file)
        expected = get_version()
        with tempfile.TemporaryDirectory() as directory:
            other = Path(directory) / "pyproject.toml"
            other.write_text('[project]\nname="unrelated-fixture"\nversion="99.99"\n', encoding="utf-8")
            original = Path.cwd()
            try:
                os.chdir(directory)
                self.assertEqual(get_version(), expected)
            finally:
                os.chdir(original)

    def test_installed_version_uses_distribution_owning_exact_module_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = root / "site-packages"
            module_file = site / "framework_v2" / "version.py"
            module_file.parent.mkdir(parents=True)
            module_file.write_text("# isolated installed-package fixture\n", encoding="utf-8")
            # A parent project and a different distribution with the same RECORD path do not own this file.
            (root / "pyproject.toml").write_text(
                '[project]\nname="unrelated-parent-fixture"\nversion="98.0"\n', encoding="utf-8")
            unrelated = _FixtureDistribution(root / "other-site", "unrelated-dist-fixture", "97.0",
                                             files=(Path("framework_v2/version.py"),))
            owner = _FixtureDistribution(site, "owner-dist-fixture", "2.3.4",
                                         files=(Path("framework_v2/version.py"),))
            with patch("framework_v2.version.metadata.distributions", return_value=[unrelated, owner]):
                info = get_version_info(module_file)
            self.assertEqual((info.source, info.distribution, info.version),
                             ("distribution-metadata", "owner-dist-fixture", "2.3.4"))

    def test_package_cli_doctor_and_mcp_initialize_share_candidate_version(self):
        candidate_src = str(Path(__file__).resolve().parents[2] / "src")
        self.assertTrue(candidate_src.replace("\\", "/").endswith("publish-rc2-20261004/src"))
        sys.path.insert(0, candidate_src)
        try:
            import kabuforge
            from kabuforge.cli import _main
            from framework_v2.agent.mcp import MCPAdapter

            expected = get_version()
            self.assertEqual(kabuforge.__file__ and Path(kabuforge.__file__).resolve().parent,
                             Path(candidate_src).resolve() / "kabuforge")
            self.assertEqual(kabuforge.__version__, expected)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                _main(["doctor"])
            self.assertEqual(json.loads(output.getvalue())["version"], expected)

            adapter = object.__new__(MCPAdapter)
            adapter.service = object()
            adapter.expose_reserved_external = False
            response = adapter.request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
            self.assertEqual(response["result"]["serverInfo"]["version"], expected)
        finally:
            sys.path.remove(candidate_src)


if __name__ == "__main__":
    unittest.main()
