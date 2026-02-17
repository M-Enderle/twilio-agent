import logging
import sys

import dotenv

dotenv.load_dotenv()


class _ColoredFormatter(logging.Formatter):
    """Custom formatter with colors like uvicorn."""

    # ANSI color codes
    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Green
        'WARNING': '\033[33m',    # Yellow
        'ERROR': '\033[31m',      # Red
        'CRITICAL': '\033[35m',   # Magenta
    }
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'

    def format(self, record):
        # Color the level name
        levelname = record.levelname
        if levelname in self.COLORS:
            colored_levelname = f"{self.COLORS[levelname]}{self.BOLD}{levelname:8s}{self.RESET}"
        else:
            colored_levelname = f"{levelname:8s}"

        # Format timestamp in dim
        timestamp = self.formatTime(record, '%H:%M:%S')
        colored_timestamp = f"{self.DIM}{timestamp}{self.RESET}"

        # Color the logger name
        colored_name = f"{self.BOLD}{record.name}{self.RESET}"

        # Build the message
        message = record.getMessage()

        return f"{colored_timestamp} | {colored_levelname} | {colored_name} - {message}"


class _WebSocketLogFilter(logging.Filter):
    """Filter noisy websocket lifecycle logs produced by uvicorn."""

    keywords = ("WebSocket", "connection open", "connection closed")

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not any(keyword in message for keyword in self.keywords)


_LOGGING_CONFIGURED = False


def configure_logging() -> None:
    """Suppress noisy websocket and third-party HTTP logs. Safe to call multiple times."""

    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return

    # Configure root logger with colorful formatting
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Add a new handler with colored formatter
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(_ColoredFormatter())
    root_logger.addHandler(console_handler)

    ws_filter = _WebSocketLogFilter()
    for name in (
        "uvicorn",
        "uvicorn.access",
        "uvicorn.error",
        "uvicorn.protocols",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.wsproto_impl",
    ):
        logging.getLogger(name).addFilter(ws_filter)

    logging.getLogger("twilio.http_client").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    _LOGGING_CONFIGURED = True
