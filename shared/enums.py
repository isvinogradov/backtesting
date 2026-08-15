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
