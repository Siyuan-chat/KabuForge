import json
import tempfile
import unittest
from pathlib import Path

from framework_v2.workbench_model import ConfigDocument
from framework_v2.config import ConfigError


class DocumentTests(unittest.TestCase):
    def test_metadata_roundtrip_revision_and_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "run.json"
            original = {"schema_version": "1.0", "kind": "run", "id": "r", "version": "1",
                        "strategy": "strategy.json", "data_snapshot": "data.json",
                        "account_ref": "account.json", "clock": {"start": "2024-01-01", "end": "2024-01-31", "timezone": "Asia/Tokyo"},
                        "mode": "backtest", "fees": {"commission_rate": 0, "minimum_fee": 0},
                        "output_dir": "out", "metadata": {"nested": {"memo": "keep"}}}
            source.write_text(json.dumps(original), encoding="utf-8")
            doc = ConfigDocument(source)
            self.assertFalse(doc.dirty)
            external = doc.data
            external["metadata"]["nested"]["memo"] = "corrupt"
            self.assertEqual(doc.data["metadata"]["nested"]["memo"], "keep")
            revision = doc.revision
            doc.set_field("fees.minimum_fee", 3)
            self.assertEqual(doc.revision, revision + 1)
            doc.set_json(doc.text)
            self.assertEqual(doc.validate(), [])
            saved = doc.save_as(root / "copy.json")
            self.assertFalse(doc.dirty)
            self.assertEqual(json.loads(saved.read_text(encoding="utf-8"))["metadata"], original["metadata"])
            nested = doc.save_as(root / "nested" / "copy.json")
            new_value = json.loads(nested.read_text(encoding="utf-8"))
            for key in ("strategy", "data_snapshot", "account_ref", "output_dir"):
                self.assertEqual((nested.parent / new_value[key]).resolve(), (root / original[key]).resolve())
            self.assertEqual(new_value["metadata"], original["metadata"])

    def test_unknown_missing_legacy_and_unsafe_json(self):
        doc = ConfigDocument()
        doc.set_json('{"kind":"run","extra":1}')
        fields = doc.validate()
        self.assertTrue(any("Additional properties" in item["message"] for item in fields))
        self.assertTrue(any("required" in item["message"] for item in fields))
        doc.set_json('{"legacy":"factor"}')
        self.assertIn("conversion", doc.validate()[0]["message"])
        with self.assertRaises(ConfigError):
            doc.set_json('{"x":1,"x":2}')
        with self.assertRaises(ConfigError):
            doc.set_json('{"x":NaN}')
        with self.assertRaises(ConfigError):
            doc.set_field("missing.nested", 1)
        doc.set_json('{"kind":[]}')
        self.assertEqual(doc.validate()[0]["field"], "kind")


if __name__ == "__main__":
    unittest.main()
