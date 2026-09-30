"""In-memory integration of installed legacy factors with the strict PIT view.

No cache path is ever resolved. This distribution imports only the public repository factor modules.
Private implementation identities are never automatically substituted.
"""
from __future__ import annotations
import hashlib
import inspect
import math
from pathlib import Path
from typing import Mapping, Callable
import pandas as pd
import numpy as np
from runtime.historical_data import JpxHistoricalProvider, LocalDataPaths
from runtime.topix_pool_runtime import HistoricalDataProvider
from .factors import FactorContext, FactorContractError, FactorSpec
from .legacy_factors import LegacyFactorRegistry, LegacyFactorAdapter, LEGACY_CONTRACTS

NUMERIC_FIELDS = frozenset({
    "open", "high", "low", "close", "volume", "adjustment_factor", "adjustment_open",
    "adjustment_high", "adjustment_low", "adjustment_close", "market_cap", "shares_outstanding",
    "total_revenue", "gross_profit", "operating_income", "ebit", "ebitda", "net_income",
    "total_assets", "stockholders_equity", "total_debt", "cash_and_cash_equivalents",
    "operating_cash_flow", "free_cash_flow", "margin_buy_balance", "margin_sell_balance",
    "margin_buy_change", "margin_sell_change",
})
REQUIRED_DATASETS = {
    "quality": ("financial_summary", "market_cap"),
    "value": ("financial_summary", "market_cap"),
    "residual_momentum": ("prices", "index_prices"),
    "dual_ma": ("prices",), "reversal": ("prices",),
    "attention": ("prices", "market_cap"),
    "behaviour": ("prices", "margin", "market_cap"),
}

def _legacy_date(value):
    stamp = pd.Timestamp(value)
    return stamp.tz_convert("Asia/Tokyo").tz_localize(None) if stamp.tzinfo else stamp

class PITLegacyProvider(JpxHistoricalProvider):
    """Reuse the installed provider's calculations, replacing all file access.

    Financial CSV strings are explicitly coerced here under the v2 adapter's
    identity. This repairs the old CSV dtype boundary, without changing the
    archived legacy baseline or its missing-value expectations.
    """
    def __init__(self, context: FactorContext):
        super().__init__(paths=LocalDataPaths(data_dir="<memory-only>"))
        self.context = context

    def _resolve_path(self, name):
        raise FactorContractError("PIT provider cannot resolve filesystem data")

    def table(self, name, *, required=True, copy=True):
        # Optional data is still explicit: missing capabilities do not trigger
        # a filesystem/network fallback.
        frame = self.context.read(name)
        if name == "financial_summary" and "source_disclosed_at" in frame:
            from .financial_events import latest_visible_financial_events
            frame = latest_visible_financial_events(frame, self.context.decision_at)
        for column in ("date", "asof_date", "disclosed_date"):
            if column in frame:
                frame[column] = frame[column].map(_legacy_date)
        for column in NUMERIC_FIELDS.intersection(frame.columns):
            try:
                frame[column] = pd.to_numeric(frame[column], errors="raise")
            except (TypeError, ValueError) as exc:
                raise FactorContractError(f"nonnumeric {name}.{column}") from exc
        return frame

def installed_public_runners() -> dict[str, Callable]:
    """Explicit imports of the existing public repository factors only."""
    from factors.fundamental_factor_runtime import run_quality_factor, run_value_factor
    from factors.residual_momentum_factor_runtime import run_residual_momentum_factor
    from factors.dual_ma_factor_runtime import run_dual_ma_factor
    from factors.reversal_factor_runtime import run_reversal_factor
    from factors.attention_factor_runtime import run_attention_factor
    from factors.behaviour_factor_runtime import run_behaviour_factor
    return dict(quality=run_quality_factor, value=run_value_factor,
        residual_momentum=run_residual_momentum_factor, dual_ma=run_dual_ma_factor,
        reversal=run_reversal_factor, attention=run_attention_factor, behaviour=run_behaviour_factor)

def source_version(function: Callable) -> str:
    path = inspect.getsourcefile(function)
    if path is None:
        raise FactorContractError("legacy runner requires inspectable installed source")
    dependencies = [Path(path), Path(inspect.getsourcefile(JpxHistoricalProvider)),
        Path(inspect.getsourcefile(HistoricalDataProvider)),
        Path(__file__),Path(__file__).with_name("legacy_factors.py"),Path(__file__).with_name("factors.py"),
        Path(__file__).with_name("financial_events.py")]
    digest=hashlib.sha256()
    digest.update(f"numpy:{np.__version__};pandas:{pd.__version__};".encode())
    for item in sorted(set(dependencies),key=lambda p:p.name):
        digest.update(item.name.encode()); digest.update(b"\0"); digest.update(item.read_bytes()); digest.update(b"\0")
    return "sha256:" + digest.hexdigest()

def validate_parameters(function, parameters):
    """Validate the installed implementation's declared defaults, not JSON code."""
    module=inspect.getmodule(function)
    defaults=getattr(module,"DEFAULT_CONFIG",None)
    if defaults is None and hasattr(module,"ResidualMomentumParams"):
        from dataclasses import asdict
        defaults=asdict(module.ResidualMomentumParams())
        defaults["market_benchmark"]=module.MARKET_BENCHMARK
    if defaults is None:
        raise FactorContractError("installed implementation lacks parameter declarations")
    forbidden={"mode","data_source","allow_yfinance_fallback","save_minimal_path","save_detail_path",
        "request_pause_sec","retry_count","statement_frequency"}
    allowed=set(defaults)-forbidden
    if set(parameters)-allowed:
        raise FactorContractError(f"unknown or reserved factor parameters: {sorted(set(parameters)-allowed)}")
    effective={**defaults,**parameters}
    for key,value in parameters.items():
        default=defaults[key]
        if isinstance(default,bool): valid=type(value) is bool
        elif isinstance(default,int): valid=type(value) is int and value>=0
        elif isinstance(default,float): valid=type(value) in (int,float) and math.isfinite(value) and value>=0
        elif isinstance(default,str): valid=isinstance(value,str) and bool(value)
        elif isinstance(default,(tuple,list)): valid=isinstance(value,(tuple,list)) and all(isinstance(v,str) and v for v in value)
        else: valid=False
        if not valid: raise FactorContractError("invalid factor parameter: "+key)
        if ("window" in key or key in {"min_reg_obs","history_buffer_calendar_days","lookback_weeks"}) and value<=0:
            raise FactorContractError("positive factor window required: "+key)
    for low,high in (("winsor_lower","winsor_upper"),("winsor_lower_q","winsor_upper_q")):
        if low in effective and not 0<=effective[low]<effective[high]<=1:
            raise FactorContractError("invalid winsor bounds")
    if "temperature" in effective and effective["temperature"]<=0: raise FactorContractError("temperature must be positive")

def _single_price_loader(context):
    provider = PITLegacyProvider(context)
    def load(ticker, start, end, config):
        normalized = str(ticker)[:4] if str(ticker)[:4].isdigit() else str(ticker)
        frame = provider.price_frame([normalized], start, end)
        if frame.empty:
            return pd.DataFrame()
        frame = frame.rename(columns={"date":"Date", "open":"Open", "high":"High",
            "low":"Low", "close":"Close", "volume":"Volume"})
        return frame.set_index("Date")[["Open", "High", "Low", "Close", "Volume"]].sort_index()
    return load

class BuiltinFactors:
    """Actual seven-factor integration with content-versioned implementations."""
    def __init__(self, *, runners: Mapping[str, Callable] | None = None, family="public"):
        if family not in {"private", "public"}:
            raise FactorContractError("unknown implementation family")
        if family != "public":
            raise FactorContractError("this distribution installs public factors only")
        self.runners = dict(installed_public_runners() if runners is None else runners)
        if set(self.runners) != set(LEGACY_CONTRACTS):
            raise FactorContractError("exactly seven explicit legacy runners are required")
        self.registry = LegacyFactorRegistry()
        self.versions = {}
        self.names = {}
        for name, function in self.runners.items():
            implementation = f"{family}.{name}"
            if family == "public" and name == "residual_momentum": implementation = "public.momentum_12_1"
            version = source_version(function)
            register = self.registry.register_runner if family == "private" else self.registry.register_public_runner
            register(name, version, function)
            self.versions[implementation] = version
            self.names[implementation] = name
        methods = {"fundamental_loader":"load_fundamental_panel", "close_loader":"load_close_prices",
            "price_loader":"load_price_history", "panel_price_loader":"load_price_history",
            "attention_loader":"load_attention_inputs", "behaviour_loader":"load_behaviour_inputs"}
        for capability, method in methods.items():
            self.registry.register_loader(capability, lambda ctx, method=method:getattr(PITLegacyProvider(ctx),method))
        self.adapter = LegacyFactorAdapter(self.registry)

    def validate_spec(self, spec: FactorSpec):
        if spec.implementation_id not in self.names:
            raise FactorContractError("implementation not installed in this factor family")
        self.registry._require_binding(spec)
        name = self.names[spec.implementation_id]
        validate_parameters(self.runners[name],spec.config["implementation"]["parameters"])
        declared = {item["dataset"] for item in spec.config["data_requirements"]}
        required = set(REQUIRED_DATASETS[name])
        if not required.issubset(declared):
            raise FactorContractError(f"undeclared data requirements: {sorted(required-declared)}")
        return name

    def compute(self, spec: FactorSpec, context: FactorContext):
        name=self.validate_spec(spec)
        for item in spec.config["data_requirements"]:
            context.read(item["dataset"], fields=tuple(item["fields"]))
        # Reversal uses a single-ticker price-loader fallback, distinct from
        # dual_ma's panel-loader signature. Its panel path is always provided.
        runner, config = self.registry.bind(spec, context)
        if name == "reversal": config["price_loader"] = _single_price_loader(context)
        from .factors import FactorResult
        result = runner(universe=context.universe(), rebalance_date=config["rebalance_date"], config=config)
        binding = self.registry._require_binding(spec)
        return FactorResult.from_legacy_dict(result, factor_id=binding.result_name, binding_id=spec.id)
