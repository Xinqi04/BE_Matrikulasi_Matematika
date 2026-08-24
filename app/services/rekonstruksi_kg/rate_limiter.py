import time
import logging

logger = logging.getLogger(__name__)


class RateLimiter:
    def __init__(self, delay_seconds: int, max_retries: int):
        self.delay_seconds = delay_seconds
        self.max_retries = max_retries

    def wait(self):
        """Tunggu selama delay standar sebelum lanjut, buat jaga rate limit."""
        logger.info(f"Sleeping {self.delay_seconds} seconds to respect rate limits...")
        time.sleep(self.delay_seconds)

    def backoff(self, attempt: int):
        """Exponential backoff berdasarkan nomor percobaan (1-indexed)."""
        # attempt 1: 5 * 2^0 = 5s
        # attempt 2: 5 * 2^1 = 10s
        # attempt 3: 5 * 2^2 = 20s
        backoff_time = self.delay_seconds * (2 ** (attempt - 1))
        logger.warning(f"Rate limit hit or error occurred. Backing off for {backoff_time} seconds (Attempt {attempt}/{self.max_retries})...")
        time.sleep(backoff_time)
