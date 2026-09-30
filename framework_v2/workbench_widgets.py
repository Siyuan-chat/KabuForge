"""Graphite widgets shared by the private v2 workbench pages."""
from __future__ import annotations
import csv
import json
from pathlib import Path
from PySide6.QtCore import Qt,QSortFilterProxyModel,QPointF
from PySide6.QtGui import QStandardItemModel,QStandardItem,QKeySequence,QShortcut,QPainter,QPen,QColor,QPolygonF
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QTableView,QLineEdit,
    QPushButton,QFileDialog,QApplication,QLabel,QHeaderView)

def label(text,role=None):
    widget=QLabel(text); widget.setWordWrap(role not in {"brandTitle","pageTitle","brandEyebrow","statusPill"})
    widget.setMinimumWidth(0)
    if role: widget.setObjectName(role)
    return widget

class DataTable(QWidget):
    def __init__(self,name,settings=None,parent=None):
        super().__init__(parent); self.name=name; self.settings=settings
        box=QVBoxLayout(self); box.setContentsMargins(0,0,0,0)
        tools=QHBoxLayout(); self.search=QLineEdit(); self.search.setPlaceholderText("筛选表格…")
        self.search.setAccessibleName(name+"筛选")
        tools.addWidget(self.search); self.export=QPushButton("导出 CSV"); tools.addWidget(self.export); box.addLayout(tools)
        self.model=QStandardItemModel(); self.proxy=QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model); self.proxy.setFilterKeyColumn(-1)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.setSortRole(Qt.ItemDataRole.UserRole)
        self.view=QTableView(); self.view.setModel(self.proxy); self.view.setSortingEnabled(True)
        self.view.setAlternatingRowColors(True); self.view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.view.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.view.horizontalHeader().setStretchLastSection(True)
        self.view.setAccessibleName(name); box.addWidget(self.view)
        self.search.textChanged.connect(self.proxy.setFilterFixedString)
        self.export.clicked.connect(self.export_csv)
        QShortcut(QKeySequence.StandardKey.Copy,self.view,activated=self.copy_selected)
        self.rows=[]; self.columns=[]

    def set_rows(self,rows,columns=None):
        self.rows=list(rows or []); self.columns=list(columns or (list(self.rows[0]) if self.rows else []))
        self.view.setSortingEnabled(False); self.model.clear(); self.model.setHorizontalHeaderLabels(self.columns)
        for row in self.rows:
            items=[]
            for key in self.columns:
                value=row.get(key,"")
                text=json.dumps(value,ensure_ascii=False) if isinstance(value,(dict,list,tuple)) else str(value if value is not None else "—")
                item=QStandardItem(text); item.setToolTip(text)
                try: sort=float(value)
                except (ValueError,TypeError): sort=text
                item.setData(sort,Qt.ItemDataRole.UserRole); items.append(item)
            self.model.appendRow(items)
        self.view.setSortingEnabled(True)
        for i in range(len(self.columns)): self.view.setColumnWidth(i,150)
        if self.settings:
            saved=self.settings.value("tables/"+self.name)
            if saved is not None: self.view.horizontalHeader().restoreState(saved)

    def persist(self):
        if self.settings: self.settings.setValue("tables/"+self.name,self.view.horizontalHeader().saveState())

    def visible_rows(self):
        return [[str(self.proxy.index(r,c).data() or "") for c in range(self.proxy.columnCount())] for r in range(self.proxy.rowCount())]

    def copy_selected(self):
        indexes=self.view.selectionModel().selectedIndexes()
        rows=sorted({i.row() for i in indexes}); cols=sorted({i.column() for i in indexes})
        QApplication.clipboard().setText("\n".join("\t".join(str(self.proxy.index(r,c).data() or "") for c in cols) for r in rows))

    def export_csv(self):
        path,_=QFileDialog.getSaveFileName(self,"导出当前筛选结果","", "CSV (*.csv)")
        if path:
            with Path(path).open("w",newline="",encoding="utf-8-sig") as stream:
                writer=csv.writer(stream); writer.writerow(self.columns)
                for row in self.visible_rows():
                    writer.writerow(["'"+v if v.startswith(("=","+","@")) else v for v in row])

class SeriesChart(QWidget):
    """Display report values only; portfolio or performance calculations stay upstream."""
    def __init__(self,title,percent=False,parent=None):
        super().__init__(parent); self.title=title; self.percent=percent; self.series=[]; self.dates=[]
        self.setMinimumHeight(180); self.setAccessibleName(title)

    def set_series(self,dates,series):
        self.dates=list(dates); self.series=list(series); self.update()

    def paintEvent(self,event):
        painter=QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette=getattr(self,"brand_palette",{})
        painter.fillRect(self.rect(),QColor(palette.get("surface","#11151C"))); painter.setPen(QColor(palette.get("text","#E9ECF2")))
        from .i18n import tr
        language=getattr(self,"language","zh_CN")
        painter.drawText(16,25,tr(self.title,language))
        if not self.series or not any(values for _,values in self.series):
            painter.setPen(QColor(palette.get("text-muted","#9AA4B2"))); painter.drawText(16,60,tr("运行后显示；不以演示曲线代替结果",language))
            return
        values=[float(v) for _,seq in self.series for v in seq]
        low,high=min(values),max(values); pad=max((high-low)*.15,abs(high)*.001,.001)
        low-=pad; high+=pad
        left,top,right,bottom=72,48,self.width()-20,self.height()-34
        for i in range(4):
            y=top+(bottom-top)*i/3; val=high-(high-low)*i/3
            painter.setPen(QColor(palette.get("border","#252B36"))); painter.drawLine(left,int(y),right,int(y))
            painter.setPen(QColor(palette.get("text-muted","#9AA4B2"))); painter.drawText(8,int(y)+4,f"{val:.1%}" if self.percent else f"{val:.3f}")
        colors=[palette.get("info","#8DB2FF"),palette.get("text-muted","#FFB340")]
        for idx,(name,seq) in enumerate(self.series):
            painter.setPen(QPen(QColor(colors[idx%2]),2))
            points=QPolygonF([QPointF(left+(right-left)*i/max(1,len(seq)-1),bottom-(float(v)-low)/(high-low)*(bottom-top)) for i,v in enumerate(seq)])
            if len(points)==1: painter.drawEllipse(points[0],3,3)
            else: painter.drawPolyline(points)
            painter.drawText(180+idx*180,25,tr(name,language))
        painter.setPen(QColor(palette.get("text-muted","#9AA4B2")))
        if self.dates:
            painter.drawText(left,self.height()-10,str(self.dates[0])[:10])
            painter.drawText(max(left,right-85),self.height()-10,str(self.dates[-1])[:10])
