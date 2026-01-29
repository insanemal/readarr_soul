import logging
import sys
from dataclasses import dataclass, field
from typing import Any, Optional, Dict

from .display import CustomRichHandler, console

DEFAULT_LOGGING_CONF = {
    "level": "INFO",
    "format": "[%(levelname)s|%(module)s|L%(lineno)d] %(asctime)s: %(message)s",
    "datefmt": "%Y-%m-%dT%H:%M:%S%z",
}


def setup_logging(config):
    """
    Configure the logging system using Rich for beautiful output.
    """
    if "Logging" in config:
        log_config = config["Logging"]
    else:
        log_config = DEFAULT_LOGGING_CONF

    # Setup Rich logging
    logging.basicConfig(
        level=getattr(logging, log_config.get("level", "INFO").upper()),
        format="%(message)s",
        datefmt="[%X]",
        handlers=[CustomRichHandler(console=console, show_time=True, show_path=False)],
    )


@dataclass
class Context:
    """
    Application context to hold shared state across the application.
    """

    config: Any  # dict or ConfigParser
    slskd: Any
    readarr: Any
    config_dir: str = "."
    stats: Optional[Dict[str, Any]] = field(default_factory=dict)
