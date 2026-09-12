#!/usr/bin/env python3
"""
Fetch the current NWS daily forecast and email it.

Reuses fetch_nws_forecast() from fetch_forecasts.py so there's a single
source of truth for talking to the NWS API. This script is designed to
run in GitHub Actions as a scheduled job, alongside (but independent of)
the snapshot-archival workflow.
"""

import os
import re
import smtplib
import urllib.parse
from datetime import datetime, timezone, timedelta, date as date_type
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from fetch_forecasts import (
    fetch_nws_forecast,
    fetch_json,
    log,
    FLAGSTAFF_LATITUDE,
    FLAGSTAFF_LONGITUDE,
    FLAGSTAFF_STATION_NAME,
)

# Arizona is fixed at UTC-7 year-round (no DST observed).
ARIZONA_UTC_OFFSET = timedelta(hours=-7)
LOCAL_TZ = ZoneInfo("America/Phoenix")  # Arizona - no DST, matches Flagstaff

# NWS gridpoint identifier for the Flagstaff coordinate used elsewhere in
# this project (FLAGSTAFF_LATITUDE/FLAGSTAFF_LONGITUDE) - confirmed correct.
# Used only for the hourly QPF (rain total) lookup; the day/night forecast
# itself still goes through fetch_nws_forecast()'s /points/ lookup.
RAIN_GRID_URL = "https://api.weather.gov/gridpoints/FGZ/74,91"

DURATION_RE = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?")

# Precipitation-probability thresholds (%) used to decide how strongly a
# rain/snow icon should show. Below LOW, precip chance is treated as
# negligible and we fall back to the sky-condition icon (clear/cloudy/etc)
# even if the forecast text mentions "chance of showers". Between LOW and
# HIGH, we show a lighter "possible precip" icon. At/above HIGH, we show
# the full rain/snow icon.
PRECIP_THRESHOLD_LOW = 40
PRECIP_THRESHOLD_HIGH = 70


def parse_duration_hours(duration: str) -> float:
    """Parse an ISO 8601 duration like 'PT3H' or 'PT1H30M' into hours."""
    match = DURATION_RE.fullmatch(duration)
    if not match:
        raise ValueError(f"Unexpected duration format: {duration}")
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    return hours + minutes / 60


def fetch_daily_rain_totals() -> Dict:
    """Fetch NWS hourly QPF (quantitative precipitation forecast) and sum
    it into midnight-to-midnight local-day totals, in inches. Returns
    {date: inches}; returns {} if the fetch fails, so a rain-data outage
    degrades gracefully rather than breaking the whole email."""
    data = fetch_json(RAIN_GRID_URL)
    if not data:
        log("⚠️  Failed to fetch QPF grid data - rain totals will be omitted")
        return {}

    try:
        qpf = data["properties"]["quantitativePrecipitation"]
    except KeyError:
        log("⚠️  QPF data missing from grid response - rain totals will be omitted")
        return {}

    uom = qpf.get("uom", "")
    totals: Dict = {}

    for entry in qpf.get("values", []):
        value = entry.get("value")
        if value is None:
            continue

        raw = float(value)
        inches = raw / 25.4 if "mm" in uom else raw

        start_str, duration_str = entry["validTime"].split("/")
        start = datetime.fromisoformat(start_str).astimezone(LOCAL_TZ)
        hours = parse_duration_hours(duration_str)

        # Some intervals cover more than one hour (NWS merges equal
        # consecutive values). Spread the total evenly across each
        # covered hour so it lands in the right local day.
        num_buckets = max(round(hours), 1)
        inches_per_hour = inches / num_buckets

        for i in range(num_buckets):
            hour_start = start + timedelta(hours=i)
            day = hour_start.date()
            totals[day] = totals.get(day, 0.0) + inches_per_hour

    return totals


def fetch_wu_daily_history(station_id: str, target_date: date_type) -> List[Dict]:
    """Fetch WU PWS historical observations for a specific calendar date via
    the /v2/pws/history/all endpoint. Unlike /observations/all/1day (which,
    per testing, returns only today-so-far rather than a trailing 24 hours),
    this endpoint is scoped to exactly the requested date, so it reliably
    captures all of "yesterday" regardless of what time this script runs.
    Returns [] on any failure, so a history-fetch outage just means the
    actuals section is omitted rather than the whole email failing.
    """
    api_key = os.getenv('WU_API_KEY')
    if not api_key:
        log("⚠️  WU_API_KEY not set - skipping yesterday's actuals section")
        return []

    params = {
        'stationId': station_id,
        'format': 'json',
        'units': 'e',
        'date': target_date.strftime('%Y%m%d'),
        'apiKey': api_key,
    }
    url = f"https://api.weather.com/v2/pws/history/all?{urllib.parse.urlencode(params)}"
    data = fetch_json(url)

    if not data or 'observations' not in data:
        log(f"⚠️  Failed to fetch WU history for {target_date} - actuals will be omitted")
        return []

    observations = data['observations']

    # TEMPORARY DEBUG - remove once the actuals section is confirmed working.
    log(f"actuals debug: fetched {len(observations)} history entries for {target_date}")
    if observations:
        log(f"actuals debug: sample history entry = {observations[0]}")

    return observations


def compute_actuals_from_history(observations: List[Dict], target_date: date_type) -> Dict:
    """Aggregate WU PWS historical observations (from fetch_wu_daily_history)
    into that day's actual high/low temp and rain total. Returns
    {'date': date, 'high': float|None, 'low': float|None, 'rain': float|None}.
    Any value is None if no data was available for it.

    Each history entry already covers the requested calendar day, and its
    imperial block reports that interval's own tempHigh/tempLow plus a
    precipTotal that's a running cumulative total for the day (resets at
    local midnight) - so the day's overall high/low/rain are simply the
    max tempHigh, min tempLow, and max precipTotal across all entries.
    """
    highs = []
    lows = []
    precip_values = []

    for obs in observations:
        imperial = obs.get('imperial') or {}

        temp_high = imperial.get('tempHigh')
        if temp_high is not None:
            highs.append(temp_high)

        temp_low = imperial.get('tempLow')
        if temp_low is not None:
            lows.append(temp_low)

        precip_total = imperial.get('precipTotal')
        if precip_total is not None:
            precip_values.append(precip_total)

    result = {
        'date': target_date,
        'high': max(highs) if highs else None,
        'low': min(lows) if lows else None,
        'rain': max(precip_values) if precip_values else None,
    }

    # TEMPORARY DEBUG - remove once the actuals section is confirmed working.
    log(f"actuals debug: computed result = {result}")

    return result




def format_actuals_html(actuals: Dict) -> str:
    """Render the yesterday-actuals section: date header (with 'ACTUALS'
    suffix) plus plain, icon-free High/Low/Rain boxes. Returns '' entirely
    if no high or low data was available (e.g. station was offline), since
    a section with nothing but dashes isn't worth showing."""
    if actuals.get('high') is None and actuals.get('low') is None:
        return ""

    box_style = "flex:1;background:#f5f5f5;border-radius:8px;padding:10px 14px;"
    label_style = "display:block;font-size:12px;color:#666;margin:0;"
    value_style = "font-size:17px;font-weight:bold;margin:0;"

    date_label = actuals['date'].strftime("%A, %B %-d")

    cells = []
    if actuals.get('high') is not None:
        cells.append(
            f"<div style='{box_style}'>"
            f"<p style='{label_style}'>Actual High</p>"
            f"<p style='{value_style}'>{actuals['high']:.0f}\u00b0F</p>"
            f"</div>"
        )
    if actuals.get('low') is not None:
        cells.append(
            f"<div style='{box_style}'>"
            f"<p style='{label_style}'>Actual Low</p>"
            f"<p style='{value_style}'>{actuals['low']:.0f}\u00b0F</p>"
            f"</div>"
        )
    if actuals.get('rain'):
        cells.append(
            f"<div style='{box_style}'>"
            f"<p style='{label_style}'>Actual Rain</p>"
            f"<p style='{value_style}'>{actuals['rain']:.2f} in</p>"
            f"</div>"
        )

    return (
        f"<div style='margin-bottom:20px;'>"
        f"<p style='font-size:14px;font-weight:bold;margin:0 0 8px;'>{date_label} &mdash; ACTUALS</p>"
        f"<div style='display:flex;gap:12px;'>{''.join(cells)}</div>"
        f"</div>"
        f"<hr style='border:none;border-top:1px solid #ddd;margin:20px 0;'>"
    )


def get_weather_emoji(
    short_forecast: str,
    is_daytime: bool,
    pop_value: Optional[int] = None,
    detailed_forecast: str = "",
) -> str:
    """Map an NWS shortForecast string (plus, when available, its
    probabilityOfPrecipitation value) to a representative emoji icon.

    Precipitation icons are gated by pop_value using a two-tier threshold:
    below PRECIP_THRESHOLD_LOW, precip is treated as unlikely enough to show
    the underlying sky condition instead; between LOW and HIGH, a lighter
    "possible" icon is shown; at/above HIGH, the full rain/snow icon shows.
    If pop_value is unavailable (None), falls back to text-only matching.

    When shortForecast is entirely a precip qualifier (e.g. "Slight Chance
    Showers And Thunderstorms" with no sky-condition words of its own), the
    sky-condition check also searches detailed_forecast, since NWS often
    states "Mostly sunny"/"Mostly clear" etc. only there in that case.
    """
    text = short_forecast.lower()

    is_thunder = 'thunderstorm' in text or 't-storm' in text
    is_snow = 'snow' in text or 'flurries' in text or 'blizzard' in text or 'sleet' in text
    is_rain = 'rain' in text or 'shower' in text or 'drizzle' in text

    icon = None
    reason = ""

    if (is_thunder or is_snow or is_rain) and pop_value is not None:
        if pop_value >= PRECIP_THRESHOLD_HIGH:
            if is_thunder:
                icon, reason = "\u26c8\ufe0f", "precip >= HIGH, thunder"
            elif is_snow:
                icon, reason = "\u2744\ufe0f", "precip >= HIGH, snow"
            else:
                icon, reason = "\U0001f327\ufe0f", "precip >= HIGH, rain"
        elif pop_value >= PRECIP_THRESHOLD_LOW:
            if is_snow:
                icon, reason = "\U0001f328\ufe0f", "precip >= LOW, snow"  # light/possible snow
            else:
                icon, reason = "\U0001f326\ufe0f", "precip >= LOW, rain"  # possible showers
        # Below the low threshold: precip chance is negligible enough that
        # we ignore the "shower"/"snow" wording and fall through to the
        # plain sky-condition check below - checking detailed_forecast too,
        # since shortForecast may contain nothing but the precip qualifier.
    elif is_thunder:
        icon, reason = "\u26c8\ufe0f", "thunder, no pop_value"
    elif is_snow:
        icon, reason = "\u2744\ufe0f", "snow, no pop_value"
    elif is_rain:
        icon, reason = "\U0001f327\ufe0f", "rain, no pop_value"

    if icon is None:
        # Sky-condition check: shortForecast first, then detailedForecast as
        # a fallback for cases like "Chance Showers And Thunderstorms" where
        # the actual sky description ("Mostly sunny") only appears in the
        # detail. Checked most-specific-phrase-first, since e.g. "partly
        # cloudy" contains the substring "cloudy" and would otherwise always
        # match the generic cloudy check before reaching the partly check.
        combined_text = text
        if detailed_forecast:
            combined_text = f"{text} {detailed_forecast.lower()}"

        if 'fog' in combined_text or 'haze' in combined_text or 'mist' in combined_text:
            icon, reason = "\U0001f32b\ufe0f", "fog/haze/mist"
        elif 'mostly cloudy' in combined_text:
            icon, reason = ("\U0001f325\ufe0f" if is_daytime else "\u2601\ufe0f"), "mostly cloudy"
        elif 'partly cloudy' in combined_text or 'partly sunny' in combined_text:
            icon, reason = ("\u26c5" if is_daytime else "\U0001f319\u2601\ufe0f"), "partly cloudy/sunny"
        elif 'mostly sunny' in combined_text or 'mostly clear' in combined_text:
            icon, reason = ("\U0001f324\ufe0f" if is_daytime else "\U0001f319"), "mostly sunny/clear"
        elif 'cloudy' in combined_text or 'overcast' in combined_text:
            icon, reason = "\u2601\ufe0f", "cloudy/overcast (generic)"
        elif 'clear' in combined_text or 'sunny' in combined_text:
            icon, reason = ("\u2600\ufe0f" if is_daytime else "\U0001f319"), "clear/sunny (generic)"
        elif 'wind' in combined_text:
            icon, reason = "\U0001f4a8", "wind"
        else:
            # Nothing matched in either string - default to a neutral
            # partly-cloudy icon rather than a thermometer fallback, since
            # an unstated sky condition is far more plausibly partly cloudy
            # than it is worth a generic "unknown" icon.
            icon, reason = ("\u26c5" if is_daytime else "\U0001f319"), "no match, default"

    # TEMPORARY DEBUG - remove once icon selection looks right across a
    # few real days of emails.
    log(
        f"icon debug: short='{short_forecast}' pop={pop_value} "
        f"daytime={is_daytime} -> {icon} ({reason})"
    )

    return icon


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
    """Format an NWS period's startTime into a 'Weekday, Month Day' label,
    e.g. 'Saturday, September 12'."""
    if not start_time:
        return ""
    try:
        dt = datetime.fromisoformat(start_time)
        return dt.strftime("%A, %B %-d")
    except ValueError:
        return ""


def format_period_detail_html(period: Dict, label: str) -> str:
    """Render one period's bolded summary line plus wind/detailed text.
    label is a generic prefix ('Day' or 'Night') rather than the period's
    own name (e.g. 'Saturday'/'Saturday Night'), since the day-of-week now
    appears once in the date header above instead of per period."""
    temp = period.get('temperature')
    temp_unit = period.get('temperatureUnit', '')
    short_forecast = period.get('shortForecast', '')
    wind_speed = period.get('windSpeed', '')
    wind_dir = period.get('windDirection', '')
    detailed = period.get('detailedForecast', '')

    lines = [f"<p style='margin:0 0 10px;'>"]
    lines.append(f"<b>{label}: {temp}\u00b0{temp_unit}, {short_forecast}</b><br>")
    if wind_speed:
        lines.append(f"Wind: {wind_speed} {wind_dir}".rstrip() + "<br>")
    if detailed:
        lines.append(f"{detailed}<br>")
    lines.append("</p>")

    return "".join(lines)


def format_summary_boxes_html(day: Optional[Dict], night: Optional[Dict], rain_inches: Optional[float]) -> str:
    """Render the Day/Night H/L summary boxes for one date, plus a third
    Rain Total box - only shown when rain_inches is a positive amount."""
    box_style = (
        "flex:1;background:#f5f5f5;border-radius:8px;"
        "padding:10px 14px;display:flex;align-items:center;gap:10px;"
    )
    cells = []

    if day:
        pop = day.get('probabilityOfPrecipitation', {}) or {}
        icon = get_weather_emoji(
            day.get('shortForecast', ''), True, pop.get('value'), day.get('detailedForecast', '')
        )
        high = day.get('temperature')
        temp_unit = day.get('temperatureUnit', '')
        cells.append(
            f"<div style='{box_style}'>"
            f"<span style='font-size:22px;'>{icon}</span>"
            f"<span><span style='display:block;font-size:12px;color:#666;'>Day &middot; High</span>"
            f"<span style='font-size:17px;font-weight:bold;'>{high}\u00b0{temp_unit}</span></span>"
            f"</div>"
        )

    if night:
        pop = night.get('probabilityOfPrecipitation', {}) or {}
        icon = get_weather_emoji(
            night.get('shortForecast', ''), False, pop.get('value'), night.get('detailedForecast', '')
        )
        low = night.get('temperature')
        temp_unit = night.get('temperatureUnit', '')
        cells.append(
            f"<div style='{box_style}'>"
            f"<span style='font-size:22px;'>{icon}</span>"
            f"<span><span style='display:block;font-size:12px;color:#666;'>Night &middot; Low</span>"
            f"<span style='font-size:17px;font-weight:bold;'>{low}\u00b0{temp_unit}</span></span>"
            f"</div>"
        )

    # Rain Total box - omitted entirely for days with no forecast rain
    # (rain_inches is None or 0), rather than showing "0.00 in".
    if rain_inches:
        cells.append(
            f"<div style='{box_style}'>"
            f"<span style='font-size:22px;'>\U0001f4a7</span>"
            f"<span><span style='display:block;font-size:12px;color:#666;'>Rain Total</span>"
            f"<span style='font-size:17px;font-weight:bold;'>{rain_inches:.2f} in</span></span>"
            f"</div>"
        )

    return f"<div style='display:flex;gap:12px;margin-bottom:14px;'>{''.join(cells)}</div>"


def format_forecast_html(
    station_name: str,
    periods: List[Dict],
    generated_at: str,
    rain_totals: Optional[Dict] = None,
    actuals: Optional[Dict] = None,
) -> str:
    """Format NWS forecast periods into the full HTML email body: a header
    with the generation timestamp, an optional yesterday-actuals section,
    then one section per day with Day/Night (and, when applicable, Rain
    Total) summary boxes followed by the detailed bolded forecast text.
    rain_totals is {date: inches} from fetch_daily_rain_totals(); pass
    None/{} to omit rain boxes entirely. actuals is the dict returned by
    compute_yesterday_actuals(); pass None to omit the actuals section."""
    rain_totals = rain_totals or {}

    parts = [
        f"<p style='font-size:15px;font-weight:bold;margin:0 0 4px;'>{station_name} Forecast (Home Station)</p>",
        f"<p style='font-size:13px;color:#666;margin:0 0 14px;'>Generated on {generated_at}</p>",
        "<hr style='border:none;border-top:1px solid #ddd;margin:0 0 18px;'>",
    ]

    if actuals:
        parts.append(format_actuals_html(actuals))

    days = group_periods_into_days(periods)

    for idx, day in enumerate(days):
        ref_period = day['day'] or day['night']
        start_time = ref_period.get('startTime')
        date_label = format_date_label(start_time)
        divider = "padding-top:18px;border-top:1px solid #ddd;" if idx > 0 else ""

        # Look up this day's rain total using the same local calendar date
        # the periods themselves are anchored to.
        rain_inches = None
        if start_time:
            try:
                period_date = datetime.fromisoformat(start_time).astimezone(LOCAL_TZ).date()
                rain_inches = rain_totals.get(period_date)
            except ValueError:
                pass

        parts.append(f"<div style='margin-bottom:20px;{divider}'>")
        if date_label:
            parts.append(f"<p style='font-size:14px;font-weight:bold;margin:0 0 8px;'>{date_label}</p>")

        parts.append(format_summary_boxes_html(day['day'], day['night'], rain_inches))

        if day['day']:
            parts.append(format_period_detail_html(day['day'], "Day"))
        if day['night']:
            parts.append(format_period_detail_html(day['night'], "Night"))

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

    # Fetch rain totals separately - a failure here shouldn't block the
    # email, since fetch_daily_rain_totals() already degrades to {} on
    # error and format_forecast_html() simply omits the Rain Total box.
    rain_totals = fetch_daily_rain_totals()

    # Fetch yesterday's actual station observations (high/low/rain) from
    # the WU PWS history endpoint, if a station is configured. Degrades
    # gracefully: no STATION_ID, no WU_API_KEY, or a failed fetch all just
    # mean the actuals section is omitted rather than the email failing.
    station_id = os.getenv('STATION_ID')
    if station_id:
        yesterday_date = (datetime.now(LOCAL_TZ) - timedelta(days=1)).date()
        history_obs = fetch_wu_daily_history(station_id, yesterday_date)
        actuals = compute_actuals_from_history(history_obs, yesterday_date)
    else:
        log("⚠️  STATION_ID not set - skipping yesterday's actuals section")
        actuals = None

    # Compute the current time in Arizona (fixed UTC-7, no DST) for the
    # "Generated on" header, since GitHub Actions runners run in UTC.
    generated_at_dt = datetime.now(timezone.utc) + ARIZONA_UTC_OFFSET
    generated_at = generated_at_dt.strftime("%B %-d, %Y at %-I:%M %p")

    body_html = format_forecast_html(station_name, periods, generated_at, rain_totals, actuals)
    subject = f"{station_name} Forecast"

    send_forecast_email(body_html, subject)

    log("✅ Daily forecast email complete")


if __name__ == "__main__":
    main()
