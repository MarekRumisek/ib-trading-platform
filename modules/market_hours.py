"""Market hours detection for IB Trading Platform.

Returns current session status based on Prague timezone (CET/CEST).
"""

from datetime import datetime
from zoneinfo import ZoneInfo

# US market hours in Eastern Time
_ET = ZoneInfo('America/New_York')
# EU market hours in CET
_CET = ZoneInfo('Europe/Berlin')

# Session labels
US_PREMARKET = 'US_PREMARKET'
US_REGULAR = 'US_REGULAR'
US_AFTERHOURS = 'US_AFTERHOURS'
EU_REGULAR = 'EU_REGULAR'
CLOSED = 'CLOSED'

# Display labels and colors
SESSION_DISPLAY = {
    US_PREMARKET:   {'label': '🌅 US Pre-Market',  'color': '#ffb74d'},
    US_REGULAR:     {'label': '🇺🇸 US Regular',     'color': '#4caf50'},
    US_AFTERHOURS:  {'label': '🌙 US After-Hours',  'color': '#7986cb'},
    EU_REGULAR:     {'label': '🇪🇺 EU Regular',      'color': '#4caf50'},
    CLOSED:         {'label': '🔴 Markets Closed',   'color': '#ef5350'},
}


def get_session_status(timezone: str = 'Europe/Prague') -> str:
    """Return current market session status.

    Checks US and EU market hours. Returns the most relevant session.

    Args:
        timezone: User timezone (used for display, not calculation).

    Returns:
        One of: US_PREMARKET, US_REGULAR, US_AFTERHOURS, EU_REGULAR, CLOSED
    """
    now_et = datetime.now(_ET)
    now_cet = datetime.now(_CET)

    # Skip weekends
    if now_et.weekday() >= 5:  # Saturday=5, Sunday=6
        return CLOSED

    hour_et = now_et.hour
    minute_et = now_et.minute
    et_time = hour_et * 60 + minute_et  # minutes since midnight ET

    hour_cet = now_cet.hour
    minute_cet = now_cet.minute
    cet_time = hour_cet * 60 + minute_cet

    # US Regular: 9:30 - 16:00 ET
    if 570 <= et_time < 960:  # 9:30=570, 16:00=960
        return US_REGULAR

    # US Pre-market: 4:00 - 9:30 ET
    if 240 <= et_time < 570:  # 4:00=240
        return US_PREMARKET

    # US After-hours: 16:00 - 20:00 ET
    if 960 <= et_time < 1200:  # 20:00=1200
        return US_AFTERHOURS

    # EU Regular: 9:00 - 17:30 CET
    if 540 <= cet_time < 1050:  # 9:00=540, 17:30=1050
        return EU_REGULAR

    return CLOSED


def get_session_display(timezone: str = 'Europe/Prague') -> dict:
    """Return session status with display label and color.

    Returns:
        Dict with keys: status, label, color
    """
    status = get_session_status(timezone)
    info = SESSION_DISPLAY.get(status, SESSION_DISPLAY[CLOSED])
    return {
        'status': status,
        'label': info['label'],
        'color': info['color'],
    }
