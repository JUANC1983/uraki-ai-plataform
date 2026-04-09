# dashboard/utils/time.py
"""Bogotá-aware time utilities."""
from datetime import datetime, timezone, timedelta

# UTC-5 — Colombia does not observe DST
BOGOTA_TZ = timezone(timedelta(hours=-5))

MONTH_NAMES_ES = [
    "", "ene", "feb", "mar", "abr", "may", "jun",
    "jul", "ago", "sep", "oct", "nov", "dic",
]


def bogota_now() -> datetime:
    return datetime.now(tz=BOGOTA_TZ)


def fmt_time(dt: datetime) -> str:
    """HH:MM:SS"""
    return dt.strftime("%H:%M:%S")


def fmt_date(dt: datetime) -> str:
    """15 ene 2024"""
    return f"{dt.day} {MONTH_NAMES_ES[dt.month]} {dt.year}"


def fmt_datetime(dt: datetime) -> str:
    return f"{fmt_date(dt)} {dt.strftime('%H:%M')}"


def time_ago(iso_str: str) -> str:
    """'hace X' human-readable. iso_str is a naive or aware ISO datetime string."""
    try:
        if iso_str.endswith("Z"):
            iso_str = iso_str[:-1] + "+00:00"
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=BOGOTA_TZ)
        now = bogota_now()
        delta = now - dt
        secs = int(delta.total_seconds())
        if secs < 60:
            return "hace un momento"
        elif secs < 3600:
            m = secs // 60
            return f"hace {m}m"
        elif secs < 86400:
            h = secs // 3600
            return f"hace {h}h"
        else:
            d = secs // 86400
            return f"hace {d}d"
    except Exception:
        return "—"


def fmt_duration_ms(ms: int) -> str:
    """Format milliseconds to human duration: '2m 34s'"""
    if ms <= 0:
        return "—"
    s = ms // 1000
    if s < 60:
        return f"{s}s"
    m = s // 60
    s = s % 60
    return f"{m}m {s}s"


def live_clock_html() -> str:
    """Returns an HTML component that shows a live Bogotá clock (updates every second)."""
    return """
<div id="uraki-clock" style="
    font-family: 'Inter', monospace;
    font-size: 13px;
    font-weight: 500;
    color: #888888;
    letter-spacing: 0.06em;
    min-width: 90px;
    text-align: center;
"></div>
<script>
(function() {
    function update() {
        const now = new Date();
        const opts = {
            timeZone: 'America/Bogota',
            hour: '2-digit', minute: '2-digit', second: '2-digit',
            hour12: false
        };
        const t = now.toLocaleTimeString('es-CO', opts);
        const d = now.toLocaleDateString('es-CO', {
            timeZone: 'America/Bogota',
            day: '2-digit', month: 'short'
        });
        const el = document.getElementById('uraki-clock');
        if (el) el.innerHTML = d + ' &nbsp; ' + t;
    }
    update();
    setInterval(update, 1000);
})();
</script>
"""
