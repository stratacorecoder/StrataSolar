import logging

from legacy_notifications import warn_ignored_outbound_notifications


def test_warns_on_notifications_block_and_env(caplog, monkeypatch):
    monkeypatch.setenv("STRATASOLAR_WEBHOOK_URL", "http://example/hook?token=SECRET")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    with caplog.at_level(logging.WARNING):
        warn_ignored_outbound_notifications({
            "notifications": {"enabled": True, "webhook_url": "x"},
        })
    assert "not supported in this version" in caplog.text
    assert "notifications:" in caplog.text
    assert "STRATASOLAR_WEBHOOK_URL" in caplog.text
    assert "SMTP_HOST" in caplog.text
    assert "SECRET" not in caplog.text
    assert "pw" not in caplog.text
