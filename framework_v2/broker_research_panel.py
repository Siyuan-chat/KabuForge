"""Offline broker configuration and pure cash-order mapping preview UI."""
from __future__ import annotations

import json
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from PySide6.QtCore import QDateTime, QEvent, QTime, QThread, Signal
from PySide6.QtWidgets import (QComboBox, QDateTimeEdit, QDoubleSpinBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox,
    QTextEdit, QVBoxLayout, QWidget)


_TEXT={
 "zh_CN":{"title":"券商映射预览 · 离线","intro":"本页只保存本地连接配置和凭证引用，并执行纯本地订单字段映射。保存不连接；不读取/生成 token、不查询报价、不提交或撤单。历史连续股必须由用户另填合规整手，绝不自动取整。","env":"环境","prod":"生产 · localhost:18080","test":"测试 · localhost:18081","account":"本地账户标签","account_type":"账户类型","general":"一般账户","specified":"特定账户","exchange":"交易所","sor":"SOR","tokyo":"东京+","credential":"凭证引用（不解析）","workspace":"独立配置目录","choose":"选择父目录…","save":"保存离线配置","code":"标的代码","side":"方向","buy":"买入","sell":"卖出","quantity":"订单数量（整手）","lot":"整手股数","tick":"最小价位","type":"订单类型","market":"市价","limit":"限价","limit_price":"限价","price":"估算价格","fee":"估算费用","clock":"映射预览时钟（东京）","preview":"生成本地映射预览","status":"尚未保存配置。此处不连接终端。","blocked":"预览被阻断：","saved":"配置已保存。终端未连接，凭证引用未读取。","mapped":"本地映射完成；未连接、未提交、网络调用 0。","config_dirty":"设置已更改。请选择新的隔离目录并保存，再生成预览。","preview_dirty":"订单字段已变化，请重新生成本地映射。","bad_workspace":"配置目录必须是一个新目录。","config_saved":"配置已就绪（仅凭证引用）。","mapped_request":"映射请求与本地回执","read_only":"终端只读连接检查未在离线预览中运行。行情查询可能注册标的；需用户明确触发且单独实现。","no_secret":"严禁在此输入 token 或密码；仅填既有引用，如 env:KABU_TOKEN。","lot_block":"数量必须为整手的正整数倍。"},
 "ja_JP":{"title":"証券会社注文マッピング · オフライン","intro":"ローカル接続設定と資格情報参照のみを保存し、注文項目をローカルでマッピングします。保存時に接続せず、token 読取/発行、板照会、発注、取消は行いません。連続株数を自動で単元株へ丸めません。","env":"環境","prod":"本番 · localhost:18080","test":"検証 · localhost:18081","account":"ローカル口座ラベル","account_type":"口座種別","general":"一般","specified":"特定","exchange":"取引所","sor":"SOR","tokyo":"東証+","credential":"資格情報参照（解決しない）","workspace":"隔離設定ディレクトリ","choose":"親ディレクトリ…","save":"オフライン設定を保存","code":"銘柄コード","side":"売買","buy":"買い","sell":"売り","quantity":"注文数量（単元株）","lot":"売買単位","tick":"呼値","type":"注文種別","market":"成行","limit":"指値","limit_price":"指値価格","price":"見積価格","fee":"見積手数料","clock":"マッピング時刻（東京）","preview":"ローカルマッピングを作成","status":"未保存。端末には接続しません。","blocked":"プレビューを中止しました：","saved":"設定を保存しました。未接続、資格情報参照も未読込です。","mapped":"ローカルマッピング完了。未接続・未発注・通信 0 回。","config_dirty":"設定を変更しました。新しい隔離ディレクトリに保存してからプレビューしてください。","preview_dirty":"注文項目が変わりました。ローカルマッピングを再作成してください。","bad_workspace":"設定先は新しいディレクトリである必要があります。","config_saved":"設定を準備しました（資格情報参照のみ）。","mapped_request":"マッピング要求とローカル記録","read_only":"オフライン画面では端末の読み取り専用確認を行いません。板照会が銘柄登録する場合があるため、明示操作と別実装が必要です。","no_secret":"token/パスワードを入力しないでください。env:KABU_TOKEN のような既存参照のみです。","lot_block":"数量は売買単位の正の整数倍が必要です。"},
 "en_US":{"title":"Broker mapping preview · Offline","intro":"Save local connection settings and a credential reference only, then map order fields locally. Saving does not connect. No token read/creation, quote lookup, submission, or cancellation occurs. Fractional research shares are never rounded into board lots.","env":"Environment","prod":"Production · localhost:18080","test":"Test · localhost:18081","account":"Local account label","account_type":"Account type","general":"General","specified":"Specified","exchange":"Exchange","sor":"SOR","tokyo":"Tokyo+","credential":"Credential reference (not resolved)","workspace":"Isolated config directory","choose":"Choose parent…","save":"Save offline config","code":"Instrument code","side":"Side","buy":"Buy","sell":"Sell","quantity":"Order quantity (board lots)","lot":"Board-lot size","tick":"Minimum tick","type":"Order type","market":"Market","limit":"Limit","limit_price":"Limit price","price":"Estimated price","fee":"Estimated fee","clock":"Mapping preview clock (Tokyo)","preview":"Create local mapping preview","status":"No configuration saved. This page does not connect to a terminal.","blocked":"Preview blocked: ","saved":"Configuration saved. Terminal is not connected; credential reference was not read.","mapped":"Local mapping completed; not connected, not submitted, network calls 0.","config_dirty":"Settings changed. Save a new isolated configuration before previewing.","preview_dirty":"Order inputs changed. Create a new local mapping preview.","bad_workspace":"Configuration must use a new directory.","config_saved":"Configuration ready (reference only).","mapped_request":"Mapped request and local receipt","read_only":"A read-only terminal check is not run in this offline preview. Quote lookup may register an instrument and would require an explicit user action and a separate implementation.","no_secret":"Never enter a token or password here; use an existing reference such as env:KABU_TOKEN.","lot_block":"Quantity must be a positive multiple of the board-lot size."},
}

_READONLY_TEXT = {
 "zh_CN": {"intro":"本页保存本地连接配置/凭证引用，并执行纯本地订单映射。保存不连接；离线映射不查询、不提交、不撤单。单独点击只读检查后才读取已存在的 token 引用，并仅 GET 现金余额/持仓/订单；不会发 token POST、查报价板或交易。连续股不自动取整手。","readonly_check":"显式只读连接检查","readonly_wait":"正在后台用已保存引用执行只读 GET（每次 I/O 超时 2 秒）…","readonly_connected":"只读连接成功：现金、持仓、订单 GET 均返回 HTTP 200。响应账户明细未写入日志。","readonly_failed":"只读检查未完成：","readonly_stale":"检查期间配置已变化，旧结果已丢弃。请保存后重新检查。","readonly_busy":"只读检查仍在后台运行，请等待完成后再关闭。","readonly_dirty":"配置已更改。请先在新的隔离目录保存，再执行只读检查。","readonly_log":"只读检查记录","read_only":"只读检查仅 GET localhost /kabusapi/wallet/cash、/kabusapi/positions、/kabusapi/orders；不读报价板，不发 token、不提交或撤单。变更配置后需重新保存。响应账户金额不会写入日志。"},
 "ja_JP": {"intro":"ローカル設定と資格情報参照を保存し、注文項目をローカルでマッピングします。保存時は接続しません。別ボタンの読み取り専用確認でのみ既存tokenを参照し、現金・保有・注文のGETを行います。token POST、板照会、発注、取消は行いません。連続株を単元株へ丸めません。","readonly_check":"明示的な読み取り専用確認","readonly_wait":"保存済み参照でバックグラウンドGETを確認中（各I/Oタイムアウト2秒）…","readonly_connected":"読み取り専用接続成功：現金・保有・注文のGETがすべてHTTP 200。口座詳細はログに保存していません。","readonly_failed":"読み取り確認に失敗：","readonly_stale":"確認中に設定が変更されたため、古い結果を破棄しました。保存後に再確認してください。","readonly_busy":"読み取り確認を実行中です。完了後に閉じてください。","readonly_dirty":"設定が変更されています。新しい隔離先に保存してから確認してください。","readonly_log":"読み取り確認ログ","read_only":"明示操作のみlocalhostの /kabusapi/wallet/cash、/kabusapi/positions、/kabusapi/ordersへGETします。板、token発行、発注、取消は行いません。口座金額はログに保存しません。"},
 "en_US": {"intro":"Save local connection settings and a credential reference, then map orders locally. Saving does not connect. Only the separate explicit read-only action resolves the existing token reference and performs GET-only cash/positions/orders requests. No token creation, board lookup, submission, or cancellation occurs. Fractional shares are never rounded into board lots.","readonly_check":"Explicit read-only terminal check","readonly_wait":"Running background GET-only checks (2-second timeout per I/O)…","readonly_connected":"Read-only connection succeeded: cash, positions, and orders all returned HTTP 200. Account details were not written to logs.","readonly_failed":"Read-only check failed: ","readonly_stale":"Configuration changed during the check; the stale result was discarded. Save before checking again.","readonly_busy":"The read-only check is still running. Wait for it to finish before closing.","readonly_missing":"Credential reference is empty or unavailable. No network request was sent.","readonly_dirty":"Configuration changed. Save a new isolated configuration before checking.","readonly_log":"Read-only check log","read_only":"Only an explicit action sends GET to localhost /kabusapi/wallet/cash, /kabusapi/positions, and /kabusapi/orders. No board, token-creation, submission, or cancellation calls occur. Response account amounts are not logged."},
}
for _locale, _overrides in _READONLY_TEXT.items():
    _TEXT[_locale].update(_overrides)

_ERROR_TEXT = {
 "zh_CN":{"credential_missing":"凭证引用不存在或为空。未发出网络请求。","unsupported_credential_reference":"此凭证管理器引用目前无法安全解析。未发出网络请求。","invalid_credential_reference":"凭证引用格式无效。未发出网络请求。","endpoint_not_allowlisted":"端点不符合本环境固定 localhost 白名单。","localhost_connection_failed":"无法连接到本机终端。","request_timeout":"本机只读请求超时。","http_status_not_ok":"至少一个只读 GET 未返回 HTTP 200。","redirect_blocked":"检测到重定向，已阻止请求。","response_json_invalid":"终端返回内容不是有效 JSON。","response_error":"终端返回了错误响应。","response_shape_invalid":"终端返回结构不受支持。","response_too_large":"终端响应超过大小限制。","timeout_out_of_range":"请求超时配置超出安全范围。","invalid_saved_configuration":"保存的连接配置无效。","credential_resolution_failed":"无法解析凭证引用。","credential_invalid":"凭证格式不支持。","response_too_large_or_invalid":"响应大小或类型无效。","preview_rejected":"本地订单映射未通过校验。","config_save_failed":"离线配置未能保存。","dirty_configuration":"请先重新保存变更后的配置。"},
 "ja_JP":{"credential_missing":"資格情報参照が空または存在しません。要求は送信していません。","unsupported_credential_reference":"この資格情報参照方式は安全に解決できません。要求は送信していません。","invalid_credential_reference":"資格情報参照の形式が無効です。要求は送信していません。","endpoint_not_allowlisted":"環境固有のlocalhost許可リスト外です。","localhost_connection_failed":"ローカル端末に接続できません。","request_timeout":"ローカル読み取り要求がタイムアウトしました。","http_status_not_ok":"GETの一部がHTTP 200を返しませんでした。","redirect_blocked":"リダイレクトを検出し、要求を停止しました。","response_json_invalid":"端末の応答は有効なJSONではありません。","response_error":"端末がエラー応答を返しました。","response_shape_invalid":"端末の応答形式は未対応です。","response_too_large":"端末の応答サイズ上限を超えました。","timeout_out_of_range":"タイムアウト設定が安全な範囲外です。","invalid_saved_configuration":"保存済み設定が無効です。","credential_resolution_failed":"資格情報参照を解決できません。","credential_invalid":"資格情報の形式が無効です。","response_too_large_or_invalid":"応答サイズまたは形式が無効です。","preview_rejected":"ローカル注文マッピングの検証に失敗しました。","config_save_failed":"オフライン設定を保存できませんでした。","dirty_configuration":"変更後の設定を保存してください。"},
 "en_US":{"credential_missing":"Credential reference is empty or unavailable. No request was sent.","unsupported_credential_reference":"This credential-manager reference cannot be resolved safely. No request was sent.","invalid_credential_reference":"Credential reference format is invalid. No request was sent.","endpoint_not_allowlisted":"Endpoint is outside the fixed localhost environment allowlist.","localhost_connection_failed":"Could not connect to the local terminal.","request_timeout":"A local read-only request timed out.","http_status_not_ok":"At least one read-only GET did not return HTTP 200.","redirect_blocked":"A redirect was detected and blocked.","response_json_invalid":"Terminal returned invalid JSON.","response_error":"The terminal returned an API error response.","response_shape_invalid":"Terminal response shape is unsupported.","response_too_large":"Terminal response exceeded the size limit.","timeout_out_of_range":"Configured request timeout is outside the safe range.","invalid_saved_configuration":"Saved connection configuration is invalid.","credential_resolution_failed":"Credential reference could not be resolved.","credential_invalid":"Credential value format is invalid.","response_too_large_or_invalid":"Response size or type is invalid.","preview_rejected":"Local order mapping did not pass validation.","config_save_failed":"Offline configuration could not be saved.","dirty_configuration":"Save the changed configuration first."}
}


class _ReadOnlyCheckThread(QThread):
    outcome = Signal(object, int, object)

    def __init__(self, config, timeout, generation):
        super().__init__()
        self.config = config
        self.timeout = timeout
        self.generation = generation

    def run(self):
        from .broker_readonly import BrokerReadOnlyError, check_read_only
        try:
            self.outcome.emit(self, self.generation, {"ok": True, "result": check_read_only(self.config, timeout=self.timeout)})
        except BrokerReadOnlyError as exc:
            self.outcome.emit(self, self.generation, {"ok": False, "code": exc.code, "attempted_paths": list(exc.attempted_paths)})
        except Exception:
            self.outcome.emit(self, self.generation, {"ok": False, "code": "localhost_connection_failed", "attempted_paths": []})


class BrokerResearchPanel(QGroupBox):
    """Pure local config/mapping flow; the panel has no network or credential APIs."""
    def __init__(self,workspace: str|Path,language="zh_CN",parent=None):
        super().__init__(parent); self.root=Path(workspace).resolve(); self.language=language if language in _TEXT else "zh_CN"
        self.config_workspace:Path|None=None; self.config=None; self.last_receipt=None; self.readonly_receipt=None; self.failure_receipt=None
        self._busy=False; self._generation=0; self._readonly_thread=None; self._readonly_outcome=None
        self._readonly_operation=None; self._readonly_request_sha=None; self._readonly_config=None
        self._failure_detail=""; self._failure_code=None; self._failure_kind=None
        self._last_action=None; self._config_dirty=False
        self.setProperty("ownTranslation",True)
        layout=QVBoxLayout(self); self.intro=QLabel(); self.intro.setWordWrap(True); layout.addWidget(self.intro)
        form=QFormLayout(); layout.addLayout(form); self._labels={}
        self.environment=QComboBox(); self.environment.addItem("", "production"); self.environment.addItem("", "test")
        self.account_id=QLineEdit("teaching-cash-account")
        self.account_type=QComboBox(); self.account_type.addItem("",2); self.account_type.addItem("",4)
        self.exchange=QComboBox(); self.exchange.addItem("",9); self.exchange.addItem("",27)
        self.environment.setCurrentIndex(1)
        self.credential_ref=QLineEdit("env:KABU_TOKEN"); self.credential_ref.setEchoMode(QLineEdit.EchoMode.Normal)
        self.credential_hint=QLabel(); self.credential_hint.setWordWrap(True)
        self.workspace_edit=QLineEdit(); self.workspace_edit.setReadOnly(True); self.workspace_button=QPushButton(); self.workspace_button.clicked.connect(self._choose_workspace)
        self._add_field(form,"env",self.environment); self._add_field(form,"account",self.account_id)
        self._add_field(form,"account_type",self.account_type); self._add_field(form,"exchange",self.exchange)
        self._add_field(form,"credential",self.credential_ref); form.addRow(self.credential_hint)
        self._add_field(form,"workspace",self._row(self.workspace_edit,self.workspace_button))
        self.save_button=QPushButton(); self.save_button.clicked.connect(self.save_config); form.addRow(self.save_button)
        self.code=QLineEdit("6758"); self.side=QComboBox(); self.side.addItem("", "buy"); self.side.addItem("", "sell")
        self.quantity=QSpinBox(); self.quantity.setRange(1,100000000); self.quantity.setValue(100)
        self.lot_size=QSpinBox(); self.lot_size.setRange(1,10000); self.lot_size.setValue(100)
        self.tick_size=self._decimal("1",0.0001,10000); self.order_type=QComboBox(); self.order_type.addItem("", "market"); self.order_type.addItem("", "limit")
        self.limit_price=self._decimal("1000",0.0001,100000000); self.estimated_price=self._decimal("1000",0.0001,100000000)
        self.estimated_fee=self._decimal("10",0,10000000); self.preview_clock=QDateTimeEdit(); self.preview_clock.setCalendarPopup(True); self.preview_clock.setDisplayFormat("yyyy-MM-dd HH:mm")
        preview_time=QDateTime.currentDateTime(); preview_time.setTime(QTime(10,30)); self.preview_clock.setDateTime(preview_time)
        self.order_fields={"code":self.code,"side":self.side,"quantity":self.quantity,"lot":self.lot_size,"tick":self.tick_size,"type":self.order_type,"limit_price":self.limit_price,"price":self.estimated_price,"fee":self.estimated_fee,"clock":self.preview_clock}
        for key,widget in self.order_fields.items(): self._add_field(form,key,widget)
        self.preview_button=QPushButton(); self.preview_button.clicked.connect(self.preview)
        self.readonly_check_button=QPushButton(); self.readonly_check_button.clicked.connect(self.check_read_only)
        self.status=QLabel(); self.status.setWordWrap(True)
        actions=QHBoxLayout(); actions.addWidget(self.preview_button); actions.addWidget(self.readonly_check_button); layout.addLayout(actions); layout.addWidget(self.status)
        self.mapping=QTextEdit(); self.mapping.setReadOnly(True); self.mapping.setMinimumHeight(180); layout.addWidget(self.mapping,1)
        self.set_language(self.language)
        if parent is not None:
            parent.installEventFilter(self)
        self.environment.currentIndexChanged.connect(self._config_changed)
        self.account_type.currentIndexChanged.connect(self._config_changed); self.exchange.currentIndexChanged.connect(self._config_changed)
        self.account_id.textChanged.connect(self._config_changed); self.credential_ref.textChanged.connect(self._config_changed)
        self.side.currentIndexChanged.connect(self._order_changed); self.order_type.currentIndexChanged.connect(self._order_changed)
        for widget in (self.code,self.quantity,self.lot_size,self.tick_size,self.limit_price,self.estimated_price,self.estimated_fee):
            signal=getattr(widget,"textChanged",None) or getattr(widget,"valueChanged",None)
            if signal is not None: signal.connect(self._order_changed)
        self.preview_clock.dateTimeChanged.connect(self._order_changed)
        self.preview_button.setEnabled(False)

    @staticmethod
    def _row(a,b):
        box=QWidget(); row=QHBoxLayout(box); row.setContentsMargins(0,0,0,0); row.addWidget(a,1); row.addWidget(b); return box

    def _add_field(self,form,key,widget):
        label=QLabel(); self._labels[key]=label; form.addRow(label,widget)

    @staticmethod
    def _decimal(value,low,high):
        w=QDoubleSpinBox(); w.setRange(low,high); w.setDecimals(4); w.setValue(float(value)); return w

    def set_language(self,language):
        self.language=language if language in _TEXT else "zh_CN"; t=_TEXT[self.language]; self.setTitle(t["title"]); self.intro.setText(t["intro"])
        for key,widget in self._labels.items(): widget.setText(t[key])
        self.environment.setItemText(0,t["prod"]); self.environment.setItemText(1,t["test"])
        self.account_type.setItemText(0,t["general"]); self.account_type.setItemText(1,t["specified"])
        self.exchange.setItemText(0,t["sor"]); self.exchange.setItemText(1,t["tokyo"])
        self.side.setItemText(0,t["buy"]); self.side.setItemText(1,t["sell"])
        self.order_type.setItemText(0,t["market"]); self.order_type.setItemText(1,t["limit"])
        self.workspace_button.setText(t["choose"]); self.save_button.setText(t["save"]); self.preview_button.setText(t["preview"])
        self.credential_hint.setText(t["no_secret"])
        self.readonly_check_button.setText(t["readonly_check"])
        if self._busy:
            self.status.setText(t["readonly_wait"])
        elif self._last_action=="readonly" and self._failure_code=="stale_configuration":
            self.status.setText(t["readonly_stale"])
        elif self._last_action=="readonly" and self._failure_code:
            self.status.setText(t["readonly_failed"]+_ERROR_TEXT[self.language].get(self._failure_code,self._failure_code))
        elif self._config_dirty:
            self.status.setText(t["config_dirty"])
        elif self._last_action=="readonly" and self.readonly_receipt:
            self.status.setText(t["readonly_connected"]+" · "+t["readonly_log"]+": "+str(self.readonly_receipt.parent))
        elif self._last_action=="preview" and self._failure_code=="invalid_lot":
            self.status.setText(t["blocked"]+t["lot_block"])
        elif self._last_action=="preview" and self._failure_code:
            self.status.setText(t["blocked"]+_ERROR_TEXT[self.language].get(self._failure_code,t["preview_dirty"]))
        elif self.last_receipt: self.status.setText(t["mapped"])
        elif self.config: self.status.setText(t["saved"])
        else: self.status.setText(t["status"])
        displayed=(self.readonly_receipt if self._last_action=="readonly" and self.readonly_receipt else
                   self.failure_receipt if self._failure_code and self.failure_receipt else self.last_receipt)
        if displayed:
            self.mapping.setPlainText(Path(displayed).read_text(encoding="utf-8"))
        elif self.config:
            self.mapping.setPlainText(t["config_dirty"] if self._config_dirty else t["read_only"])
        self.readonly_check_button.setEnabled(self.config is not None and not self._config_dirty and not self._busy)
        self.preview_button.setEnabled(self.config is not None and not self._config_dirty and not self._busy)

    def _choose_workspace(self):
        parent=QFileDialog.getExistingDirectory(self,_TEXT[self.language]["workspace"],str(self.root))
        if parent:
            path=Path(parent)/("broker-preview-"+uuid.uuid4().hex[:12]); self.workspace_edit.setText(str(path)); self.config_workspace=path

    def _config_from_form(self):
        from .broker_research import BrokerResearchConfig
        environment=self.environment.currentData(); endpoint="http://127.0.0.1:18080" if environment=="production" else "http://127.0.0.1:18081"
        return BrokerResearchConfig(environment,endpoint,self.account_id.text().strip(),int(self.account_type.currentData()),int(self.exchange.currentData()),self.credential_ref.text().strip())

    def _config_changed(self,*_):
        if self.config is None: return
        self._generation += 1
        try: self._config_dirty=self._config_from_form()!=self.config
        except Exception: self._config_dirty=True
        self.preview_button.setEnabled(not self._config_dirty and not self._busy)
        self.readonly_check_button.setEnabled(not self._config_dirty and not self._busy)
        if self._config_dirty:
            self.last_receipt=None; self.readonly_receipt=None; self.failure_receipt=None; self._failure_code=None; self._last_action=None
            self.mapping.setPlainText(_TEXT[self.language]["config_dirty"]); self.status.setText(_TEXT[self.language]["config_dirty"])
        elif self.last_receipt: self.status.setText(_TEXT[self.language]["mapped"])
        else: self.status.setText(_TEXT[self.language]["saved"])

    def _order_changed(self,*_):
        had_preview=self._last_action=="preview"
        if self.last_receipt:
            self.last_receipt=None; self.mapping.setPlainText(_TEXT[self.language]["preview_dirty"])
            self.status.setText(_TEXT[self.language]["preview_dirty"])
        elif had_preview:
            self.mapping.setPlainText(_TEXT[self.language]["preview_dirty"])
            self.status.setText(_TEXT[self.language]["preview_dirty"])
        if had_preview: self._last_action=None; self._failure_code=None
        self.preview_button.setEnabled(self.config is not None and not self._config_dirty)

    def save_config(self):
        from .broker_research import BrokerResearchConfig,create_broker_workspace
        try:
            config=self._config_from_form()
            target=Path(self.workspace_edit.text().strip()).expanduser().resolve()
            if not str(target) or target.exists(): raise ValueError(_TEXT[self.language]["bad_workspace"])
            create_broker_workspace(target,config); self.config_workspace=target; self.config=config; self._failure_detail=""; self._failure_code=None; self._failure_kind=None; self._last_action=None; self._config_dirty=False
            self.last_receipt=None; self.readonly_receipt=None; self.failure_receipt=None
            self.preview_button.setEnabled(True)
            self.readonly_check_button.setEnabled(True)
            self.status.setText(_TEXT[self.language]["saved"]); self.mapping.setPlainText(_TEXT[self.language]["read_only"])
            return True
        except Exception:
            self._failure_detail=""; self._failure_code="config_save_failed"; self._failure_kind="preview"; self._last_action="preview"
            self.status.setText(_TEXT[self.language]["blocked"]+_TEXT[self.language]["bad_workspace"]); return False

    def _intent_and_instrument(self):
        from .execution import Instrument,OrderIntent
        from datetime import timezone
        local=self.preview_clock.dateTime().toPython()
        now=local.replace(tzinfo=ZoneInfo("Asia/Tokyo"))
        if self.quantity.value()%self.lot_size.value(): raise ValueError(_TEXT[self.language]["lot_block"])
        kind=self.order_type.currentData(); limit=Decimal(str(self.limit_price.value())) if kind=="limit" else None
        valid_until=(now+timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0)
        intent=OrderIntent(intent_id=uuid.uuid4().hex,idempotency_key=uuid.uuid4().hex,account_id=self.account_id.text().strip(),
            account_revision="offline-preview",decision_identity="offline-teaching-preview",strategy_hash="offline-manual-preview-v1",
            code=self.code.text().strip(),side=self.side.currentData(),quantity=self.quantity.value(),order_type=kind,limit_price=limit,
            time_in_force="DAY",created_at=now,valid_until=valid_until,estimated_price=Decimal(str(self.estimated_price.value())),estimated_fee=Decimal(str(self.estimated_fee.value())))
        instrument=Instrument(self.code.text().strip(),self.lot_size.value(),Decimal(str(self.tick_size.value())))
        return intent,instrument,now

    def preview(self):
        from .broker_research import NoCallTransport,preview_order
        self._last_action="preview"; self._failure_code=None; self._failure_kind=None; self.last_receipt=None
        try:
            if self.config is None or self.config_workspace is None: raise ValueError("save an offline configuration first")
            if self._config_dirty: raise ValueError(_TEXT[self.language]["config_dirty"])
            intent,instrument,now=self._intent_and_instrument()
            guard=NoCallTransport(); path=preview_order(self.config_workspace,intent,instrument,now=now,transport=guard)
            receipt=json.loads(path.read_text(encoding="utf-8"))
            if guard.calls!=0 or receipt.get("credential_resolved") is not False or receipt.get("network_calls")!=0:
                raise RuntimeError("offline preview boundary check failed")
            self.last_receipt=path; self._failure_detail=""; self._failure_code=None; self._failure_kind=None; self.readonly_receipt=None; self.status.setText(_TEXT[self.language]["mapped"])
            self.mapping.setPlainText(json.dumps(receipt,ensure_ascii=False,indent=2))
            return path
        except Exception as exc:
            self.last_receipt=None; self._failure_detail=""; self._failure_kind="preview"; self.failure_receipt=None
            self._failure_code="invalid_lot" if ("lot" in str(exc).lower() or _TEXT[self.language]["lot_block"] in str(exc)) else "preview_rejected"
            self.status.setText(_TEXT[self.language]["blocked"]+(_TEXT[self.language]["lot_block"] if self._failure_code=="invalid_lot" else "Order mapping was rejected."))
            self.mapping.setPlainText(self.status.text())
            self.failure_receipt=self._write_local_failure(self._failure_code)
            return None

    def _write_local_failure(self, code: str):
        """Write a safe operation failure receipt without user values or secrets."""
        if self.config_workspace is None: return None
        try:
            operation=self.config_workspace/"mapping-failures"/uuid.uuid4().hex
            operation.mkdir(parents=True,exist_ok=False)
            request={"schema":"kabuforge_broker_mapping_failure","timestamp_utc":datetime.now(timezone.utc).isoformat(),
                "environment":self.config.environment if self.config else None,"action":"offline_mapping_preview",
                "secret_values_persisted":False,"policy":"redacted reason code only"}
            (operation/"request.json").write_text(json.dumps(request,ensure_ascii=False,indent=2),encoding="utf-8")
            result={"status":"BLOCKED","error_code":code,"details_redacted":True,
                "credential_value_persisted":False,"network_calls":0,"order_payload_persisted":False}
            (operation/"failure.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
            return operation/"failure.json"
        except OSError:
            return None

    def check_read_only(self):
        """Start the explicit GET-only check outside the GUI event loop."""
        if self._busy:
            return None
        self._last_action="readonly"; self._failure_code=None; self._failure_kind=None; self.failure_receipt=None
        if self.config is None or self.config_workspace is None or self._config_dirty:
            self._failure_code="dirty_configuration" if self.config is not None else "credential_missing"
            self._failure_kind="readonly"
            self.status.setText(_TEXT[self.language]["readonly_dirty"] if self.config is not None else _ERROR_TEXT[self.language]["credential_missing"])
            return None
        operation=self.config_workspace/"read-only-checks"/uuid.uuid4().hex
        operation.mkdir(parents=True,exist_ok=False)
        request={"schema":"kabuforge_broker_read_only_request","timestamp_utc":datetime.now(timezone.utc).isoformat(),
            "environment":self.config.environment,"endpoint":self.config.endpoint,
            "method":"GET","paths":["/kabusapi/wallet/cash","/kabusapi/positions","/kabusapi/orders"],
            "timeout_seconds_per_io":2.0,"credential_reference_present":bool(self.config.credential_ref),
            "credential_value_persisted":False,"redirects_allowed":False,"proxies_used":False}
        request_bytes=json.dumps(request,sort_keys=True,separators=(",",":"),allow_nan=False).encode("utf-8")
        (operation/"request.json").write_bytes(request_bytes)
        self._generation+=1; generation=self._generation; config=self.config
        self._readonly_operation=operation; self._readonly_request_sha=hashlib.sha256(request_bytes).hexdigest()
        self._readonly_config=config; self._readonly_outcome=None; self._busy=True
        self.status.setText(_TEXT[self.language]["readonly_wait"])
        for widget in (self.environment,self.account_id,self.account_type,self.exchange,self.credential_ref,
                       self.save_button,self.preview_button,self.readonly_check_button):
            widget.setEnabled(False)
        thread=_ReadOnlyCheckThread(config,2.0,generation); self._readonly_thread=thread
        thread.outcome.connect(self._read_only_outcome)
        thread.finished.connect(self._read_only_thread_finished)
        thread.start()
        return operation

    @property
    def busy(self):
        return bool(self._busy)

    def eventFilter(self,watched,event):
        if event.type()==QEvent.Type.Close and self._busy:
            event.ignore(); self.status.setText(_TEXT[self.language]["readonly_busy"])
            return True
        return super().eventFilter(watched,event)

    def closeEvent(self,event):
        if self._busy:
            event.ignore(); self.status.setText(_TEXT[self.language]["readonly_busy"]); return
        super().closeEvent(event)

    def _read_only_outcome(self,thread,generation,outcome):
        if thread is not self._readonly_thread: return
        if generation!=self._generation or self.config!=self._readonly_config or self._config_dirty:
            result=outcome.get("result",{}) if outcome.get("ok") else {}
            paths=outcome.get("attempted_paths",[]) if not outcome.get("ok") else [
                row.get("path") for row in result.get("requests",[]) if isinstance(row,dict) and row.get("path")]
            self._readonly_outcome={"ok":False,"code":"stale_configuration","attempted_paths":paths,
                "observed_network_calls":result.get("network_calls",len(paths)),
                "source_generation":generation,"current_generation":self._generation}
        else:
            self._readonly_outcome=outcome

    def _read_only_thread_finished(self):
        thread=self._readonly_thread
        if thread is not None:
            self._read_only_finished(thread,thread.generation)

    def _read_only_finished(self,thread,generation):
        if thread is not self._readonly_thread: return
        outcome=self._readonly_outcome or {"ok":False,"code":"localhost_connection_failed","attempted_paths":[]}
        operation=self._readonly_operation
        if outcome.get("ok"):
            result=dict(outcome["result"]); result["request_sha256"]=self._readonly_request_sha
            result_path=operation/"result.json"
            result_path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
            self.readonly_receipt=result_path; self.failure_receipt=None; self.last_receipt=None
            self._failure_code=None; self._failure_kind=None; self.mapping.setPlainText(result_path.read_text(encoding="utf-8"))
            self._last_action="readonly"
            self.status.setText(_TEXT[self.language]["readonly_connected"]+" · "+_TEXT[self.language]["readonly_log"]+": "+str(operation))
        else:
            code=outcome.get("code","localhost_connection_failed"); self.readonly_receipt=None; self.last_receipt=None
            self._failure_code=code; self._failure_kind="readonly"; self._last_action="readonly"
            failure={"schema":"kabuforge_broker_read_only_result","status":"CHECK_FAILED_REDACTED",
                "error_code":code,"details_redacted":True,"credential_value_persisted":False,
                "account_values_persisted":False,"attempted_get_paths":outcome.get("attempted_paths",[]),
                "network_calls":outcome.get("observed_network_calls",len(outcome.get("attempted_paths",[]))),
                "request_sha256":self._readonly_request_sha}
            if code=="stale_configuration":
                failure.update({"disposition":"discarded_stale_result","source_generation":outcome.get("source_generation"),
                    "current_generation":outcome.get("current_generation")})
            result_path=operation/"failure.json"
            result_path.write_text(json.dumps(failure,ensure_ascii=False,indent=2),encoding="utf-8")
            self.failure_receipt=result_path; self.mapping.setPlainText(json.dumps(failure,ensure_ascii=False,indent=2))
            if code=="stale_configuration":
                self.status.setText(_TEXT[self.language]["readonly_stale"]+" · "+_TEXT[self.language]["readonly_log"]+": "+str(operation))
            else:
                self.status.setText(_TEXT[self.language]["readonly_failed"]+_ERROR_TEXT[self.language].get(code,code)+" · "+_TEXT[self.language]["readonly_log"]+": "+str(operation))
        self._busy=False; self._readonly_thread=None; self._readonly_outcome=None
        for widget in (self.environment,self.account_id,self.account_type,self.exchange,self.credential_ref,self.save_button):
            widget.setEnabled(True)
        self.preview_button.setEnabled(self.config is not None and not self._config_dirty)
        self.readonly_check_button.setEnabled(self.config is not None and not self._config_dirty)
        thread.deleteLater()
