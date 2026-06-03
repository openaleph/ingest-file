"""Provides a set of ingestors based on different file types."""

import logging

from anystore.logging import configure_logging, get_logger
from procrastinate import cli as procrastinate_cli

__version__ = "5.3.1-rc1"

configure_logging()

logging.getLogger("chardet").setLevel(logging.INFO)
logging.getLogger("PIL").setLevel(logging.INFO)
logging.getLogger("google.auth").setLevel(logging.INFO)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("msglite").setLevel(logging.WARNING)

procrastinate_cli.print_stderr = get_logger("procrastinate.cli").info
