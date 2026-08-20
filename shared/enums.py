from dataclasses import dataclass
from enum import StrEnum
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Asia/Nicosia")


class Side(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class Outcome(StrEnum):
    TP = "TP"
    SL = "SL"
    TIME = "TIME"
    END = "END"
    AMBIGUOUS = "AMBIGUOUS"


class RsiCross(StrEnum):
    UP = "up"
    DOWN = "down"


class Symbol(StrEnum):
    """ Perps only! USDT only! """

    BTC = "BTC"
    ETH = "ETH"
    SOL = "SOL"
    DOGE = "DOGE"
    XAU = "XAU"
    BNB = "BNB"
    XPL = "XPL"
    XRP = "XRP"
    AVAX = "AVAX"
    TAO = "TAO"
    HYPE = "HYPE"

    @property
    def usdt_pair(self) -> str:
        return f"{self}USDT"

    @property
    def okx_repr(self) -> str:
        return f"{self}-USDT-SWAP"


@dataclass(slots=True)
class Band:
    """
    Generic class used for ranges.
    Easier to use for settings like RSI [25,75] or RVOL.
    """
    low: int | float
    high: int | float

    # alias
    @property
    def min(self) -> int | float:
        return self.low

    # alias
    @property
    def max(self) -> int | float:
        return self.high

    # alias
    @property
    def start(self) -> int | float:
        return self.low

    # alias
    @property
    def end(self) -> int | float:
        return self.high

    def __str__(self) -> str:
        return f"[{self.low}-{self.high}]"

    def is_inside(self, value) -> bool:
        return self.min <= value <= self.max

    def is_outside(self, value) -> bool:
        return not self.is_inside(value)
