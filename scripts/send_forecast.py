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
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, List

from fetch_forecasts import (
    fetch_nws_forecast,
    log,
    FLAGSTAFF_LATITUDE,
    FLAGSTAFF_LONGITUDE,
    FLAGSTAFF_STATION_NAME,
)


def format_forecast_text(station_name: str, periods: List[Dict]) -> str:
    """Format NWS forecast periods into a plain-text email body."""
    lines = [f"Forecast for {station_name}", ""]

    for period in periods:
        name = period.get('name', 'Unknown')
        temp = period.get('temperature')
        temp_unit = period.get('temperatureUnit', '')
        short_forecast = period.get('shortForecast', '')
        wind_speed = period.get('windSpeed', '')
        wind_dir = period.get('windDirection', '')
        detailed = period.get('detailedForecast', '')

        lines.append(f"{name}: {temp}°{temp_unit}, {short_forecast}")
        if wind_speed:
            lines.append(f"  Wind: {wind_speed} {wind_dir}".rstrip())
        if detailed:
            lines.append(f"  {detailed}")
        lines.append("")

    return "\n".join(lines)


def send_forecast_email(body_text: str, subject: str):
    """Send the forecast email via Gmail SMTP."""
    sender = os.environ["GMAIL_ADDRESS"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ.get("EMAIL_TO", sender)

    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.attach(MIMEText(body_text, "plain"))

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

    body_text = format_forecast_text(station_name, periods)
    subject = f"{station_name} Forecast"

    send_forecast_email(body_text, subject)

    log("✅ Daily forecast email complete")


if __name__ == "__main__":
    main()
