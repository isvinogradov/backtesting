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

    @property
    def usdt_pair(self) -> str:
        return f"{self}USDT"

    @property
    def okx_repr(self) -> str:
        return f"{self}-USDT-SWAP"
