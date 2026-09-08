#!/usr/bin/env python3
"""
Fetch the current NWS daily forecast and email it.

Reuses fetch_nws_forecast() from fetch_forecasts.py so there's a single
source of truth for talking to the NWS API. This script is designed to
run in GitHub Actions as a scheduled job, alongside (but independent of)
the snapshot-archival workflow.
"""

import os
import smtplib
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, List, Optional

from fetch_forecasts import (
    fetch_nws_forecast,
    log,
    FLAGSTAFF_LATITUDE,
    FLAGSTAFF_LONGITUDE,
    FLAGSTAFF_STATION_NAME,
)

# Arizona is fixed at UTC-7 year-round (no DST observed).
ARIZONA_UTC_OFFSET = timedelta(hours=-7)


def get_weather_emoji(short_forecast: str, is_daytime: bool) -> str:
    """Map an NWS shortForecast string to a representative emoji icon."""
    text = short_forecast.lower()

    if 'thunderstorm' in text or 't-storm' in text:
        return "⛈️"
    if 'snow' in text or 'flurries' in text or 'blizzard' in text or 'sleet' in text:
        return "❄️"
    if 'rain' in text or 'shower' in text or 'drizzle' in text:
        return "🌧️"
    if 'fog' in text or 'haze' in text or 'mist' in text:
        return "🌫️"
    if 'cloudy' in text or 'overcast' in text:
        return "☁️"
    if 'partly' in text or 'mostly sunny' in text or 'mostly clear' in text:
        return "⛅" if is_daytime else "🌙"
    if 'clear' in text or 'sunny' in text:
        return "☀️" if is_daytime else "🌙"
    if 'wind' in text:
        return "💨"

    return "🌡️"  # fallback for anything unmatched


def group_periods_into_days(periods: List[Dict]) -> List[Dict]:
    """Pair up consecutive day/night NWS periods. Handles the edge cases
    where the forecast starts mid-night or ends on an unpaired period."""
    days = []
    i = 0
    n = len(periods)

    while i < n:
        period = periods[i]
        is_day = period.get('isDaytime', True)

        if is_day and i + 1 < n and not periods[i + 1].get('isDaytime', True):
            days.append({'day': period, 'night': periods[i + 1]})
            i += 2
        elif is_day:
            days.append({'day': period, 'night': None})
            i += 1
        else:
            days.append({'day': None, 'night': period})
            i += 1

    return days


def format_date_label(start_time: Optional[str]) -> str:
    """Format an NWS period's startTime into a 'Month Day' label."""
    if not start_time:
        return ""
    try:
        dt = datetime.fromisoformat(start_time)
        return dt.strftime("%B %-d")
    except ValueError:
        return ""


def format_period_detail_html(period: Dict) -> str:
    """Render one period's bolded summary line plus wind/detailed text."""
    name = period.get('name', 'Unknown')
    temp = period.get('temperature')
    temp_unit = period.get('temperatureUnit', '')
    short_forecast = period.get('shortForecast', '')
    wind_speed = period.get('windSpeed', '')
    wind_dir = period.get('windDirection', '')
    detailed = period.get('detailedForecast', '')

    lines = [f"<p style='margin:0 0 10px;'>"]
    lines.append(f"<b>{name}: {temp}°{temp_unit}, {short_forecast}</b><br>")
    if wind_speed:
        lines.append(f"Wind: {wind_speed} {wind_dir}".rstrip() + "<br>")
    if detailed:
        lines.append(f"{detailed}<br>")
    lines.append("</p>")

    return "".join(lines)


def format_summary_boxes_html(day: Optional[Dict], night: Optional[Dict]) -> str:
    """Render the side-by-side Day/Night H/L summary boxes for one date."""
    box_style = (
        "flex:1;background:#f5f5f5;border-radius:8px;"
        "padding:10px 14px;display:flex;align-items:center;gap:10px;"
    )
    cells = []

    if day:
        icon = get_weather_emoji(day.get('shortForecast', ''), True)
        high = day.get('temperature')
        temp_unit = day.get('temperatureUnit', '')
        cells.append(
            f"<div style='{box_style}'>"
            f"<span style='font-size:22px;'>{icon}</span>"
            f"<span><span style='display:block;font-size:12px;color:#666;'>Day &middot; High</span>"
            f"<span style='font-size:17px;font-weight:bold;'>{high}°{temp_unit}</span></span>"
            f"</div>"
        )

    if night:
        icon = get_weather_emoji(night.get('shortForecast', ''), False)
        low = night.get('temperature')
        temp_unit = night.get('temperatureUnit', '')
        cells.append(
            f"<div style='{box_style}'>"
            f"<span style='font-size:22px;'>{icon}</span>"
            f"<span><span style='display:block;font-size:12px;color:#666;'>Night &middot; Low</span>"
            f"<span style='font-size:17px;font-weight:bold;'>{low}°{temp_unit}</span></span>"
            f"</div>"
        )

    return f"<div style='display:flex;gap:12px;margin-bottom:14px;'>{''.join(cells)}</div>"


def format_forecast_html(station_name: str, periods: List[Dict], generated_at: str) -> str:
    """Format NWS forecast periods into the full HTML email body: a header
    with the generation timestamp, then one section per day with side-by-side
    Day/Night summary boxes followed by the detailed bolded forecast text."""
    parts = [
        f"<p style='font-size:15px;font-weight:bold;margin:0 0 4px;'>{station_name} Forecast (Home Station)</p>",
        f"<p style='font-size:13px;color:#666;margin:0 0 14px;'>Generated on {generated_at}</p>",
        "<hr style='border:none;border-top:1px solid #ddd;margin:0 0 18px;'>",
    ]

    days = group_periods_into_days(periods)

    for idx, day in enumerate(days):
        ref_period = day['day'] or day['night']
        date_label = format_date_label(ref_period.get('startTime'))
        divider = "padding-top:18px;border-top:1px solid #ddd;" if idx > 0 else ""

        parts.append(f"<div style='margin-bottom:20px;{divider}'>")
        if date_label:
            parts.append(f"<p style='font-size:14px;font-weight:bold;margin:0 0 8px;'>{date_label}</p>")

        parts.append(format_summary_boxes_html(day['day'], day['night']))

        if day['day']:
            parts.append(format_period_detail_html(day['day']))
        if day['night']:
            parts.append(format_period_detail_html(day['night']))

        parts.append("</div>")

    return "\n".join(parts)


def send_forecast_email(body_html: str, subject: str):
    """Send the forecast email via Gmail SMTP."""
    sender = os.environ["GMAIL_ADDRESS"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ.get("EMAIL_TO", sender)

    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.attach(MIMEText(body_html, "html"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(sender, password)
        server.send_message(msg)

    log(f"✅ Email sent to {recipient}")


def main():
    """Main execution function."""
    log("🚀 Starting daily forecast email")

    # Location is intentionally NOT read from the environment - imported
    # directly from fetch_forecasts.py so both scripts always agree on
    # where "the forecast" means, with no secret to misconfigure.
    station_name = FLAGSTAFF_STATION_NAME
    latitude = FLAGSTAFF_LATITUDE
    longitude = FLAGSTAFF_LONGITUDE

    nws_result = fetch_nws_forecast(latitude, longitude)

    if not nws_result:
        log("❌ Failed to fetch forecast - aborting email send")
        raise SystemExit(1)

    periods, metadata = nws_result

    # Compute the current time in Arizona (fixed UTC-7, no DST) for the
    # "Generated on" header, since GitHub Actions runners run in UTC.
    generated_at_dt = datetime.now(timezone.utc) + ARIZONA_UTC_OFFSET
    generated_at = generated_at_dt.strftime("%B %-d, %Y at %-I:%M %p")

    body_html = format_forecast_html(station_name, periods, generated_at)
    subject = f"{station_name} Forecast"

    send_forecast_email(body_html, subject)

    log("✅ Daily forecast email complete")


if __name__ == "__main__":
    main()
