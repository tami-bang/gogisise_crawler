import logging
import sys
import structlog
from pythonjsonlogger import jsonlogger

def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
        format="%(message)s",
    )
    # JSON formatter for stdlib logger (used by structlog)
    formatter = jsonlogger.JsonFormatter()
    for h in logging.getLogger().handlers:
        h.setFormatter(formatter)

    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
