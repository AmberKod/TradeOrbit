"""Decimal-string read contracts; missing values remain unknown rather than zero."""

from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any


class PrivateReadError(Exception):
    """Contains only an internal allowlisted code, never exchange text or credentials."""

    def __init__(self, code: str, *, retry_after: int | None = None):
        super().__init__(code)
        self.code = code
        self.retry_after = retry_after


def decimal_string(value: Any, *, required: bool = False) -> str | None:
    if isinstance(value, bool) or len(str(value)) > 100:
        raise PrivateReadError("INVALID_RESPONSE")
    if value is None or value == "":
        if required:
            raise PrivateReadError("INVALID_RESPONSE")
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise PrivateReadError("INVALID_RESPONSE") from None
    if not number.is_finite() or abs(number.adjusted()) > 60:
        raise PrivateReadError("INVALID_RESPONSE")
    return format(number, "f")


def required_decimal(value: Any) -> str:
    result = decimal_string(value, required=True)
    assert result is not None
    return result


@dataclass
class Balance:
    asset: str
    equity: str | None
    available: str | None = None
    wallet_balance: str | None = None
    unrealized_pnl: str | None = None
    equity_definition: str = "exchange_reported"


@dataclass
class Position:
    instrument: str
    side: str
    quantity: str
    quantity_unit: str
    margin_asset: str | None = None
    entry_price: str | None = None
    mark_price: str | None = None
    liquidation_price: str | None = None
    unrealized_pnl: str | None = None
    leverage: str | None = None
    margin_ratio: str | None = None
    margin_ratio_definition: str | None = None
    margin_mode: str | None = None


@dataclass
class ScopeSnapshot:
    balances: list[Balance] = field(default_factory=list)
    positions: list[Position] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
