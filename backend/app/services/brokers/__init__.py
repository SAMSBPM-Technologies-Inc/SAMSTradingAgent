"""
Broker adapter registry.

`BROKER_PROVIDER` selects the execution venue at startup:
    ibkr    → Interactive Brokers via IB Gateway (default)
    alpaca  → Alpaca REST

Adding a venue means implementing `BrokerAdapter` and registering it here;
nothing in the signal, risk, or persistence layers needs to change.
"""
from app.services.brokers.base import (
    AccountSummary,
    BrokerAdapter,
    BrokerConfig,
    Position,
)

__all__ = [
    "AccountSummary",
    "BrokerAdapter",
    "BrokerConfig",
    "Position",
    "build_adapter",
]


def build_adapter(provider: str, config: BrokerConfig) -> BrokerAdapter:
    """Instantiate the adapter for `provider`. Unknown values fall back to IBKR."""
    key = (provider or "ibkr").strip().lower()

    if key == "alpaca":
        from app.services.brokers.alpaca import AlpacaAdapter
        return AlpacaAdapter(config)

    from app.services.brokers.ibkr import IbkrAdapter
    return IbkrAdapter(config)
