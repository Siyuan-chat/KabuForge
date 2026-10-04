"""Run outside the checkout with a wheel-installed Python and GUI extra."""
from pathlib import Path
import json
import os
import subprocess
import sys
import sysconfig
import tempfile
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import kabuforge
import framework_v2.application
from framework_v2.legacy_provider import BuiltinFactors
from framework_v2.brand_theme import BRAND_DIR
from PySide6.QtWidgets import QApplication
from framework_v2.product_ui import ProductWorkbench

site=Path(sysconfig.get_paths()['purelib']).resolve()
assert Path(kabuforge.__file__).resolve().is_relative_to(site)
assert Path(framework_v2.application.__file__).resolve().is_relative_to(site)
assert all(x.startswith('public.') for x in BuiltinFactors().versions)
assert BRAND_DIR.is_relative_to(site) and (BRAND_DIR/'tokens.css').is_file()
with tempfile.TemporaryDirectory() as temporary:
    root=Path(temporary)
    result=subprocess.run([sys.executable,'-m','kabuforge','doctor'],cwd=root,capture_output=True,text=True,check=True)
    assert json.loads(result.stdout)['distribution']=='PUBLIC'
    app=QApplication.instance() or QApplication([])
    with patch('framework_v2.data_connection.load_api_key',return_value=None):window=ProductWorkbench(root/'gui')
    assert not window.windowIcon().isNull() and window.brand_logo.renderer().isValid()
    window.document._dirty=False;window.close();app.processEvents()
print(json.dumps({'installed_package':True,'GUI_resources':True,'public_factor_family':True}))
