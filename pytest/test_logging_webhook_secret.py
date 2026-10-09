import logging

from logging_setup import configure_sensitive_loggers
from notifications import _send_webhook


def test_verbose_logging_does_not_log_webhook_token(caplog):
    configure_sensitive_loggers()
    caplog.set_level(logging.DEBUG, logger="urllib3.connectionpool")
    with caplog.at_level(logging.DEBUG):
        try:
            _send_webhook(
                "http://127.0.0.1:9/hook?token=SUPERSECRET99",
                {"x": 1},
                timeout=0.2)
        except Exception:
            pass
    joined = "\n".join(caplog.messages)
    assert "SUPERSECRET99" not in joined
