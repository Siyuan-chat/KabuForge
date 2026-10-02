"""Regression fixtures for the artifact-level extension tutorial check."""
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "check_sdist_tutorial", ROOT / "tools/check_sdist_tutorial.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class SdistTutorialCheckTests(unittest.TestCase):
    def write_archive(self, root, *, omit=(), extra=()):
        path = root / "tutorial.tar.gz"
        with tarfile.open(path, "w:gz") as archive:
            for name in checker.REQUIRED_FILES:
                if name in omit:
                    continue
                member = tarfile.TarInfo("kabuforge-test/" + name)
                member.size = len(b"fixture\n")
                archive.addfile(member, io.BytesIO(b"fixture\n"))
            for member, content in extra:
                archive.addfile(member, io.BytesIO(content) if content is not None else None)
        return path

    def test_complete_archive_extracts_its_own_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            extracted = checker.extract_sdist(self.write_archive(root), root / "unpacked")
            for name in checker.REQUIRED_FILES:
                self.assertEqual((extracted / name).read_bytes(), b"fixture\n")

    def test_each_required_file_is_checked_in_archive_not_checkout(self):
        for name in checker.REQUIRED_FILES:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                with patch.object(checker.subprocess, "run") as run:
                    with self.assertRaisesRegex(ValueError, "missing required"):
                        checker.check_sdist(self.write_archive(Path(temp), omit=(name,)))
                    run.assert_not_called()

    def test_empty_required_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            name = checker.REQUIRED_FILES[0]
            member = tarfile.TarInfo("kabuforge-test/" + name)
            archive = self.write_archive(Path(temp), omit=(name,), extra=((member, b""),))
            with self.assertRaisesRegex(ValueError, "missing required"):
                checker.extract_sdist(archive, Path(temp) / "unpacked")

    def test_unsafe_paths_are_rejected_before_extraction(self):
        for name in ("../escape", "/absolute", "kabuforge-test/../escape",
                     "C:/escape", "kabuforge-test\\escape"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                archive = self.write_archive(root, extra=((tarfile.TarInfo(name), b""),))
                with self.assertRaisesRegex(ValueError, "unsafe"):
                    checker.extract_sdist(archive, root / "unpacked")
                self.assertFalse((root / "unpacked").exists())

    def test_links_and_special_files_are_rejected(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                member = tarfile.TarInfo("kabuforge-test/link")
                member.type = kind
                member.linkname = "examples/extension_demo.py"
                archive = self.write_archive(Path(temp), extra=((member, None),))
                with self.assertRaisesRegex(ValueError, "links/special"):
                    checker.extract_sdist(archive, Path(temp) / "unpacked")

    def test_duplicate_paths_and_multiple_roots_are_rejected(self):
        for name, message in (("kabuforge-test/" + checker.REQUIRED_FILES[0], "duplicate"),
                              ("other-root/file", "top-level")):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                archive = self.write_archive(Path(temp), extra=((tarfile.TarInfo(name), b""),))
                with self.assertRaisesRegex(ValueError, message):
                    checker.extract_sdist(archive, Path(temp) / "unpacked")

    def test_empty_archive_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = self.write_archive(Path(temp), omit=checker.REQUIRED_FILES)
            with self.assertRaisesRegex(ValueError, "top-level"):
                checker.extract_sdist(archive, Path(temp) / "unpacked")

    def test_check_uses_extracted_cwd_and_isolated_installed_python(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = self.write_archive(Path(temp))
            demo_output = json.dumps({"synthetic": True, "orders_submitted": False,
                                      "planned_order_count": 1})
            completed = subprocess.CompletedProcess([], 0, stdout=demo_output)
            with patch.dict(os.environ, {"PYTHONPATH": str(ROOT), "PYTHONHOME": "bad"}):
                with patch.object(checker.subprocess, "run", return_value=completed) as run:
                    report = checker.check_sdist(archive)
            self.assertEqual(report["tutorial_tests"], "passed")
            self.assertEqual(run.call_count, 3)
            for call in run.call_args_list:
                self.assertEqual(call.args[0][:2], [checker.sys.executable, "-I"])
                self.assertEqual(call.kwargs["cwd"].name, "kabuforge-test")
                self.assertNotEqual(call.kwargs["cwd"], ROOT)
                self.assertNotIn("PYTHONPATH", call.kwargs["env"])
                self.assertNotIn("PYTHONHOME", call.kwargs["env"])
                self.assertTrue(call.kwargs["check"])
            self.assertIn("test_extension_example.py", run.call_args_list[-1].args[0])
            self.assertFalse(run.call_args.kwargs["cwd"].exists())

    def test_failed_tutorial_tests_propagate(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = self.write_archive(Path(temp))
            passed = subprocess.CompletedProcess([], 0, stdout=json.dumps(
                {"synthetic": True, "orders_submitted": False, "planned_order_count": 1}))
            with patch.object(checker.subprocess, "run", side_effect=[
                passed, passed, subprocess.CalledProcessError(1, ["unittest"])
            ]):
                with self.assertRaises(subprocess.CalledProcessError):
                    checker.check_sdist(archive)

    def test_invalid_demo_output_fails_before_tests(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = self.write_archive(Path(temp))
            output = subprocess.CompletedProcess([], 0, stdout=json.dumps(
                {"synthetic": True, "orders_submitted": True, "planned_order_count": 1}))
            with patch.object(checker.subprocess, "run", return_value=output) as run:
                with self.assertRaisesRegex(ValueError, "unexpected"):
                    checker.check_sdist(archive)
                self.assertEqual(run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
