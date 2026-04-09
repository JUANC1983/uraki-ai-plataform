# dashboard/utils/formatters.py
"""Display formatting utilities."""
from styles.theme import COLORS, RISK_COLORS, PRIORITY_COLORS, STATUS_COLORS, STATUS_LABELS


def fmt_currency(amount: float, currency: str = "COP") -> str:
    """$4,850,000 COP"""
    return f"${amount:,.0f} {currency}"


def fmt_days(n: int) -> str:
    return f"{n} día{'s' if n != 1 else ''}"


def fmt_pct(n: float) -> str:
    return f"{n:.0f}%"


def risk_badge_html(level: str) -> str:
    color = RISK_COLORS.get(level, COLORS["text_muted"])
    bg = color.replace("#", "").strip()
    return (
        f'<span style="'
        f'background:rgba({_hex_to_rgb(color)},0.12);'
        f'color:{color};'
        f'border:1px solid rgba({_hex_to_rgb(color)},0.3);'
        f'border-radius:5px;padding:2px 8px;'
        f'font-size:11px;font-weight:600;letter-spacing:0.05em;'
        f'">RIESGO {level}</span>'
    )


def priority_badge_html(priority: str) -> str:
    color = PRIORITY_COLORS.get(priority, COLORS["text_muted"])
    labels = {
        "CRITICAL": "⚡ CRÍTICO",
        "HIGH":     "↑ HIGH",
        "MEDIUM":   "· MEDIO",
        "LOW":      "↓ LOW",
    }
    label = labels.get(priority, priority)
    return (
        f'<span style="'
        f'background:rgba({_hex_to_rgb(color)},0.12);'
        f'color:{color};'
        f'border:1px solid rgba({_hex_to_rgb(color)},0.3);'
        f'border-radius:5px;padding:2px 8px;'
        f'font-size:11px;font-weight:700;letter-spacing:0.04em;'
        f'">{label}</span>'
    )


def status_badge_html(status: str) -> str:
    color = STATUS_COLORS.get(status, COLORS["text_muted"])
    label = STATUS_LABELS.get(status, status)
    return (
        f'<span style="'
        f'background:rgba({_hex_to_rgb(color)},0.10);'
        f'color:{color};'
        f'border-radius:4px;padding:2px 7px;'
        f'font-size:11px;font-weight:500;'
        f'">{label}</span>'
    )


def score_bar_html(score: float, color: str, width_px: int = 120) -> str:
    """Horizontal progress bar for risk score."""
    pct = min(max(score, 0), 100)
    return (
        f'<div style="display:inline-flex;align-items:center;gap:6px;">'
        f'<div style="width:{width_px}px;height:4px;background:{COLORS["border_default"]};'
        f'border-radius:4px;overflow:hidden;">'
        f'<div style="width:{pct}%;height:100%;background:{color};'
        f'border-radius:4px;transition:width 0.4s ease;"></div>'
        f'</div>'
        f'<span style="font-size:11px;color:{COLORS["text_secondary"]};'
        f'font-weight:600;min-width:30px;">{pct:.0f}</span>'
        f'</div>'
    )


def _hex_to_rgb(hex_color: str) -> str:
    """Convert #RRGGBB to 'R,G,B' string for rgba()."""
    h = hex_color.lstrip("#")
    if len(h) == 6:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"{r},{g},{b}"
    return "128,128,128"


def card_html(content: str, padding: str = "1.25rem", border_accent: bool = False) -> str:
    border = (
        f"1px solid {COLORS['border_accent']}"
        if border_accent
        else f"1px solid {COLORS['border_subtle']}"
    )
    return (
        f'<div style="'
        f'background:{COLORS["bg_elevated"]};'
        f'border:{border};'
        f'border-radius:12px;'
        f'padding:{padding};'
        f'margin-bottom:0.75rem;'
        f'">{content}</div>'
    )


def label_value_html(label: str, value: str, value_color: str = None) -> str:
    vc = value_color or COLORS["text_primary"]
    return (
        f'<div style="display:flex;justify-content:space-between;'
        f'align-items:center;padding:4px 0;">'
        f'<span style="font-size:12px;color:{COLORS["text_muted"]};'
        f'text-transform:uppercase;letter-spacing:0.06em;">{label}</span>'
        f'<span style="font-size:13px;color:{vc};font-weight:500;">{value}</span>'
        f'</div>'
    )
