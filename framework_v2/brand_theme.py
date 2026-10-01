"""Qt palette derived directly from the supplied KabuForge v1 CSS tokens."""
from pathlib import Path
import re

BRAND_DIR=Path(__file__).resolve().parent/"assets"/"brand"

def palette(mode="dark"):
    source=(BRAND_DIR/"tokens.css").read_text(encoding="utf-8")
    blocks=re.findall(r"\{([^}]+)\}",source)
    def parse(block): return dict(re.findall(r"--kf-([\w-]+)\s*:\s*(#[0-9A-Fa-f]{6})\s*;",block))
    values=parse(blocks[0])
    if mode=="dark": values.update(parse(blocks[1]))
    return values

DARK=palette("dark")
LIGHT=palette("light")

def branded_stylesheet(existing):
    p=DARK
    # Preserve established spacing/roles while replacing legacy palette tokens.
    roles={
        "bg":["#0C0F14","#0E1218"],
        "surface":["#11151C","#151A22","#171C25","#141820","#141922","#11161E"],
        "surface-muted":["#202632","#282F3D","#182237","#1A2332","#1D2B42","#202630"],
        "text":["#E9ECF2","#F3F5F8","#D9DEE7","#C8D0DC","#BCC4CF"],
        "text-muted":["#738095","#9AA4B2","#AAB4C2","#8F99A8"],
        "border":["#252B36","#2B323E","#303744","#434C5D","#242A34","#273245","#596474"],
        "focus":["#3D7BFA","#365C9A","#315FAE"],
        "primary-hover":["#4D87FF"],"info":["#8DB2FF"],
        "success":["#65DD84"],"warning":["#FFB340","#FF9F0A"],"danger":["#FF6B63","#FF453A"],
    }
    mapping={old:p[key] for key,colors in roles.items() for old in colors}
    styled=re.sub(r"#[0-9A-Fa-f]{6}",lambda m:mapping.get(m[0],m[0]),existing)
    return styled+f'''
QPushButton#primaryButton {{background:{p['primary-bg']};border-color:{p['primary-bg']};color:{p['primary-fg']};}}
QPushButton#primaryButton:hover {{background:{p['primary-hover']};border-color:{p['primary-hover']};}}
QPushButton#primaryButton:disabled {{background:{p['surface-muted']};border-color:{p['border']};color:{p['text-muted']};}}
QAbstractItemView {{selection-background-color:{p['primary-bg']};selection-color:{p['primary-fg']};}}
QListWidget::item {{padding:8px 6px;border-radius:5px;}}
QListWidget::item:selected {{background:{p['primary-bg']};color:{p['primary-fg']};}}
QLineEdit,QTextEdit,QPlainTextEdit {{selection-background-color:{p['primary-bg']};selection-color:{p['primary-fg']};}}
QTableView {{background:{p['surface']};alternate-background-color:{p['surface-muted']};gridline-color:{p['border']};}}
QToolTip {{background:{p['surface-muted']};color:{p['text']};border:1px solid {p['border']};padding:5px;}}
'''
