import logging
import sys
import time
from abc import ABC, abstractmethod

from shared.api.bybit import BybitAPIClient

from shared.enums import Side

logging.basicConfig(
    format='%(asctime)s %(name)s[%(levelname)s]: %(message)s',
    level=logging.INFO,
    stream=sys.stdout,
)
logging.Formatter.converter = time.gmtime
log = logging.getLogger("BaseExitStrategy")


class BaseExitStrategy(ABC):
    """
    The goal of exit strategy is to determine TP and SL for position
    """

    def __init__(self, api) -> None:
        self.api: BybitAPIClient = api  # Bybit API client

    @abstractmethod
    async def get_tp_sl(self, for_side: Side) -> tuple[float, float]:
        pass
