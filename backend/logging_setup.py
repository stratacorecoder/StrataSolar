import logging
import sys
from logging.handlers import RotatingFileHandler

_SENSITIVE_LOGGER_NAMES = (
    'urllib3',
    'urllib3.connection',
    'urllib3.connectionpool',
    'requests',
    'http.client',
)


def configure_sensitive_loggers():
    '''Keep secrets out of debug logs (urllib3 URLs).'''
    for name in _SENSITIVE_LOGGER_NAMES:
        level = logging.ERROR if name == 'urllib3.connection' else logging.WARNING
        logging.getLogger(name).setLevel(level)


def setup_process_logging(log_path, level=logging.INFO):
    '''Log to a rotating data file and stdout (for Docker / systemd).'''
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    configure_sensitive_loggers()
    formatter = logging.Formatter(
        fmt='%(asctime)s %(levelname)-8s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S')
    file_handler = RotatingFileHandler(
        log_path, mode='a', maxBytes=5 * 1024 * 1024, backupCount=3,
        encoding='utf-8')
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)
