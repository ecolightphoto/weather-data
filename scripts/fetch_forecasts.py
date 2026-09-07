#!/usr/bin/env python3
"""
Fetch daily and hourly forecasts from NWS and save as JSON snapshot
for historical comparison.

This script is designed to run in GitHub Actions as a scheduled job.
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path


# This project only ever tracks one specific Flagstaff-area location -
# hardcoded so it can never silently drift to the wrong place due to a
# missing/incorrect secret. (35°14'11.3"N 111°39'56.6"W)
FLAGSTAFF_LATITUDE = 35.236472
FLAGSTAFF_LONGITUDE = -111.665722
FLAGSTAFF_STATION_NAME = "Flagstaff"


def log(message: str):
    """Print timestamped log message."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")


def fetch_json(url: str, timeout: int = 30) -> Optional[Dict]:
    """Fetch JSON from URL with error handling."""
    try:
        log(f"Fetching: {url}")
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'WeatherApp-ForecastSnapshot/1.0 (GitHub Actions)',
                'Accept': 'application/json'
            }
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode('utf-8'))
            log(f"✅ Successfully fetched data from {url}")
            return data
    except urllib.error.HTTPError as e:
        log(f"❌ HTTP Error {e.code}: {e.reason} - {url}")
        return None
    except urllib.error.URLError as e:
        log(f"❌ URL Error: {e.reason} - {url}")
        return None
    except json.JSONDecodeError as e:
        log(f"❌ JSON Decode Error: {e} - {url}")
        return None
    except Exception as e:
        log(f"❌ Unexpected error: {e} - {url}")
        return None


def fetch_nws_forecast(latitude: float, longitude: float) -> Optional[tuple[List[Dict], Dict]]:
    """Fetch NWS daily forecast and metadata."""
    log("📡 Fetching NWS daily forecast...")

    # Step 1: Get forecast URL from points endpoint
    points_url = f"https://api.weather.gov/points/{latitude},{longitude}"
    points_data = fetch_json(points_url)

    if not points_data or 'properties' not in points_data:
        log("❌ Failed to get NWS points data")
        return None

    forecast_url = points_data['properties'].get('forecast')
    if not forecast_url:
        log("❌ No forecast URL in NWS points response")
        return None

    # Step 2: Fetch the actual forecast
    forecast_data = fetch_json(forecast_url)

    if not forecast_data or 'properties' not in forecast_data:
        log("❌ Failed to get NWS forecast data")
        return None

    properties = forecast_data['properties']
    periods = properties.get('periods', [])

    # Extract metadata about when forecast was updated
    metadata = {
        'updated': properties.get('updated'),
        'generatedAt': properties.get('generatedAt'),
        'updateTime': properties.get('updateTime')
    }

    log(f"✅ Fetched {len(periods)} NWS daily forecast periods")
    if metadata.get('updated'):
        log(f"   Last updated: {metadata['updated']}")

    return periods, metadata


def fetch_wu_hourly_observations(station_id: str) -> Optional[List[Dict]]:
    """
    Fetch hourly observations from Weather Underground PWS.
    Returns observations from the last 24 hours for archival purposes.
    """
    log("📡 Fetching WU hourly observations for archival...")

    # Get API key from environment
    api_key = os.getenv('WU_API_KEY')
    if not api_key:
        log("⚠️  WU_API_KEY not found in environment - skipping observations")
        return []

    # Use the 1-day observations endpoint
    params = {
        'stationId': station_id,
        'format': 'json',
        'units': 'e',  # English/Imperial units
        'apiKey': api_key
    }

    url = f"https://api.weather.com/v2/pws/observations/all/1day?{urllib.parse.urlencode(params)}"
    data = fetch_json(url)

    if not data or 'observations' not in data:
        log("❌ Failed to get WU observations")
        return []

    observations = data['observations']
    log(f"✅ Fetched {len(observations)} WU observations")

    # Convert to simplified format for archival
    hourly_obs = []

    for obs in observations:
        obs_time_local = obs.get('obsTimeLocal')
        imperial = obs.get('imperial')

        if not obs_time_local or not imperial:
            continue

        # Convert local time to UTC ISO8601
        try:
            # Parse local time (format: "2026-03-15 05:00:00")
            local_dt = datetime.strptime(obs_time_local, "%Y-%m-%d %H:%M:%S")

            # For Arizona (MST = UTC-7, no DST)
            # Adjust this offset based on your station's timezone
            utc_dt = local_dt + timedelta(hours=7)  # Arizona MST to UTC
            utc_dt = utc_dt.replace(tzinfo=timezone.utc)

            # Extract observation data
            # Use tempAvg if temp is not available (for aggregated observations)
            temp = imperial.get('temp')
            if temp is None:
                temp = imperial.get('tempAvg')

            hourly_obs.append({
                'time': utc_dt.isoformat().replace('+00:00', 'Z'),
                'temp': temp,
                'precip': imperial.get('precipTotal'),
                'humidity': obs.get('humidityAvg'),
                'windSpeed': imperial.get('windspeedAvg')
            })

        except Exception as e:
            log(f"⚠️  Error parsing observation time '{obs_time_local}': {e}")
            continue

    log(f"✅ Converted {len(hourly_obs)} observations to archive format")
    return hourly_obs


def fetch_nws_hourly_forecast(latitude: float, longitude: float) -> Optional[tuple[List[Dict], Dict]]:
    """Fetch NWS hourly forecast and metadata."""
    log("📡 Fetching NWS hourly forecast...")

    # Step 1: Get forecast URL from points endpoint
    points_url = f"https://api.weather.gov/points/{latitude},{longitude}"
    points_data = fetch_json(points_url)

    if not points_data or 'properties' not in points_data:
        log("❌ Failed to get NWS points data for hourly forecast")
        return None

    forecast_hourly_url = points_data['properties'].get('forecastHourly')
    if not forecast_hourly_url:
        log("❌ No hourly forecast URL in NWS points response")
        return None

    # Step 2: Fetch the actual hourly forecast
    forecast_data = fetch_json(forecast_hourly_url)

    if not forecast_data or 'properties' not in forecast_data:
        log("❌ Failed to get NWS hourly forecast data")
        return None

    properties = forecast_data['properties']
    periods = properties.get('periods', [])

    # Extract metadata about when forecast was updated
    metadata = {
        'updated': properties.get('updated'),
        'generatedAt': properties.get('generatedAt'),
        'updateTime': properties.get('updateTime')
    }

    log(f"✅ Fetched {len(periods)} NWS hourly forecast periods")
    if metadata.get('updated'):
        log(f"   Last updated: {metadata['updated']}")

    return periods, metadata


def create_snapshot(
    station_id: str,
    station_name: str,
    latitude: float,
    longitude: float,
    nws_periods: List[Dict],
    nws_metadata: Dict = None
) -> Dict:
    """Create daily forecast snapshot JSON structure (NWS only)."""

    now = datetime.now(timezone.utc)
    # Use UTC timestamp with 'Z' suffix for clarity
    timestamp = now.isoformat(timespec='microseconds').replace('+00:00', 'Z')

    snapshot = {
        'timestamp': timestamp,
        'station': {
            'id': station_id,
            'name': station_name,
            'latitude': latitude,
            'longitude': longitude
        },
        'forecasts': {
            'nws': {
                'source': 'National Weather Service',
                'periods': nws_periods or [],
                'metadata': nws_metadata or {}
            }
        }
    }

    return snapshot


def create_hourly_snapshot(
    station_id: str,
    station_name: str,
    latitude: float,
    longitude: float,
    nws_hourly_periods: List[Dict],
    nws_hourly_metadata: Dict = None,
    observations: List[Dict] = None
) -> Dict:
    """Create hourly forecast snapshot JSON structure (NWS only) with optional WU observations."""

    now = datetime.now(timezone.utc)
    # Use UTC timestamp with 'Z' suffix for clarity
    timestamp = now.isoformat(timespec='microseconds').replace('+00:00', 'Z')

    snapshot = {
        'timestamp': timestamp,
        'station': {
            'id': station_id,
            'name': station_name,
            'latitude': latitude,
            'longitude': longitude
        },
        'forecasts': {
            'nws': {
                'source': 'National Weather Service - Hourly',
                'periods': nws_hourly_periods or [],
                'metadata': nws_hourly_metadata or {}
            }
        }
    }

    # Add observations if available (for historical archival)
    if observations:
        snapshot['observations'] = {
            'source': 'Weather Underground PWS',
            'stationId': station_id,
            'capturedAt': timestamp,
            'hours': observations
        }
        log(f"✅ Added {len(observations)} cached observations to hourly snapshot")

    return snapshot


def save_snapshot(snapshot: Dict, output_dir: Path):
    """Save snapshot to JSON files."""

    # Create output directory if it doesn't exist
    output_dir.mkdir(parents=True, exist_ok=True)

    # Get current date for filename
    now = datetime.now()
    date_str = now.strftime('%Y-%m-%d')

    # Save with date-only filename (one snapshot per day for navigation)
    daily_file = output_dir / f"{date_str}.json"
    with open(daily_file, 'w') as f:
        json.dump(snapshot, f, indent=2)
    log(f"💾 Saved snapshot to {daily_file}")

    # Also save as latest.json
    latest_file = output_dir / "latest.json"
    with open(latest_file, 'w') as f:
        json.dump(snapshot, f, indent=2)
    log(f"💾 Saved snapshot to {latest_file}")

    return daily_file, latest_file


def save_hourly_snapshot(snapshot: Dict, output_dir: Path):
    """Save hourly snapshot to JSON files."""

    # Create output directory if it doesn't exist
    output_dir.mkdir(parents=True, exist_ok=True)

    # Get current date for filename
    now = datetime.now()
    date_str = now.strftime('%Y-%m-%d')

    # Save with date-only filename with -hourly suffix
    hourly_file = output_dir / f"{date_str}-hourly.json"
    with open(hourly_file, 'w') as f:
        json.dump(snapshot, f, indent=2)
    log(f"💾 Saved hourly snapshot to {hourly_file}")

    # Also save as latest-hourly.json
    latest_hourly_file = output_dir / "latest-hourly.json"
    with open(latest_hourly_file, 'w') as f:
        json.dump(snapshot, f, indent=2)
    log(f"💾 Saved hourly snapshot to {latest_hourly_file}")

    return hourly_file, latest_hourly_file


def main():
    """Main execution function."""
    log("🚀 Starting forecast snapshot collection")

    # Get configuration from environment variables.
    # Location is intentionally NOT read from the environment - see the
    # FLAGSTAFF_LATITUDE/FLAGSTAFF_LONGITUDE constants above. STATION_ID is
    # still configurable since it identifies your specific WU PWS station.
    station_id = os.getenv('STATION_ID', 'DEFAULT_STATION')
    station_name = FLAGSTAFF_STATION_NAME
    latitude = FLAGSTAFF_LATITUDE
    longitude = FLAGSTAFF_LONGITUDE
    output_dir = Path(os.getenv('OUTPUT_DIR', 'snapshots'))

    log(f"📍 Station: {station_name} ({station_id})")
    log(f"📍 Location: {latitude}, {longitude}")
    log(f"📁 Output directory: {output_dir}")

    # Fetch daily forecast
    log("\n" + "=" * 60)
    log("DAILY FORECAST")
    log("=" * 60)

    nws_result = fetch_nws_forecast(latitude, longitude)
    nws_periods, nws_metadata = (nws_result if nws_result else (None, {}))

    if not nws_periods:
        log("❌ Failed to fetch daily forecast - aborting")
        sys.exit(1)

    # Create daily snapshot
    snapshot = create_snapshot(
        station_id=station_id,
        station_name=station_name,
        latitude=latitude,
        longitude=longitude,
        nws_periods=nws_periods,
        nws_metadata=nws_metadata
    )

    # Save daily snapshot
    daily_file, latest_file = save_snapshot(snapshot, output_dir)

    # Fetch and save hourly forecast
    log("\n" + "=" * 60)
    log("HOURLY FORECAST")
    log("=" * 60)

    nws_hourly_result = fetch_nws_hourly_forecast(latitude, longitude)

    if nws_hourly_result:
        nws_hourly_periods, nws_hourly_metadata = nws_hourly_result
        log(f"✅ Successfully fetched hourly forecast")
    else:
        log("⚠️  Failed to fetch hourly forecast - creating empty snapshot")
        nws_hourly_periods = []
        nws_hourly_metadata = {'error': 'Failed to fetch hourly forecast'}

    # Fetch current observations for archival
    observations = fetch_wu_hourly_observations(station_id)

    # Create hourly snapshot with observations (even if fetch failed, to indicate the attempt)
    hourly_snapshot = create_hourly_snapshot(
        station_id=station_id,
        station_name=station_name,
        latitude=latitude,
        longitude=longitude,
        nws_hourly_periods=nws_hourly_periods,
        nws_hourly_metadata=nws_hourly_metadata,
        observations=observations
    )

    # Save hourly snapshot
    hourly_file, latest_hourly_file = save_hourly_snapshot(hourly_snapshot, output_dir)

    # Summary
    log("\n" + "=" * 60)
    log("📊 Snapshot Summary:")
    log("=" * 60)
    log("DAILY FORECAST:")
    log(f"   NWS periods: {len(nws_periods) if nws_periods else 0}")
    if nws_metadata.get('updated'):
        log(f"   NWS updated: {nws_metadata['updated']}")
    log(f"   Files created: {daily_file.name}, {latest_file.name}")

    log("\nHOURLY FORECAST:")
    log(f"   NWS hourly periods: {len(nws_hourly_periods)}")
    if nws_hourly_metadata.get('updated'):
        log(f"   NWS hourly updated: {nws_hourly_metadata['updated']}")
    if nws_hourly_metadata.get('error'):
        log(f"   ⚠️  Error: {nws_hourly_metadata['error']}")
    log(f"   Cached observations: {len(observations) if observations else 0}")
    if observations:
        log(f"   ✅ Observations archived for historical comparison")
    log(f"   Files created: {hourly_file.name}, {latest_hourly_file.name}")
    log("=" * 60)
    log("✅ Forecast snapshot collection complete")


if __name__ == "__main__":
    main()
