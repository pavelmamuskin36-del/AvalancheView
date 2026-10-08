import logging
import sys
from logging.handlers import RotatingFileHandler

from avalanche_view.config import LOG_DIRECTORY


def configure_logging() -> None:
    directory = LOG_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        directory / "avalanche_view.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    handlers = [handler]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )
