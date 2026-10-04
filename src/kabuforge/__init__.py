"""KabuForge local integration API (release candidate)."""
from __future__ import annotations

__version__ = "0.1.0rc2"

# Facade modules preserve contract class identity across compatibility imports.

from framework_v2.strategy_registry import (CompositeFactorStrategyAdapter, Strategy,
                                StrategyRegistry, StrategySpec)

__all__ = ["ApplicationService", "CompositeFactorStrategyAdapter", "Strategy",
           "StrategyRegistry", "StrategySpec", "__version__"]


def __getattr__(name: str):
    """Load application services only when a local source integration requests them."""
    if name == "ApplicationService":
        from framework_v2.application import ApplicationService
        return ApplicationService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
