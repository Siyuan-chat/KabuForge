"""Negative fixtures for homepage links, language and licensing checks."""
from pathlib import Path
import importlib.util
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('check_docs', ROOT/'tools/check_docs.py')
docs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(docs)


class DocumentationContractTests(unittest.TestCase):
    def test_broken_link_and_anchor(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); file=root/'README.md'
            file.write_text('# Title\n[broken](missing.md)\n[anchor](#absent)',encoding='utf-8')
            errors=docs.local_links(root,file)
            self.assertTrue(any('broken link' in e for e in errors))
            self.assertTrue(any('missing anchor' in e for e in errors))

    def test_html_media_and_explicit_anchor(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); file=root/'README.md'
            file.write_text('<a id="start"></a>\n[ok](#start)\n<img src="absent.svg">',encoding='utf-8')
            self.assertEqual(docs.local_links(root,file),['broken link: README.md absent.svg'])

    def test_wrong_language_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); text=(ROOT/'README.md').read_text(encoding='utf-8')
            for path in docs.HOMEPAGES: (root/path).write_text(text,encoding='utf-8')
            self.assertEqual(docs.check_homepages(root),[])
            (root/'README.md').write_text(text.replace('](README.ja_JP.md)','](README.ja.md)'),encoding='utf-8')
            self.assertTrue(any('language entry mismatch' in e for e in docs.check_homepages(root)))

    def test_wrong_license_identifier(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            paths=['pyproject.toml','CITATION.cff','LICENSE','NOTICE']
            paths += [f'docs/{locale}/{name}.md' for locale in docs.LOCALES for name in ('DEVELOPMENT','CONTRIBUTING')]
            for path in paths:
                target=root/path; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes((ROOT/path).read_bytes())
            self.assertEqual(docs.check_license(root),[])
            path=root/'pyproject.toml'
            path.write_text(path.read_text(encoding='utf-8').replace('license = "AGPL-3.0-only"','license = "AGPL-3.0-or-later"'),encoding='utf-8')
            self.assertIn('license metadata mismatch: pyproject.toml',docs.check_license(root))

    def test_formal_docs_and_mirrors(self):
        self.assertEqual(docs.check(ROOT),[])
