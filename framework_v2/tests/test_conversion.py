from pathlib import Path
import tempfile
import unittest
import json
from framework_v2.conversion import convert_factor
from framework_v2.factors import FactorContractError

class ConversionTests(unittest.TestCase):
    def test_original_bytes_and_parameters_preserved_unknown_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); source=root/"source.json"
            raw=b'{ "short_ma_window": 12, "long_ma_window": 48 }\n'
            source.write_bytes(raw)
            output=convert_factor(source,root/"converted",name="dual_ma",factor_id="custom_ma",lookback=320)
            self.assertEqual(source.read_bytes(),raw)
            self.assertEqual((output.parent/"legacy_original.json").read_bytes(),raw)
            self.assertEqual(json.loads(output.read_text())["implementation"]["parameters"],json.loads(raw))
            source.write_text('{"composite_formula":"Q+V"}')
            with self.assertRaises(FactorContractError): convert_factor(source,root/"bad",name="quality",factor_id="q",lookback=365)
            self.assertFalse((root/"bad").exists())

if __name__=="__main__": unittest.main()
