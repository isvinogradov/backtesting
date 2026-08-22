import logging
import sys
import time
from abc import abstractmethod, ABC
from datetime import datetime, timezone

from shared.api.bybit import BybitAPIClient
from shared.dbwriter import PostgresWriter
from shared.tg_notifier import TelegramNotifier

from shared.enums import Side

logging.basicConfig(
    format='%(asctime)s %(name)s[%(levelname)s]: %(message)s',
    level=logging.INFO,
    stream=sys.stdout,
)
logging.Formatter.converter = time.gmtime
log = logging.getLogger("BaseEntryStrategy")


class BaseEntryStrategy(ABC):
    """
    The sole goal of entry strategy is to determine the entry
    point based on historical candles
    """

    def __init__(self, api, tg, db) -> None:
        self.api: BybitAPIClient = api  # Bybit API client
        self.tg: TelegramNotifier = tg  # Telegram client
        self.db: PostgresWriter = db  # PostgreSQL writer

    @abstractmethod
    async def detect_entry_point(self) -> Side | None:
        pass

    @staticmethod
    def has_time_discrepancy_5m(last_closed_ts: datetime) -> bool:
        # todo implement for different timeframes
        now = datetime.now(timezone.utc)
        delta = (now - last_closed_ts).total_seconds()
        if not (5 * 60 < delta < 10 * 60):
            log.warning(
                f"last candle time discrepancy: {last_closed_ts}",
            )
            return True
        return False
