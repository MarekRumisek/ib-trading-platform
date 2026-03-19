"""Simple log helper that respects config.LOG_LEVEL.

Usage:
    from modules.logger import log
    log('DEBUG', '[TICK] price update ...')   # only printed when LOG_LEVEL='DEBUG'
    log('INFO',  '[ORDER] filled ...')        # always printed
"""

import config

_LEVELS = {'DEBUG': 0, 'INFO': 1, 'WARNING': 2, 'ERROR': 3}


def log(level: str, msg: str) -> None:
    """Print *msg* only if *level* >= config.LOG_LEVEL."""
    threshold = _LEVELS.get(getattr(config, 'LOG_LEVEL', 'INFO').upper(), 1)
    msg_level = _LEVELS.get(level.upper(), 1)
    if msg_level >= threshold:
        print(msg)
