'''Install server shutdown signals before importing application modules.'''

import signal


def _server_early_interrupt(_signum, _frame):
    raise SystemExit(0)


signal.signal(signal.SIGINT, _server_early_interrupt)
signal.signal(signal.SIGTERM, _server_early_interrupt)
