"""Offline resource and sanitizer tests for the packaged GUI research courses."""
from __future__ import annotations

from pathlib import Path
from html.parser import HTMLParser
import re
import tempfile
import unittest
from urllib.parse import unquote, urlsplit
import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from framework_v2 import manual_content
import framework_v2.help_viewer as help_viewer
from framework_v2.help_viewer import HelpDialog, export_manuals, manual_html
from framework_v2.manual_content import CHAPTERS
from PySide6.QtCore import Qt
from PySide6.QtCore import QUrl
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QApplication


class _DocumentResources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.image_sources = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "id" in values:
            self.ids.add(values["id"])
        if "name" in values:
            self.ids.add(values["name"])
        if tag == "img" and "src" in values:
            self.image_sources.append(values["src"])
        if tag == "a" and "href" in values:
            self.links.append(values["href"])


class ManualResearchCourseTests(unittest.TestCase):
    def test_existing_public_anchors_stay_and_two_chapters_are_additive(self):
        self.assertEqual(set(CHAPTERS), {"zh_CN", "ja_JP", "en_US"})
        self.assertTrue(all(len(chapters) == 15 for chapters in CHAPTERS.values()))
        self.assertTrue(all(chapters[0][0] == "start" for chapters in CHAPTERS.values()))
        expected_prefix = ["start", "demo", "connect", "download", "strategy", "language",
                           "market", "realpack", "results", "paper", "records", "trouble", "help"]
        for chapters in CHAPTERS.values():
            self.assertEqual([row[0] for row in chapters[:13]], expected_prefix)
            self.assertEqual([row[0] for row in chapters[13:]], ["indicators", "research-studio"])

    def test_real_localized_courses_load_search_and_render_from_docs_tree(self):
        shared_blocks = []
        for language in ("zh_CN", "ja_JP", "en_US"):
            with self.subTest(language=language):
                sections = manual_content.research_course_sections(language)
                entries = manual_content.research_course_search_entries(language)
                course_html = manual_content.render_research_course(language)
                page_html = manual_html(language)
                self.assertEqual(len(sections), 9)
                self.assertEqual([entry[0] for entry in entries], [item.anchor for item in sections])
                self.assertEqual([item.anchor for item in sections][2:5],
                                 ["course-demo-1", "course-demo-2", "course-demo-3"])
                self.assertEqual([item.anchor for item in sections][6:8],
                                 ["course-demo-4", "course-demo-5"])
                searchable = " ".join(text for _, _, text in entries)
                self.assertIn("4502", searchable)
                self.assertIn("PIT", searchable)
                self.assertIn("EVIDENCE_SUMMARY.md", searchable)
                self.assertNotIn("c245051c1a33cabee8043b23a5f170bc84b5c2ea8e4351b6c6f781291f9cd545", course_html)
                self.assertIn('src="demos/research-20261006/', page_html)
                self.assertNotRegex(page_html, r"(?i)<script|href=[\"'](?:https?:|file:)")
                parser = _DocumentResources(); parser.feed(page_html)
                self.assertTrue(all(f"course-demo-{demo}" in parser.ids for demo in range(1, 6)))
                local_png_links = sum(urlsplit(link).path.lower().endswith(".png") for link in parser.links)
                self.assertGreaterEqual(len(parser.image_sources) + local_png_links, 60)
                blocks = re.findall(r"<pre><code>(.*?)</code></pre>", page_html, re.DOTALL)
                self.assertTrue(blocks)
                shared_blocks.append(blocks[0])
        self.assertEqual(shared_blocks[0], shared_blocks[1])
        self.assertEqual(shared_blocks[1], shared_blocks[2])

    def test_help_dialog_searches_full_course_and_keeps_course_anchor_on_locale_change(self):
        app = QApplication.instance() or QApplication([])
        dialog = HelpDialog("en_US")
        try:
            app.processEvents()
            image = dialog.browser.document().resource(
                QTextDocument.ResourceType.ImageResource,
                QUrl("demos/research-20261006/en_US/cache-selection.png"),
            )
            self.assertIsNotNone(image)
            self.assertFalse(image.isNull())
            dialog.search.setText("credential_missing")
            matches = [dialog.contents.item(i) for i in range(dialog.contents.count())]
            course = next(item for item in matches
                          if item.data(Qt.ItemDataRole.UserRole) == "course-demo-5")
            self.assertTrue(course.text())
            dialog._select(course)
            self.assertEqual(dialog.chapter, "course-demo-5")
            dialog.set_language("ja_JP")
            self.assertEqual(dialog.chapter, "course-demo-5")
            self.assertIn("credential_missing", dialog.browser.toPlainText())
            dialog.search.setText("")
            self.assertEqual(dialog.contents.count(), len(CHAPTERS["ja_JP"]) + 9)
        finally:
            dialog.close(); app.processEvents()

    def test_html_exports_resolve_packaged_images_and_all_local_anchors(self):
        candidate_root = Path(__file__).resolve().parents[2]
        package_root = manual_content.PACKAGE_DOCS_ROOT.resolve()
        temp_parent = Path(tempfile.gettempdir()).resolve()
        public_logo = candidate_root / "framework_v2" / "assets" / "brand" / "logo-horizontal-dark.png"
        with tempfile.TemporaryDirectory(dir=temp_parent, prefix="manual-course-export-") as tmp:
            output_dir = Path(tmp).resolve()
            with patch("framework_v2.help_viewer.os.path.relpath",
                       side_effect=ValueError("simulated different filesystem volumes")):
                exports = export_manuals(output_dir)
            self.assertEqual(len(exports), 3)
            for html_file in exports:
                parser = _DocumentResources()
                source = html_file.read_text(encoding="utf-8")
                parser.feed(source)
                self.assertIn("course-demo-5", parser.ids)
                self.assertTrue(parser.image_sources)
                for link in parser.links:
                    parsed = urlsplit(link)
                    self.assertFalse(parsed.scheme or parsed.netloc)
                    if link.startswith("#"):
                        self.assertIn(parsed.fragment, parser.ids)
                    else:
                        self.assertNotIn("..", Path(unquote(parsed.path)).parts)
                        target = (output_dir / unquote(parsed.path)).resolve(strict=True)
                        self.assertTrue(target.is_file())
                        self.assertTrue(target.is_relative_to(output_dir))
                for source_url in parser.image_sources:
                    parsed = urlsplit(source_url)
                    self.assertFalse(parsed.scheme or parsed.netloc or parsed.query or parsed.fragment)
                    target = (output_dir / unquote(parsed.path)).resolve(strict=True)
                    self.assertNotIn("..", Path(unquote(parsed.path)).parts)
                    self.assertTrue(target.is_file())
                    self.assertTrue(target.is_relative_to(output_dir))
                    relative = Path(unquote(parsed.path))
                    if relative.as_posix().startswith("demos/"):
                        original = package_root / relative
                    else:
                        self.assertEqual(relative.as_posix(), "assets/brand/logo-horizontal-dark.png")
                        original = public_logo
                    self.assertEqual(target.read_bytes(), original.read_bytes())

    def test_export_asset_copy_rejects_unapproved_source(self):
        package_root = manual_content.PACKAGE_DOCS_ROOT.resolve()
        temp_parent = Path(tempfile.gettempdir()).resolve()
        with tempfile.TemporaryDirectory(dir=temp_parent, prefix="manual-export-path-guard-") as tmp:
            source = Path(tmp) / "outside.png"
            source.write_bytes(b"not a packaged manual asset")
            export = Path(tmp) / "export"
            export.mkdir()
            with self.assertRaises(ValueError):
                help_viewer._copy_asset_for_export(source, export)
            packaged = package_root / "demos" / "research-20261006" / "en_US" / "cache-selection.png"
            relative = packaged.relative_to(package_root)
            conflict = export / relative
            conflict.parent.mkdir(parents=True)
            conflict.write_bytes(b"pre-existing conflicting content")
            with self.assertRaises(ValueError):
                help_viewer._copy_asset_for_export(packaged, export)
            self.assertEqual(conflict.read_bytes(), b"pre-existing conflicting content")

    def test_language_path_is_allowlisted_and_bad_images_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "docs"
            locale = root / "zh_CN"
            images = root / "demos" / "research-20261006" / "zh_CN"
            locale.mkdir(parents=True)
            images.mkdir(parents=True)
            (images / "ok.png").write_bytes(b"fixture-png")
            (Path(tmp) / "outside.png").write_bytes(b"outside")
            headings = [
                "Input", "Start", "Demo 1: price", "Demo 2: factors", "Demo 3: models",
                "Results", "Demo 4: paper", "Demo 5: broker", "Evidence",
            ]

            def write_course(first_body: str) -> None:
                lines = ["# Course", "", "Overview", ""]
                for index, heading in enumerate(headings):
                    lines.extend([f"## {heading}", first_body if index == 0 else "Course body", ""])
                (locale / manual_content._COURSE_FILE).write_text("\n".join(lines), encoding="utf-8")

            write_course("Image ![ok](../demos/research-20261006/zh_CN/ok.png) and <script>bad</script>.")
            parsed = manual_content._load_course_sections("zh_CN", root)
            self.assertIn("&lt;script&gt;bad&lt;/script&gt;", parsed[0].html)
            self.assertIn('src="demos/research-20261006/zh_CN/ok.png"', parsed[0].html)

            write_course("![escape](../../outside.png)")
            with self.assertRaises(ValueError):
                manual_content._load_course_sections("zh_CN", root)

            write_course("[external](https://example.invalid/)")
            with self.assertRaises(ValueError):
                manual_content._load_course_sections("zh_CN", root)

    def test_untrusted_html_is_escaped_and_only_internal_fragments_link(self):
        root = Path(__file__).resolve().parents[2] / "docs"
        html = manual_content._render_markdown_blocks(
            '<img src=x onerror="alert(1)"> [section](#course-demo-1)',
            root / "zh_CN", root,
        )
        self.assertIn("&lt;img src=x onerror=", html)
        self.assertIn('href="#course-demo-1"', html)
        self.assertNotIn("onerror=\"alert", html)


if __name__ == "__main__":
    unittest.main()
