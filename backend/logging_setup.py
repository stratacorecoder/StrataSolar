import logging
import sys
from logging.handlers import RotatingFileHandler


def setup_process_logging(log_path, level=logging.INFO):
    '''Log to a rotating data file and stdout (for Docker / systemd).'''
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
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
