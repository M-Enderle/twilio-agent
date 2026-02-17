import logging

import dotenv

dotenv.load_dotenv()


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
