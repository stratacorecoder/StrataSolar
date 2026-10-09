'''Optional webhook and SMTP notifications for new alerts.'''

import logging
import os
import re
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.parse import urlparse

import requests

from feature_settings import notifications_settings

_URL_TOKEN_RE = re.compile(
    r'(https?://[^\s\']+)', re.IGNORECASE)

_SEVERITY_RANK = {'info': 1, 'warning': 2, 'critical': 3}


def _meets_min(severity, minimum):
    return _SEVERITY_RANK.get(severity, 0) >= _SEVERITY_RANK.get(minimum, 99)


def _utc_now():
    return datetime.now(timezone.utc)


def enqueue_for_alerts(db, config, alert_ids):
    if not alert_ids:
        return
    try:
        settings = notifications_settings(config.config_data)
    except Exception:
        logging.exception("Notifications: invalid settings")
        return
    if not settings['enabled']:
        return

    now = _utc_now().isoformat()
    for aid in alert_ids:
        rows = db.execute_params(
            "SELECT severity, title, message FROM alerts WHERE id=?",
            (aid,))
        if not rows:
            continue
        sev, title, message = rows[0]
        if settings['webhook_url'] and _meets_min(
                sev, settings['webhook_min_severity']):
            db.execute_params_no_result(
                "INSERT INTO notification_outbox "
                "(alert_id, channel, created_at, next_attempt_at) "
                "VALUES (?, 'webhook', ?, ?)",
                (aid, now, now))
        if settings['email_enabled'] and _meets_min(
                sev, settings['email_min_severity']):
            db.execute_params_no_result(
                "INSERT INTO notification_outbox "
                "(alert_id, channel, created_at, next_attempt_at) "
                "VALUES (?, 'email', ?, ?)",
                (aid, now, now))


def _redact_url(url):
    if not url:
        return ''
    try:
        parsed = urlparse(url)
        host = parsed.netloc or parsed.path
        return f"{parsed.scheme}://{host}/…" if parsed.scheme else host
    except Exception:
        return '<redacted>'


def _redact_error_text(text, webhook_url=''):
    if not text:
        return ''
    out = text
    if webhook_url:
        out = out.replace(webhook_url, _redact_url(webhook_url))
    out = _URL_TOKEN_RE.sub('<redacted-url>', out)
    return out[:500]


def _send_webhook(url, payload, timeout=10):
    resp = requests.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()


def _send_email(settings, subject, body):
    password = os.environ.get(settings['smtp_password_env'], '')
    if not password:
        raise RuntimeError("SMTP password env var not set")
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = settings['smtp_from']
    msg['To'] = settings['smtp_to']
    msg.set_content(body)
    with smtplib.SMTP(
            settings['smtp_host'], settings['smtp_port'], timeout=15) as smtp:
        if settings['smtp_use_tls']:
            smtp.starttls()
        if settings['smtp_user']:
            smtp.login(settings['smtp_user'], password)
        smtp.send_message(msg)


def process_outbox(db, config):
    try:
        settings = notifications_settings(config.config_data)
    except Exception:
        return
    if not settings['enabled']:
        return

    now = _utc_now()
    rows = db.execute_params(
        "SELECT id, alert_id, channel, attempts FROM notification_outbox "
        "WHERE next_attempt_at <= ? ORDER BY id LIMIT 10",
        (now.isoformat(),))
    for row in rows:
        out_id, alert_id, channel, attempts = row
        alert = db.execute_params(
            "SELECT severity, title, message, rule_id FROM alerts WHERE id=?",
            (alert_id,))
        if not alert:
            db.execute_params_no_result(
                "DELETE FROM notification_outbox WHERE id=?", (out_id,))
            continue
        sev, title, message, rule_id = alert[0]
        payload = {
            'alert_id': alert_id,
            'rule_id': rule_id,
            'severity': sev,
            'title': title,
            'message': message,
        }
        try:
            if channel == 'webhook' and settings['webhook_url']:
                _send_webhook(settings['webhook_url'], payload)
            elif channel == 'email' and settings['email_enabled']:
                _send_email(
                    settings,
                    f"StrataSolar alert: {title}",
                    message)
            else:
                raise RuntimeError(f"channel {channel} not configured")
            db.execute_params_no_result(
                "DELETE FROM notification_outbox WHERE id=?", (out_id,))
        except Exception as exc:
            safe = _redact_error_text(
                str(exc), settings.get('webhook_url', ''))
            logging.warning(
                "Notification delivery failed (id=%s, channel=%s): %s",
                out_id, channel, safe)
            delay = settings['retry_interval_s'] * (attempts + 1)
            next_at = (now + timedelta(seconds=delay)).isoformat()
            db.execute_params_no_result(
                "UPDATE notification_outbox SET attempts=?, "
                "next_attempt_at=?, last_error=? WHERE id=?",
                (attempts + 1, next_at, safe, out_id))


def process_outbox_once(config):
    from database import Database

    db = Database("data/db.sqlite")
    try:
        process_outbox(db, config)
        db.connection.commit()
    finally:
        db.close()
