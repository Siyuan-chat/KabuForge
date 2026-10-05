from __future__ import annotations

import hashlib
import json
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget

from framework_v2.broker_research_panel import BrokerResearchPanel
from framework_v2.broker_research import BrokerResearchConfig
from framework_v2.broker_readonly import ALLOWED_GET_PATHS, BrokerReadOnlyError, check_read_only
from framework_v2.historical_paper_panel import HistoricalPaperPanel
from framework_v2.tests.test_historical_paper_research import _workspace_inputs
from framework_v2.product_ui import ProductWorkbench


class PaperBrokerGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])

    def setUp(self): self.temp=tempfile.TemporaryDirectory(prefix="paper-broker-gui-"); self.root=Path(self.temp.name)
    def tearDown(self): self.temp.cleanup()

    def test_imported_gui_panels_come_from_this_candidate_checkout(self):
        candidate=Path(__file__).resolve().parents[2]
        import framework_v2.broker_research_panel as broker_module
        import framework_v2.historical_paper_panel as paper_module
        self.assertTrue(Path(broker_module.__file__).resolve().is_relative_to(candidate),broker_module.__file__)
        self.assertTrue(Path(paper_module.__file__).resolve().is_relative_to(candidate),paper_module.__file__)

    def _wait(self,predicate,timeout=30):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            self.app.processEvents(); time.sleep(.01)
            if predicate(): return
        self.fail(f"background operation timed out after {timeout}s")

    def test_historical_panel_creates_steps_queries_reopens_and_completes(self):
        dates=["2021-01-04","2021-01-05","2021-01-06","2021-01-07"]
        orders=[{"signal_date":dates[0],"execution_date":dates[1],"code":"4502","side":"buy","quantity":10.0,"sizing_price":10.0}]
        source=self.root/"inputs"; manifest,report=_workspace_inputs(source,dates,orders)
        panel=HistoricalPaperPanel(self.root,language="en_US")
        account_path=self.root/"teaching-account"
        panel.set_inputs(manifest,report,hashlib.sha256(report.read_bytes()).hexdigest())
        panel.workspace_edit.setText(str(account_path)); panel.show(); self.app.processEvents()
        try:
            self.assertTrue(panel.create_account()); self._wait(lambda:not panel.busy)
            self.assertEqual(panel.last_result["summary"]["cursor"],0)
            journal=account_path/"journal.jsonl"; before=hashlib.sha256(journal.read_bytes()).hexdigest()
            self.assertTrue(panel.refresh()); self._wait(lambda:not panel.busy)
            self.assertIn("query did not advance",panel.status.text())
            self.assertEqual(hashlib.sha256(journal.read_bytes()).hexdigest(),before)
            self.assertEqual(panel.last_result["summary"]["cursor"],0)
            self.assertTrue(panel.step_next()); self._wait(lambda:not panel.busy)
            self.assertEqual(panel.last_result["summary"]["cursor"],1)
            panel.set_language("ja_JP"); self.assertIn("次の取引日",panel.status.text())
            self.assertTrue(panel.open_account()); self._wait(lambda:not panel.busy)
            self.assertEqual(panel.last_result["summary"]["cursor"],1)
            self.assertTrue(panel.run_all()); self._wait(lambda:not panel.busy)
            self.assertEqual(panel.last_result["summary"]["status"],"COMPLETED")
            self.assertEqual(panel.last_result["summary"]["cursor"],len(dates))
            self.assertEqual(panel.table.rowCount(),len(dates))
            self.assertIn("PIT 未認証",panel.status.text())
        finally:
            if panel.busy: self._wait(lambda:not panel.busy)
            panel.close(); self.app.processEvents()

    def test_broker_panel_saves_reference_only_and_previews_without_transport(self):
        panel=BrokerResearchPanel(self.root,language="zh_CN")
        folder=self.root/"broker-config"; panel.workspace_edit.setText(str(folder))
        try:
            self.assertTrue(panel.save_config())
            self.assertTrue((folder/"broker_config.json").is_file())
            saved=json.loads((folder/"broker_config.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["config"]["credential_ref"],"env:KABU_TOKEN")
            self.assertEqual(saved["config"]["credential_ref"],panel.credential_ref.text())
            self.assertEqual(saved["config"]["endpoint"],"http://127.0.0.1:18081")
            panel.order_type.setCurrentIndex(panel.order_type.findData("limit"))
            panel.limit_price.setValue(1000.0)
            receipt_path=panel.preview(); self.assertIsNotNone(receipt_path)
            receipt=json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["network_calls"],0)
            self.assertFalse(receipt["credential_resolved"])
            self.assertEqual(receipt["status"],"MAPPED_LOCALLY_NOT_CONNECTED_NOT_SUBMITTED")
            self.assertEqual(receipt["mapped_request"]["Qty"],100)
            self.assertEqual(receipt["mapped_request"]["FrontOrderType"],20)
            panel.environment.setCurrentIndex(0)
            self.assertFalse(panel.preview_button.isEnabled())
            self.assertIn("请选择新的隔离目录",panel.status.text())
            panel.environment.setCurrentIndex(1)
            self.assertTrue(panel.preview_button.isEnabled())
            panel.quantity.setValue(101)
            self.assertIsNone(panel.preview())
            self.assertIn("整手",panel.status.text())
            panel.set_language("en_US")
            self.assertIn("Preview blocked",panel.status.text())
            self.assertNotIn("MAPPED_LOCALLY_NOT_CONNECTED_NOT_SUBMITTED",panel.mapping.toPlainText())
            self.assertIsNone(panel.last_receipt)
            failures=list((folder/"mapping-failures").glob("*/failure.json"))
            self.assertEqual(len(failures),1)
            failure=json.loads(failures[0].read_text(encoding="utf-8"))
            self.assertEqual(failure["error_code"],"invalid_lot")
            self.assertFalse(failure["order_payload_persisted"])
        finally: panel.close(); self.app.processEvents()

    def test_read_only_service_is_get_only_local_bounded_and_redacted(self):
        config=BrokerResearchConfig("test","http://127.0.0.1:18081","teaching",2,9,"env:KABU_TEST_TOKEN")
        calls=[]
        def requester(path):
            calls.append(path)
            return 200,b'{"StockAccountWallet":"12345"}' if path=="/kabusapi/wallet/cash" else b'[]'
        result=check_read_only(config,credential_resolver=lambda ref:"secret-never-log",requester=requester,timeout=.5)
        self.assertEqual(calls,list(ALLOWED_GET_PATHS))
        self.assertEqual(result["status"],"CONNECTED_READ_ONLY")
        self.assertEqual(result["network_calls"],3)
        self.assertFalse(result["proxies_used"])
        self.assertFalse(result["redirects_allowed"])
        serialized=json.dumps(result)
        self.assertNotIn("secret-never-log",serialized)
        self.assertNotIn("12345",serialized)
        no_calls=[]
        with self.assertRaises(BrokerReadOnlyError) as caught:
            check_read_only(config,credential_resolver=lambda ref:None,
                requester=lambda path:no_calls.append(path),timeout=1)
        self.assertEqual(caught.exception.code,"credential_missing")
        self.assertEqual(no_calls,[])

        from unittest.mock import Mock, call, patch
        response=Mock(); response.status=200
        response.read.side_effect=[b'{"StockAccountWallet":null}',b'[]',b'[]']
        connection=Mock(); connection.getresponse.return_value=response
        with patch("framework_v2.broker_readonly.http.client.HTTPConnection",return_value=connection) as factory:
            actual=check_read_only(config,credential_resolver=lambda ref:"local-secret",timeout=1.25)
        self.assertEqual(factory.call_args_list,[call("127.0.0.1",18081,timeout=1.25)]*3)
        self.assertEqual([args.args[:2] for args in connection.request.call_args_list],
            [("GET",path) for path in ALLOWED_GET_PATHS])
        self.assertTrue(all(args.kwargs["headers"]["X-API-KEY"]=="local-secret" for args in connection.request.call_args_list))
        self.assertEqual(actual["network_calls"],3)

        for bad_path,bad_body,expected_code in (
            ("/kabusapi/wallet/cash",b'{"Code":400,"Message":"private terminal detail"}',"response_error"),
            ("/kabusapi/wallet/cash",b'{"cash":100}',"response_shape_invalid"),
            ("/kabusapi/positions",b'[1]',"response_shape_invalid"),
        ):
            def bad_requester(path,bad_path=bad_path,bad_body=bad_body):
                if path==bad_path: return 200,bad_body
                return 200,b'{"StockAccountWallet":null}' if path==ALLOWED_GET_PATHS[0] else b'[]'
            with self.assertRaises(BrokerReadOnlyError) as bad_response:
                check_read_only(config,credential_resolver=lambda ref:"unused",requester=bad_requester,timeout=1)
            self.assertEqual(bad_response.exception.code,expected_code)
            self.assertNotIn("private terminal detail",str(bad_response.exception))

        response.status=302
        connection.reset_mock(); connection.getresponse.return_value=response; response.read.side_effect=None; response.read.return_value=b'{}'
        with patch("framework_v2.broker_readonly.http.client.HTTPConnection",return_value=connection):
            with self.assertRaises(BrokerReadOnlyError) as redirect:
                check_read_only(config,credential_resolver=lambda ref:"local-secret",timeout=1)
        self.assertEqual(redirect.exception.code,"redirect_blocked")
        self.assertEqual(list(redirect.exception.attempted_paths),[ALLOWED_GET_PATHS[0]])
        self.assertEqual(connection.request.call_count,1,"a redirect must never be followed")

        for invalid_timeout in (True,float("nan"),float("inf")):
            with self.assertRaises(BrokerReadOnlyError) as invalid:
                check_read_only(config,credential_resolver=lambda ref:"unused",requester=lambda path:None,timeout=invalid_timeout)
            self.assertEqual(invalid.exception.code,"timeout_out_of_range")

    def test_panel_read_only_button_resolves_only_on_click_and_persists_redacted_failure(self):
        from unittest.mock import patch
        from framework_v2 import broker_readonly
        panel=BrokerResearchPanel(self.root,language="zh_CN")
        self.assertIn("生产",panel.environment.itemText(0)); self.assertIn("测试",panel.environment.itemText(1))
        folder=self.root/"readonly-config"; panel.workspace_edit.setText(str(folder))
        try:
            with patch.object(broker_readonly,"check_read_only",side_effect=BrokerReadOnlyError("credential_missing")) as check:
                self.assertTrue(panel.save_config())
                self.assertEqual(check.call_count,0)
                self.assertTrue(panel.readonly_check_button.isEnabled())
                panel.readonly_check_button.click()
                self._wait(lambda:check.call_count==1 and not panel.busy)
                self.assertEqual(check.call_count,1)
                self.assertIn("凭证引用不存在",panel.status.text())
            failures=list((folder/"read-only-checks").glob("*/failure.json"))
            self.assertEqual(len(failures),1)
            text=failures[0].read_text(encoding="utf-8")
            receipt=json.loads(text)
            self.assertEqual(receipt["error_code"],"credential_missing")
            self.assertTrue(receipt["details_redacted"])
            self.assertEqual(receipt["network_calls"],0)
            self.assertNotIn("teaching-cash-account",text)
            fake_success={"schema":"kabuforge_broker_read_only_check","status":"CONNECTED_READ_ONLY",
                "environment":"test","endpoint":"http://127.0.0.1:18081","network_calls":3,
                "credential_value_persisted":False,"account_values_persisted":False,"requests":[]}
            with patch.object(broker_readonly,"check_read_only",return_value=fake_success):
                panel.readonly_check_button.click()
                self._wait(lambda:not panel.busy)
            self.assertIn("只读连接成功",panel.status.text())
            successes=list((folder/"read-only-checks").glob("*/result.json"))
            self.assertEqual(len(successes),1)
            success_text=successes[0].read_text(encoding="utf-8")
            self.assertNotIn("teaching-cash-account",success_text)
            self.assertNotIn("KABU_TOKEN",success_text)
            panel.set_language("ja_JP")
            self.assertIn("読み取り専用接続成功",panel.status.text())
            panel.credential_ref.setText("env:KABU_OTHER_TOKEN")
            self.assertFalse(panel.readonly_check_button.isEnabled())
            self.assertIn("新しい隔離ディレクトリ",panel.status.text())
        finally:
            panel.close(); self.app.processEvents()

    def test_actual_missing_environment_reference_fails_before_any_get(self):
        from framework_v2 import broker_readonly
        variable="KABUFORGE_ROOT_DEMO_MISSING_TOKEN_20261006"
        panel=BrokerResearchPanel(self.root,language="en_US")
        panel.credential_ref.setText("env:"+variable)
        panel.workspace_edit.setText(str(self.root/"missing-reference"))
        try:
            self.assertTrue(panel.save_config())
            with patch.dict(os.environ,{variable:""}), \
                 patch("framework_v2.broker_readonly.http.client.HTTPConnection",
                       side_effect=AssertionError("missing environment reference must not open a socket")) as connection:
                panel.readonly_check_button.click()
                self._wait(lambda:not panel.busy)
            connection.assert_not_called()
            self.assertEqual(panel._failure_code,"credential_missing")
            receipt=json.loads(panel.failure_receipt.read_text(encoding="utf-8"))
            self.assertEqual(receipt["error_code"],"credential_missing")
            self.assertEqual(receipt["network_calls"],0)
            self.assertEqual(receipt["attempted_get_paths"],[])
            self.assertTrue(receipt["details_redacted"])
            self.assertNotIn(variable,panel.failure_receipt.read_text(encoding="utf-8"))
        finally:
            panel.close(); self.app.processEvents()

    def test_read_only_check_runs_off_event_loop_and_parent_close_waits(self):
        import time
        from unittest.mock import patch
        from framework_v2 import broker_readonly
        parent=QWidget(); panel=BrokerResearchPanel(self.root,language="en_US",parent=parent)
        folder=self.root/"async-config"; panel.workspace_edit.setText(str(folder))
        self.assertTrue(panel.save_config())
        timer_fired=[]; QTimer.singleShot(10,lambda:timer_fired.append(True))
        def delayed_success(config,*,timeout):
            time.sleep(.18)
            return {"schema":"kabuforge_broker_read_only_check","status":"CONNECTED_READ_ONLY",
                "environment":"test","endpoint":"http://127.0.0.1:18081","network_calls":3,
                "credential_value_persisted":False,"account_values_persisted":False,
                "requests":[{"path":path,"method":"GET","http_status":200,"response_shape":"object",
                    "response_sha256":"fixture-redacted-hash"} for path in ALLOWED_GET_PATHS]}
        parent.show(); self.app.processEvents()
        with patch.object(broker_readonly,"check_read_only",side_effect=delayed_success):
            panel.readonly_check_button.click()
            self.assertTrue(panel.busy)
            self.assertFalse(panel.readonly_check_button.isEnabled())
            self.assertFalse(parent.close(),"the ProductWorkbench parent close must be intercepted while the worker lives")
            self.assertTrue(parent.isVisible())
            self._wait(lambda:not panel.busy)
        self.assertTrue(timer_fired,"GUI timer should run while the fake transport is delayed")
        self.assertEqual(json.loads(panel.readonly_receipt.read_text(encoding="utf-8"))["status"],"CONNECTED_READ_ONLY")
        parent.close(); self.app.processEvents()

    def test_read_only_result_is_discarded_if_config_changes_during_worker(self):
        import time
        from unittest.mock import patch
        from framework_v2 import broker_readonly
        panel=BrokerResearchPanel(self.root,language="ja_JP")
        folder=self.root/"stale-config"; panel.workspace_edit.setText(str(folder)); self.assertTrue(panel.save_config())
        def delayed_success(config,*,timeout):
            time.sleep(.08)
            return {"schema":"kabuforge_broker_read_only_check","status":"CONNECTED_READ_ONLY",
                "environment":"test","endpoint":"http://127.0.0.1:18081","network_calls":3,
                "credential_value_persisted":False,"account_values_persisted":False,
                "requests":[{"path":path,"method":"GET","http_status":200,"response_shape":"object",
                    "response_sha256":"fixture-redacted-hash"} for path in ALLOWED_GET_PATHS]}
        try:
            with patch.object(broker_readonly,"check_read_only",side_effect=delayed_success):
                panel.readonly_check_button.click(); self.assertTrue(panel.busy)
                panel.credential_ref.setText("env:KABU_CHANGED")
                self._wait(lambda:not panel.busy)
            self.assertIsNone(panel.readonly_receipt)
            failure=json.loads(panel.failure_receipt.read_text(encoding="utf-8"))
            self.assertEqual(failure["error_code"],"stale_configuration")
            self.assertEqual(failure["disposition"],"discarded_stale_result")
            self.assertEqual(failure["network_calls"],3)
            self.assertEqual(failure["attempted_get_paths"],list(ALLOWED_GET_PATHS))
            self.assertNotIn("account_id",failure)
            self.assertIn("古い結果を破棄",panel.status.text())
            self.assertFalse(panel.readonly_check_button.isEnabled())
            panel.set_language("en_US")
            self.assertIn("stale result was discarded",panel.status.text())
        finally:
            panel.close(); self.app.processEvents()

    def test_product_mounts_localized_tabs_and_guards_real_paper_thread_on_close(self):
        dates=["2021-01-04","2021-01-05","2021-01-06","2021-01-07"]
        orders=[{"signal_date":dates[0],"execution_date":dates[1],"code":"4502","side":"buy","quantity":10.0,"sizing_price":10.0}]
        manifest,report=_workspace_inputs(self.root/"source",dates,orders)
        report_copy=self.root/"report-copy.json"; report_copy.write_bytes(report.read_bytes())
        with patch("framework_v2.data_connection.load_api_key",return_value=None):
            window=ProductWorkbench(self.root/"product-workspace")
        window.show(); self.app.processEvents()
        panel=window.historical_paper_panel
        panel.set_inputs(manifest,report,hashlib.sha256(report.read_bytes()).hexdigest())
        panel.workspace_edit.setText(str(self.root/"product-paper-account"))
        from framework_v2.historical_paper_research import create_historical_paper_research as real_create
        def delayed_create(*args,**kwargs):
            time.sleep(.2)
            return real_create(*args,**kwargs)
        try:
            window.set_language("ja_JP")
            self.assertEqual(window.paper_tabs.tabText(0),"ローカル履歴リプレイ")
            self.assertEqual(window.broker_tabs.tabText(0),"オフライン注文マッピング")
            with patch("framework_v2.historical_paper_research.create_historical_paper_research",side_effect=delayed_create):
                self.assertTrue(panel.create_account())
                self.assertFalse(panel.set_inputs(manifest,report_copy,hashlib.sha256(report_copy.read_bytes()).hexdigest()))
                window.close(); self.app.processEvents()
                self.assertTrue(window.isVisible())
                self._wait(lambda:not panel.busy)
            self.assertTrue(panel._input_changed)
            self.assertIn("元の入力",panel.identity.text())
            self.assertTrue((Path(panel.operation_log.text())/"request.json").is_file())
            self.assertTrue((Path(panel.operation_log.text())/"launch.json").is_file())
            self.assertTrue((Path(panel.operation_log.text())/"result.json").is_file())
            self.assertTrue((Path(panel.operation_log.text())/"exit.json").is_file())
            window.close(); self.app.processEvents(); self.assertFalse(window.isVisible())
        finally:
            if panel.busy: self._wait(lambda:not panel.busy)
            if window.isVisible(): window.close(); self.app.processEvents()


if __name__=="__main__": unittest.main()
