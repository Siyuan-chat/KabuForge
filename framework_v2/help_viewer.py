"""Searchable offline help with stable chapter anchors and HTML export."""
from __future__ import annotations

from html import escape
import os
from pathlib import Path
import re
import shutil
from urllib.parse import quote, unquote, urlsplit

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QSplitter, QLineEdit, QListWidget,
    QListWidgetItem, QTextBrowser, QPushButton,
)

from .brand_theme import DARK
from .i18n import LANGUAGES, tr
from .manual_content import (
    CHAPTERS, PACKAGE_DOCS_ROOT, render_research_course,
    research_course_search_entries, research_course_sections,
)


_TITLES = {
    "zh_CN": "KabuForge 操作手册",
    "ja_JP": "KabuForge 操作マニュアル",
    "en_US": "KabuForge User Guide",
}
_LOGO_PATH = Path(__file__).resolve().parent / "assets" / "brand" / "logo-horizontal-dark.png"
_COURSE_ASSET_ATTR = re.compile(r'(?P<attribute>src|href)="(?P<url>demos/[^\"]+)"')


def _validate_language(language: str) -> str:
    if language not in CHAPTERS:
        raise ValueError(f"unsupported manual language: {language}")
    return language


def _relative_asset_url(target: Path, output_dir: Path) -> str:
    """Return a safe relative URL for packaged or copied manual assets."""
    docs_root = PACKAGE_DOCS_ROOT.resolve(strict=True)
    resolved = target.resolve(strict=True)
    image_root = (docs_root / "demos" / "research-20261006").resolve(strict=True)
    output_root = output_dir.resolve(strict=True)
    if resolved.is_relative_to(output_root):
        relative = resolved.relative_to(output_root)
        relative_posix = relative.as_posix()
        if not (
            (relative_posix.startswith("demos/research-20261006/")
             and resolved.suffix.lower() == ".png")
            or relative_posix == "assets/brand/logo-horizontal-dark.png"
        ):
            raise ValueError("manual export asset is outside the allowed resource paths")
        return quote(relative_posix, safe="/._-")
    if not (resolved.is_relative_to(image_root) or resolved == _LOGO_PATH.resolve(strict=True)):
        raise ValueError("manual asset escapes the packaged documentation resources")
    try:
        relative = os.path.relpath(resolved, output_root)
    except ValueError as exc:
        raise ValueError("packaged manual assets must be copied before cross-volume export") from exc
    return quote(Path(relative).as_posix(), safe="/._-")


def _is_reparse_point(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)())


def _copy_asset_for_export(source: Path, output_dir: Path) -> Path:
    """Copy one allowlisted package asset below an export root without path traversal."""
    docs_root = PACKAGE_DOCS_ROOT.resolve(strict=True)
    image_root = (docs_root / "demos" / "research-20261006").resolve(strict=True)
    resolved_source = source.resolve(strict=True)
    if resolved_source.is_relative_to(image_root) and resolved_source.suffix.lower() == ".png":
        relative = resolved_source.relative_to(docs_root)
    elif resolved_source == _LOGO_PATH.resolve(strict=True):
        relative = Path("assets") / "brand" / _LOGO_PATH.name
    else:
        raise ValueError("manual asset escapes the packaged documentation resources")

    root = output_dir.resolve(strict=True)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("manual export asset has an unsafe relative path")
    destination = root / relative
    cursor = root
    for part in relative.parts[:-1]:
        cursor = cursor / part
        if _is_reparse_point(cursor):
            raise ValueError("manual export may not write through a symlink or junction")
        if cursor.exists():
            if not cursor.is_dir() or not cursor.resolve(strict=True).is_relative_to(root):
                raise ValueError("manual export directory escapes the selected output root")
        else:
            cursor.mkdir()
    if _is_reparse_point(destination):
        raise ValueError("manual export may not overwrite a symlink or junction")
    if destination.exists():
        if not destination.is_file() or not destination.resolve(strict=True).is_relative_to(root):
            raise ValueError("manual export asset destination is not a contained file")
        if destination.read_bytes() != resolved_source.read_bytes():
            raise ValueError("manual export contains a conflicting asset; choose a new output directory")
    else:
        if not destination.parent.resolve(strict=True).is_relative_to(root):
            raise ValueError("manual export asset destination escapes the selected output root")
    if not destination.exists() and resolved_source != destination.resolve(strict=False):
        shutil.copyfile(resolved_source, destination)
    copied = destination.resolve(strict=True)
    if not copied.is_relative_to(root) or copied.read_bytes() != resolved_source.read_bytes():
        raise ValueError("manual export asset copy did not preserve the packaged resource")
    return copied


def _relocate_course_assets(fragment: str, output_dir: Path) -> str:
    """Rebase already-sanitized package-root URLs for an exported HTML file."""
    docs_root = PACKAGE_DOCS_ROOT.resolve(strict=True)

    def replace(match: re.Match[str]) -> str:
        url = unquote(match.group("url"))
        parsed = urlsplit(url)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("course HTML may not load external assets")
        target = (docs_root / parsed.path).resolve(strict=True)
        image_root = (docs_root / "demos" / "research-20261006").resolve(strict=True)
        if not target.is_relative_to(image_root) or target.suffix.lower() != ".png":
            raise ValueError("course HTML asset is outside the packaged PNG tree")
        if output_dir.resolve(strict=True) != docs_root:
            target = _copy_asset_for_export(target, output_dir)
        safe_url = _relative_asset_url(target, output_dir)
        return f'{match.group("attribute")}="{escape(safe_url, quote=True)}"'

    return _COURSE_ASSET_ATTR.sub(replace, fragment)


def manual_html(language: str, output_dir: str | Path | None = None) -> str:
    """Render the offline manual and packaged course images for an HTML base."""
    language = _validate_language(language)
    docs_root = PACKAGE_DOCS_ROOT.resolve(strict=True)
    asset_base = Path(output_dir).resolve(strict=True) if output_dir is not None else docs_root
    chapters = CHAPTERS[language]
    course_sections = research_course_sections(language)
    course_html = _relocate_course_assets(render_research_course(language), asset_base)
    title = escape(_TITLES[language])
    names = {row[0]: row[1] for row in chapters}
    toc_items = [
        f'<li><a href="#{escape(key, quote=True)}">{escape(heading)}</a></li>'
        for key, heading, *_ in chapters
    ]
    toc_items.extend(
        f'<li class="course-entry"><a href="#{escape(item.anchor, quote=True)}">'
        f'{escape(item.heading)}</a></li>' for item in course_sections
    )
    toc = "".join(toc_items)
    sections = []
    for key, heading, *body in chapters:
        paragraphs = [line for line in body if not line.startswith("next:")]
        next_marker = next((line for line in body if line.startswith("next:")), None)
        next_key = next_marker.split(":", 1)[1] if next_marker else None
        if next_key not in names:
            raise ValueError(f"manual chapter {key!r} has an invalid next anchor")
        paragraph_html = "".join(f"<p>{escape(paragraph)}</p>" for paragraph in paragraphs)
        nav_html = (
            f'<p class="chapter-nav"><a href="#{escape(next_key, quote=True)}">'
            f'{escape(names[next_key])} →</a> · '
            f'<a href="#contents">{escape(tr("目录", language))}</a></p>'
        )
        sections.append(
            f'<section><h2 id="{escape(key, quote=True)}"><a name="{escape(key, quote=True)}"></a>{escape(heading)}</h2>'
            f"{paragraph_html}{nav_html}</section>"
        )
    colors = DARK
    css = f"""
      :root {{ color-scheme: dark; font-family: Segoe UI, Yu Gothic, Meiryo,
          'Microsoft YaHei', sans-serif; background: {colors['bg']}; color: {colors['text']}; }}
      * {{ box-sizing: border-box; }}
      body {{ margin: 0; padding: 26px clamp(18px, 4vw, 54px) 56px;
          background: {colors['bg']}; color: {colors['text']}; line-height: 1.72; }}
      main {{ max-width: 1040px; margin: auto; }}
      header {{ padding: 18px 22px 22px; margin-bottom: 24px; border: 1px solid {colors['border']};
          border-radius: 14px; background: {colors['surface']}; }}
      header img {{ display: block; width: min(240px, 60vw); height: auto; margin-bottom: 16px; }}
      h1 {{ font-size: 1.75rem; margin: 0; }}
      h2 {{ font-size: 1.3rem; margin: 0 0 14px; color: {colors['text']}; }}
      section, #contents {{ margin: 18px 0; padding: 20px 24px; border: 1px solid {colors['border']};
          border-radius: 12px; background: {colors['surface']}; scroll-margin-top: 12px; }}
      p {{ margin: 0 0 14px; }} p:last-child {{ margin-bottom: 0; }}
      a {{ color: {colors['primary-bg']}; text-decoration-thickness: 1px; text-underline-offset: 3px; }}
      a:hover {{ color: {colors['primary-hover']}; }}
      li {{ margin: 5px 0; }} ul {{ columns: 2; column-gap: 36px; padding-left: 24px; }}
      .chapter-nav {{ padding-top: 12px; border-top: 1px solid {colors['border']}; }}
      #research-courses pre {{ overflow-x: auto; padding: 14px; border-radius: 8px; background: {colors['bg']}; }}
      #research-courses table {{ display: block; overflow-x: auto; border-collapse: collapse; width: 100%; }}
      #research-courses th, #research-courses td {{ border: 1px solid {colors['border']}; padding: 7px 10px; text-align: left; }}
      #research-courses img {{ max-width: 100%; height: auto; }}
      @media (max-width: 680px) {{ ul {{ columns: 1; }} body {{ padding: 14px; }} section, #contents {{ padding: 16px; }} }}
    """
    logo_path = _LOGO_PATH
    if output_dir is not None and asset_base != docs_root:
        logo_path = _copy_asset_for_export(_LOGO_PATH, asset_base)
    logo_url = escape(_relative_asset_url(logo_path, asset_base), quote=True)
    return (
        '<!doctype html><html lang="' + language.replace("_", "-") + '"><head>'
        '<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="color-scheme" content="dark"><title>' + title + '</title><style>' + css +
        '</style></head><body><main><header><img src="' + logo_url + '" alt="KabuForge">'
        '<h1>' + title + '</h1></header>'
        '<nav id="contents"><h2>' + escape(tr("目录", language)) + '</h2><ul>' + toc + '</ul></nav>'
        + "".join(sections) + course_html + "</main></body></html>"
    )


def export_manuals(directory: str | Path | None = None) -> list[Path]:
    """Write the three language exports to the requested docs directory."""
    root = Path(directory) if directory else PACKAGE_DOCS_ROOT
    root.mkdir(parents=True, exist_ok=True)
    targets = []
    for language in CHAPTERS:
        target = root / f"manual_{language}.html"
        target.write_text(manual_html(language, output_dir=root), encoding="utf-8", newline="\n")
        targets.append(target)
    return targets


class HelpDialog(QDialog):
    """Offline manual reader with locale-aware chapter search and navigation."""

    def __init__(self, language: str = "zh_CN", parent=None):
        super().__init__(parent)
        self.language = _validate_language(language)
        self.chapter = "start"
        self._course_entries: tuple[tuple[str, str, str], ...] = ()
        if parent:
            self.setWindowIcon(parent.windowIcon())
        self.resize(1080, 780)
        self.setMinimumSize(700, 500)
        self.setStyleSheet(f"""
            QDialog {{ background: {DARK['bg']}; color: {DARK['text']}; }}
            QLineEdit, QListWidget, QTextBrowser {{ background: {DARK['surface']};
                color: {DARK['text']}; border: 1px solid {DARK['border']}; border-radius: 7px; }}
            QListWidget::item {{ padding: 8px 7px; border-radius: 5px; }}
            QListWidget::item:selected {{ background: {DARK['primary-bg']}; color: {DARK['primary-fg']}; }}
            QPushButton {{ background: {DARK['surface-muted']}; color: {DARK['text']};
                border: 1px solid {DARK['border']}; border-radius: 6px; padding: 7px 12px; }}
            QPushButton:hover {{ border-color: {DARK['primary-bg']}; }}
        """)

        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setAccessibleName(tr("搜索结果", self.language))
        self.previous = QPushButton()
        self.next = QPushButton()
        bar.addWidget(self.search, 1)
        bar.addWidget(self.previous)
        bar.addWidget(self.next)
        layout.addLayout(bar)

        split = QSplitter()
        self.contents = QListWidget()
        self.contents.setMinimumWidth(230)
        self.browser = QTextBrowser()
        self.browser.setOpenLinks(False)
        self.browser.setOpenExternalLinks(False)
        self.browser.setStyleSheet(
            f"QTextBrowser {{ background:{DARK['bg']}; color:{DARK['text']}; padding:16px; }}"
        )
        split.addWidget(self.contents)
        split.addWidget(self.browser)
        split.setSizes([270, 760])
        layout.addWidget(split)

        self.search.textChanged.connect(self._search)
        self.contents.itemClicked.connect(self._select)
        self.browser.anchorClicked.connect(self._anchor)
        self.previous.clicked.connect(lambda: self.find_match(True))
        self.next.clicked.connect(lambda: self.find_match(False))
        self.set_language(self.language)

    def set_language(self, language: str) -> None:
        language = _validate_language(language)
        self.language = language
        self._course_entries = research_course_search_entries(language)
        self.setWindowTitle("KabuForge · " + tr("操作手册", language))
        self.search.setPlaceholderText(tr("搜索章节或关键词…", language))
        self.search.setAccessibleName(tr("搜索结果", language))
        self.previous.setText(tr("上一处", language))
        self.next.setText(tr("下一处", language))
        docs = PACKAGE_DOCS_ROOT
        base_file = docs / f"manual_{language}.html"
        self.browser.document().setBaseUrl(QUrl.fromLocalFile(str(base_file)))
        self.browser.setHtml(manual_html(language))
        self._search()
        self.browser.scrollToAnchor(self.chapter)

    def _search(self, *_args) -> None:
        query = self.search.text().strip().casefold()
        self.contents.clear()
        entries = [
            (key, title, " ".join(text for text in body if not text.startswith("next:")))
            for key, title, *body in CHAPTERS[self.language]
        ] + list(self._course_entries)
        for key, title, searchable in entries:
            if query and query not in searchable.casefold():
                continue
            item = QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, key)
            if query:
                position = searchable.casefold().find(query)
                item.setToolTip(searchable[max(0, position - 45):position + 180])
            self.contents.addItem(item)
        if not self.contents.count():
            item = QListWidgetItem(tr("未找到匹配内容", self.language))
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.contents.addItem(item)

    def _select(self, item: QListWidgetItem) -> None:
        key = item.data(Qt.ItemDataRole.UserRole)
        if key:
            self.chapter = key
            self.browser.scrollToAnchor(key)

    def _anchor(self, url: QUrl) -> None:
        if url.fragment() and not url.scheme():
            self.chapter = url.fragment()
            self.browser.scrollToAnchor(self.chapter)

    def find_match(self, backward: bool = False) -> bool:
        text = self.search.text().strip()
        if not text:
            return False
        flags = QTextDocument.FindFlag.FindBackward if backward else QTextDocument.FindFlag(0)
        if self.browser.find(text, flags):
            return True
        cursor = self.browser.textCursor()
        cursor.movePosition(
            cursor.MoveOperation.End if backward else cursor.MoveOperation.Start
        )
        self.browser.setTextCursor(cursor)
        return self.browser.find(text, flags)
