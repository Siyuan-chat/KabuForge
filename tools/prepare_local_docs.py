"""Mirror reviewed formal docs into the installable local package."""
from pathlib import Path
import shutil


root=Path(__file__).resolve().parents[1]
for locale in ('en_US','zh_CN','ja_JP'):
    for source in (root/'docs'/locale).rglob('*.md'):
        destination=root/'framework_v2/docs'/locale/source.relative_to(root/'docs'/locale)
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,destination)
