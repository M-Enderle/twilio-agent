"""Loki logging handler – ships Python logs to Grafana Loki.

Uses stdlib QueueHandler/QueueListener so HTTP calls never block the
main thread (critical for a telephony app).  All exceptions inside
emit() are silently swallowed so a Loki outage can never crash the app.
"""

import atexit
import json
import logging
import logging.handlers
import os
import queue
import socket
import time

import requests


class LokiHandler(logging.Handler):
    """Sends log records to Loki's push API."""

    def __init__(self, url: str, org_id: str | None = None, labels: dict | None = None):
        super().__init__()
        self._push_url = f"{url.rstrip('/')}/loki/api/v1/push"
        self._session = requests.Session()
        if org_id:
            self._session.headers["X-Scope-OrgID"] = org_id
        self._session.headers["Content-Type"] = "application/json"
        self._static_labels = labels or {}

    def emit(self, record: logging.LogRecord) -> None:
        try:
            labels = {
                **self._static_labels,
                "level": record.levelname.lower(),
                "logger": record.name,
            }
            # Loki expects nanosecond timestamps as strings
            ts_ns = str(int(record.created * 1e9))
            message = self.format(record)

            payload = {
                "streams": [
                    {
                        "stream": labels,
                        "values": [[ts_ns, message]],
                    }
                ]
            }
            self._session.post(self._push_url, data=json.dumps(payload), timeout=5)
        except Exception:
            # Never let Loki issues affect the application
            pass


def create_loki_handler(
    url: str,
    org_id: str | None = None,
    labels: dict | None = None,
) -> logging.handlers.QueueHandler:
    """Create a non-blocking Loki handler using QueueHandler/QueueListener.

    Returns a QueueHandler that can be added to any logger.  The actual
    HTTP calls happen on a background thread managed by QueueListener.
    """
    loki = LokiHandler(url=url, org_id=org_id, labels=labels)
    # Plain text formatter (no ANSI colors) for Loki
    loki.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s - %(message)s")
    )

    log_queue: queue.Queue = queue.Queue(-1)  # unbounded
    handler = logging.handlers.QueueHandler(log_queue)
    listener = logging.handlers.QueueListener(log_queue, loki, respect_handler_level=True)
    listener.start()
    atexit.register(listener.stop)

    return handler
