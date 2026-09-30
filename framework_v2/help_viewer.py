"""Searchable offline help with stable chapter anchors and standalone HTML export."""
from html import escape
from pathlib import Path
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QSplitter,QLineEdit,QListWidget,QListWidgetItem,QTextBrowser,QPushButton
from .manual_content import CHAPTERS
from .i18n import tr
from .brand_theme import LIGHT,BRAND_DIR

def manual_html(language):
    chapters=CHAPTERS[language]
    title={"zh_CN":"KabuForge 操作手册","ja_JP":"KabuForge 操作マニュアル","en_US":"KabuForge User Guide"}[language]
    toc="".join(f'<li><a href="#{key}">{escape(heading)}</a></li>' for key,heading,*_ in chapters)
    sections=[]
    names={row[0]:row[1] for row in chapters}
    for key,heading,*body in chapters:
        paragraphs="".join(f'<p>{escape(p)}</p>' for p in body if not p.startswith("next:"))
        target=body[-1].split(":",1)[1]
        sections.append(f'<h2 id="{key}"><a name="{key}"></a>{escape(heading)}</h2>{paragraphs}<p><a href="#{target}">{escape(names[target])} →</a> · <a href="#contents">{tr("目录",language)}</a></p>')
    return f'<!doctype html><html lang="{language.replace("_","-")}"><head><meta charset="utf-8"><title>{title}</title><style>body{{font-family:"Segoe UI","Yu Gothic","Microsoft YaHei",sans-serif;line-height:1.7;margin:32px;max-width:960px;color:{LIGHT["text"]};background:{LIGHT["bg"]}}}a{{color:{LIGHT["primary-bg"]}}}h2{{margin-top:36px}}p{{margin:14px 0}}</style></head><body><p><img src="../../brand/kabuforge/v1/logo-horizontal-light.png" width="240" height="51" alt="KabuForge"></p><h1>{title}</h1><h2 id="contents"><a name="contents"></a>{tr("目录",language)}</h2><ul>{toc}</ul>{"".join(sections)}</body></html>'

def export_manuals(directory=None):
    root=Path(directory) if directory else Path(__file__).parent/"docs"
    root.mkdir(parents=True,exist_ok=True)
    for language in CHAPTERS:
        (root/f"manual_{language}.html").write_text(manual_html(language),encoding="utf-8")

class HelpDialog(QDialog):
    def __init__(self,language="zh_CN",parent=None):
        super().__init__(parent); self.language=language; self.chapter="start"
        if parent: self.setWindowIcon(parent.windowIcon())
        self.resize(1050,760); self.setMinimumSize(680,480)
        layout=QVBoxLayout(self); bar=QHBoxLayout(); self.search=QLineEdit()
        self.previous=QPushButton(); self.next=QPushButton()
        bar.addWidget(self.search,1); bar.addWidget(self.previous); bar.addWidget(self.next); layout.addLayout(bar)
        split=QSplitter(); self.contents=QListWidget(); self.contents.setMinimumWidth(220)
        self.browser=QTextBrowser(); self.browser.setOpenLinks(False); self.browser.setOpenExternalLinks(False)
        self.browser.setStyleSheet(f"QTextBrowser {{ background:{LIGHT['bg']}; color:{LIGHT['text']}; padding:16px; }}")
        split.addWidget(self.contents); split.addWidget(self.browser); split.setSizes([260,740]); layout.addWidget(split)
        self.search.textChanged.connect(self._search); self.contents.itemClicked.connect(self._select)
        self.browser.anchorClicked.connect(self._anchor)
        self.previous.clicked.connect(lambda:self.find_match(True)); self.next.clicked.connect(lambda:self.find_match(False))
        self.set_language(language)

    def set_language(self,language):
        self.language=language; self.setWindowTitle("KabuForge · "+tr("操作手册",language))
        self.search.setPlaceholderText(tr("搜索章节或关键词…",language))
        self.previous.setText(tr("上一处",language)); self.next.setText(tr("下一处",language))
        self.browser.document().setBaseUrl(QUrl.fromLocalFile(str(Path(__file__).parent/"docs"/"index.html")))
        self.browser.setHtml(manual_html(language)); self._search(); self.browser.scrollToAnchor(self.chapter)

    def _search(self,*_):
        query=self.search.text().strip().casefold(); self.contents.clear()
        for key,title,*body in CHAPTERS[self.language]:
            haystack=title+" "+" ".join(body[:-1])
            if query and query not in haystack.casefold(): continue
            item=QListWidgetItem(title); item.setData(Qt.ItemDataRole.UserRole,key)
            if query:
                pos=haystack.casefold().find(query); item.setToolTip(haystack[max(0,pos-35):pos+160])
            self.contents.addItem(item)
        if not self.contents.count():
            item=QListWidgetItem(tr("未找到匹配内容",self.language)); item.setFlags(Qt.ItemFlag.NoItemFlags); self.contents.addItem(item)

    def _select(self,item):
        key=item.data(Qt.ItemDataRole.UserRole)
        if key: self.chapter=key; self.browser.scrollToAnchor(key)

    def _anchor(self,url):
        if url.fragment() and not url.scheme(): self.chapter=url.fragment(); self.browser.scrollToAnchor(self.chapter)

    def find_match(self,backward=False):
        text=self.search.text().strip()
        if not text: return False
        flags=QTextDocument.FindFlag.FindBackward if backward else QTextDocument.FindFlag(0)
        if self.browser.find(text,flags): return True
        cursor=self.browser.textCursor(); cursor.movePosition(cursor.MoveOperation.End if backward else cursor.MoveOperation.Start); self.browser.setTextCursor(cursor)
        return self.browser.find(text,flags)
