'''Optional webhook and SMTP notifications for new alerts.'''

import logging
import os
import re
import smtplib
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.parse import urlparse

import requests

from database import DatabaseMissingError, open_database
from feature_settings import notifications_settings

_SENSITIVE_QUERY_RE = re.compile(
    r'(?i)([?&](?:token|key|secret|sig|api_key)=)[^&\s\'"]+')
_URL_IN_MSG_RE = re.compile(r'(?i)\burl:\s*[^\s\'"]+')

_SEVERITY_RANK = {'info': 1, 'warning': 2, 'critical': 3}

_SEND_HARD_TIMEOUT_S = 15


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
        return f"{parsed.scheme}://{host}/…" if parsed.scheme else '<redacted>'
    except Exception:
        return '<redacted>'


def _redact_error_text(text, webhook_url=''):
    if not text:
        return ''
    out = text
    if webhook_url:
        out = out.replace(webhook_url, _redact_url(webhook_url))
    out = _SENSITIVE_QUERY_RE.sub(r'\1<redacted>', out)
    out = _URL_IN_MSG_RE.sub('url: <redacted>', out)
    return out[:500]


def _safe_delivery_error(exc, settings):
    if isinstance(exc, requests.RequestException):
        resp = getattr(exc, 'response', None)
        if resp is not None:
            return f"{type(exc).__name__} HTTP {resp.status_code}"
        return type(exc).__name__
    if isinstance(exc, (OSError, smtplib.SMTPException)):
        return f"{type(exc).__name__}"
    return _redact_error_text(str(exc), settings.get('webhook_url', ''))


def _send_webhook(url, payload, timeout=_SEND_HARD_TIMEOUT_S):
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
            settings['smtp_host'], settings['smtp_port'],
            timeout=_SEND_HARD_TIMEOUT_S) as smtp:
        smtp.set_debuglevel(0)
        if settings['smtp_use_tls']:
            smtp.starttls()
        if settings['smtp_user']:
            smtp.login(settings['smtp_user'], password)
        smtp.send_message(msg)


def _claim_due_rows(settings, owner):
    from db_migrate import _ensure_outbox_claim_columns

    now = _utc_now()
    now_iso = now.isoformat()
    claim_until = (
        now + timedelta(seconds=settings['claim_ttl_s'])).isoformat()
    try:
        db = open_database(create=False)
    except DatabaseMissingError:
        return []
    try:
        _ensure_outbox_claim_columns(db)
        due = db.execute_params(
            "SELECT o.id FROM notification_outbox o "
            "WHERE o.failed_at IS NULL AND o.next_attempt_at <= ? "
            "AND (o.claimed_until IS NULL OR o.claimed_until < ?) "
            "ORDER BY o.id LIMIT 10",
            (now_iso, now_iso))
        claimed = []
        for (out_id,) in due:
            cur = db.connection.execute(
                "UPDATE notification_outbox SET claimed_until=?, claim_owner=? "
                "WHERE id=? AND failed_at IS NULL AND next_attempt_at <= ? "
                "AND (claimed_until IS NULL OR claimed_until < ?)",
                (claim_until, owner, out_id, now_iso, now_iso))
            if cur.rowcount != 1:
                continue
            rows = db.execute_params(
                "SELECT o.id, o.alert_id, o.channel, o.attempts, "
                "a.severity, a.title, a.message, a.rule_id "
                "FROM notification_outbox o "
                "JOIN alerts a ON a.id = o.alert_id "
                "WHERE o.id=? AND o.claim_owner=?",
                (out_id, owner))
            if rows:
                row = rows[0]
                claimed.append({
                    'out_id': row[0],
                    'alert_id': row[1],
                    'channel': row[2],
                    'attempts': row[3],
                    'severity': row[4],
                    'title': row[5],
                    'message': row[6],
                    'rule_id': row[7],
                })
        db.connection.commit()
        return claimed
    finally:
        db.close()


def _finish_success(out_id, owner):
    try:
        db = open_database(create=False)
    except DatabaseMissingError:
        return
    try:
        db.execute_params_no_result(
            "DELETE FROM notification_outbox WHERE id=? AND claim_owner=?",
            (out_id, owner))
        db.connection.commit()
    finally:
        db.close()


def _finish_failure(out_id, owner, attempts, safe_error, settings):
    try:
        db = open_database(create=False)
    except DatabaseMissingError:
        return
    try:
        now = _utc_now()
        new_attempts = attempts + 1
        if new_attempts >= settings['max_attempts']:
            db.execute_params_no_result(
                "UPDATE notification_outbox SET attempts=?, last_error=?, "
                "failed_at=?, claimed_until=NULL, claim_owner=NULL "
                "WHERE id=? AND claim_owner=?",
                (new_attempts, safe_error, now.isoformat(), out_id, owner))
        else:
            delay = settings['retry_interval_s'] * (2 ** attempts)
            delay = min(delay, settings['retry_interval_s'] * 32)
            next_at = (now + timedelta(seconds=delay)).isoformat()
            db.execute_params_no_result(
                "UPDATE notification_outbox SET attempts=?, "
                "next_attempt_at=?, last_error=?, "
                "claimed_until=NULL, claim_owner=NULL "
                "WHERE id=? AND claim_owner=?",
                (new_attempts, next_at, safe_error, out_id, owner))
        db.connection.commit()
    finally:
        db.close()


def _deliver_item(settings, item):
    payload = {
        'alert_id': item['alert_id'],
        'rule_id': item['rule_id'],
        'severity': item['severity'],
        'title': item['title'],
        'message': item['message'],
    }
    channel = item['channel']
    if channel == 'webhook' and settings['webhook_url']:
        _send_webhook(settings['webhook_url'], payload)
    elif channel == 'email' and settings['email_enabled']:
        _send_email(
            settings,
            f"StrataSolar alert: {item['title']}",
            item['message'])
    else:
        raise RuntimeError(f"channel {channel} not configured")


def process_outbox(config):
    try:
        settings = notifications_settings(config.config_data)
    except Exception:
        return
    if not settings['enabled']:
        return

    owner = f"{os.getpid()}-{uuid.uuid4().hex[:12]}"
    work = _claim_due_rows(settings, owner)
    for item in work:
        try:
            _deliver_item(settings, item)
        except Exception as exc:
            safe = _safe_delivery_error(exc, settings)
            logging.warning(
                "Notification delivery failed (id=%s, channel=%s): %s",
                item['out_id'], item['channel'], safe)
            _finish_failure(
                item['out_id'], owner, item['attempts'], safe, settings)
            continue
        _finish_success(item['out_id'], owner)


def process_outbox_once(config):
    process_outbox(config)
