#!/usr/bin/env python3
"""
Fetch daily forecasts from NWS, Weather Underground, and ECMWF (Open-Meteo)
and save as JSON snapshot for historical comparison.

This script is designed to run in GitHub Actions as a scheduled job.
"""

import json
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path


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
            from datetime import datetime
            local_dt = datetime.strptime(obs_time_local, "%Y-%m-%d %H:%M:%S")
            
            # For Arizona (MST = UTC-7, no DST)
            # Adjust this offset based on your station's timezone
            from datetime import timedelta
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


def fetch_weather_underground_forecast(latitude: float, longitude: float) -> Optional[tuple[List[Dict], Dict]]:
    """
    Fetch Weather Underground forecast via Weather.com v3 API.
    Uses PWS-compatible API key.
    """
    log("📡 Fetching Weather Underground forecast...")
    
    # Get API key from environment
    api_key = os.getenv('WU_API_KEY')
    if not api_key:
        log("⚠️  WU_API_KEY not found in environment - skipping WU forecast")
        return [], {}
    
    # Save the fetch time
    fetch_time = datetime.now(timezone.utc).isoformat()
    
    # Weather Underground v3 daily forecast API (5-day forecast)
    params = {
        'geocode': f'{latitude},{longitude}',
        'format': 'json',
        'units': 'e',  # English units (Fahrenheit, mph)
        'language': 'en-US',
        'apiKey': api_key
    }
    
    url = f"https://api.weather.com/v3/wx/forecast/daily/5day?{urllib.parse.urlencode(params)}"
    data = fetch_json(url)
    
    if not data:
        log("❌ Failed to get Weather Underground forecast data")
        return [], {}
    
    # Metadata - WU doesn't provide explicit update time, so we use fetch time
    metadata = {
        'fetched_at': fetch_time,
        'note': 'Weather Underground does not provide explicit forecast issue time'
    }
    
    # Convert WU v3 format to ForecastPeriod-like format
    periods = []
    
    try:
        day_count = len(data.get('dayOfWeek', []))
        
        for i in range(day_count):
            day_name = data.get('dayOfWeek', [])[i] if i < len(data.get('dayOfWeek', [])) else None
            temp_max = data.get('temperatureMax', [])[i] if i < len(data.get('temperatureMax', [])) else None
            temp_min = data.get('temperatureMin', [])[i] if i < len(data.get('temperatureMin', [])) else None
            narrative = data.get('narrative', [])[i] if i < len(data.get('narrative', [])) else ''
            valid_time = data.get('validTimeLocal', [])[i] if i < len(data.get('validTimeLocal', [])) else ''
            
            # Skip if missing critical data
            if not day_name or temp_max is None or temp_min is None:
                continue
            
            # Get daypart data (contains day and night details)
            daypart = data.get('daypart', [{}])[0] if data.get('daypart') else {}
            
            # Day period
            day_idx = i * 2
            if day_idx < len(daypart.get('windSpeed', [])):
                wind_speed = daypart.get('windSpeed', [])[day_idx]
                wind_dir = daypart.get('windDirectionCardinal', [])[day_idx] if day_idx < len(daypart.get('windDirectionCardinal', [])) else 'N'
                phrase = daypart.get('wxPhraseLong', [])[day_idx] if day_idx < len(daypart.get('wxPhraseLong', [])) else 'Partly Cloudy'
                precip_chance = daypart.get('precipChance', [])[day_idx] if day_idx < len(daypart.get('precipChance', [])) else None
                humidity = daypart.get('relativeHumidity', [])[day_idx] if day_idx < len(daypart.get('relativeHumidity', [])) else None
                
                periods.append({
                    'number': i * 2 + 1,
                    'name': day_name,
                    'temperature': temp_max,
                    'temperatureUnit': 'F',
                    'windSpeed': f'{wind_speed} mph' if wind_speed else '0 mph',
                    'windDirection': wind_dir,
                    'shortForecast': phrase,
                    'detailedForecast': narrative,
                    'icon': '',
                    'startTime': valid_time,
                    'probabilityOfPrecipitation': {'value': precip_chance} if precip_chance is not None else None,
                    'relativeHumidity': {'value': humidity} if humidity is not None else None
                })
            
            # Night period
            night_idx = i * 2 + 1
            if night_idx < len(daypart.get('windSpeed', [])):
                wind_speed = daypart.get('windSpeed', [])[night_idx]
                wind_dir = daypart.get('windDirectionCardinal', [])[night_idx] if night_idx < len(daypart.get('windDirectionCardinal', [])) else 'N'
                phrase = daypart.get('wxPhraseLong', [])[night_idx] if night_idx < len(daypart.get('wxPhraseLong', [])) else 'Partly Cloudy'
                precip_chance = daypart.get('precipChance', [])[night_idx] if night_idx < len(daypart.get('precipChance', [])) else None
                humidity = daypart.get('relativeHumidity', [])[night_idx] if night_idx < len(daypart.get('relativeHumidity', [])) else None
                night_name = daypart.get('daypartName', [])[night_idx] if night_idx < len(daypart.get('daypartName', [])) else f'{day_name} Night'
                
                periods.append({
                    'number': i * 2 + 2,
                    'name': night_name if night_name else f'{day_name} Night',
                    'temperature': temp_min,
                    'temperatureUnit': 'F',
                    'windSpeed': f'{wind_speed} mph' if wind_speed else '0 mph',
                    'windDirection': wind_dir,
                    'shortForecast': phrase,
                    'detailedForecast': narrative,
                    'icon': '',
                    'startTime': valid_time,
                    'probabilityOfPrecipitation': {'value': precip_chance} if precip_chance is not None else None,
                    'relativeHumidity': {'value': humidity} if humidity is not None else None
                })
        
        log(f"✅ Fetched {len(periods)} Weather Underground forecast periods")
        log(f"   Fetched at: {fetch_time}")
        return periods, metadata
        
    except (KeyError, IndexError, TypeError) as e:
        log(f"❌ Error parsing WU data: {e}")
        return [], {}


def fetch_ecmwf_forecast(latitude: float, longitude: float) -> Optional[tuple[List[Dict], Dict]]:
    """Fetch ECMWF forecast via Open-Meteo."""
    log("📡 Fetching ECMWF forecast via Open-Meteo...")
    
    # Build Open-Meteo URL with ECMWF model
    params = {
        'latitude': str(latitude),
        'longitude': str(longitude),
        'daily': 'temperature_2m_max,temperature_2m_min,weathercode,precipitation_sum,windspeed_10m_max,winddirection_10m_dominant',
        'temperature_unit': 'fahrenheit',
        'windspeed_unit': 'mph',
        'precipitation_unit': 'inch',
        'timezone': 'America/Phoenix',  # Fixed: Use Arizona timezone (MST, no DST)
        'forecast_days': '10',
        'models': 'ecmwf_ifs025'
    }
    
    url = f"https://api.open-meteo.com/v1/forecast?{urllib.parse.urlencode(params)}"
    data = fetch_json(url)
    
    if not data or 'daily' not in data:
        log("❌ Failed to get ECMWF forecast data")
        return None
    
    # Extract metadata
    metadata = {
        'generationtime_ms': data.get('generationtime_ms'),
        'utc_offset_seconds': data.get('utc_offset_seconds'),
        'model': 'ecmwf_ifs025'
    }
    
    # Determine which ECMWF run this is based on current UTC time
    now_utc = datetime.now(timezone.utc)
    hour = now_utc.hour
    
    # ECMWF runs at 00:00 and 12:00 UTC
    if hour < 12:
        # Morning fetch - using previous night's 00:00 run
        model_run = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        # Afternoon/evening fetch - using today's 12:00 run
        model_run = now_utc.replace(hour=12, minute=0, second=0, microsecond=0)
    
    metadata['model_run_time'] = model_run.isoformat()
    
    # Convert Open-Meteo format to ForecastPeriod-like format
    daily = data['daily']
    periods = []
    
    for i in range(len(daily['time'])):
        date = daily['time'][i]
        
        # Day period
        day_period = {
            'number': i * 2 + 1,
            'name': format_day_name(date, True),
            'temperature': int(daily['temperature_2m_max'][i]),
            'temperatureUnit': 'F',
            'windSpeed': f"{int(daily['windspeed_10m_max'][i])} mph",
            'windDirection': interpret_wind_direction(daily['winddirection_10m_dominant'][i]),
            'shortForecast': interpret_weather_code(daily['weathercode'][i], True),
            'detailedForecast': interpret_weather_code(daily['weathercode'][i], True),
            'icon': '',
            'startTime': f"{date}T12:00:00-07:00",  # Arizona MST (UTC-7, no DST)
            'probabilityOfPrecipitation': {
                'value': estimate_precip_probability(daily['precipitation_sum'][i])
            },
            'relativeHumidity': None
        }
        
        # Night period
        night_period = {
            'number': i * 2 + 2,
            'name': format_day_name(date, False),
            'temperature': int(daily['temperature_2m_min'][i]),
            'temperatureUnit': 'F',
            'windSpeed': f"{int(daily['windspeed_10m_max'][i])} mph",
            'windDirection': interpret_wind_direction(daily['winddirection_10m_dominant'][i]),
            'shortForecast': interpret_weather_code(daily['weathercode'][i], False),
            'detailedForecast': interpret_weather_code(daily['weathercode'][i], False),
            'icon': '',
            'startTime': f"{date}T00:00:00-07:00",  # Arizona MST (UTC-7, no DST)
            'probabilityOfPrecipitation': {
                'value': estimate_precip_probability(daily['precipitation_sum'][i])
            },
            'relativeHumidity': None
        }
        
        periods.append(day_period)
        periods.append(night_period)
    
    log(f"✅ Fetched {len(periods)} ECMWF forecast periods")
    log(f"   Model run: {metadata['model_run_time']}")
    
    return periods, metadata


def format_day_name(date_str: str, is_daytime: bool) -> str:
    """Format day name (e.g., 'Today', 'Tomorrow', 'Monday')."""
    from datetime import date, timedelta
    
    forecast_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    today = date.today()
    
    days_diff = (forecast_date - today).days
    
    if days_diff == 0:
        return "Today" if is_daytime else "Tonight"
    elif days_diff == 1:
        return "Tomorrow" if is_daytime else "Tomorrow Night"
    else:
        day_name = forecast_date.strftime('%A')
        return day_name if is_daytime else f"{day_name} Night"


def interpret_weather_code(code: int, is_daytime: bool) -> str:
    """Interpret WMO weather code to text description."""
    weather_codes = {
        0: "Clear",
        1: "Mostly Clear",
        2: "Partly Cloudy",
        3: "Overcast",
        45: "Foggy",
        48: "Foggy",
        51: "Light Drizzle",
        53: "Drizzle",
        55: "Heavy Drizzle",
        56: "Freezing Drizzle",
        57: "Freezing Drizzle",
        61: "Light Rain",
        63: "Moderate Rain",
        65: "Heavy Rain",
        66: "Freezing Rain",
        67: "Freezing Rain",
        71: "Light Snow",
        73: "Moderate Snow",
        75: "Heavy Snow",
        77: "Snow Grains",
        80: "Rain Showers",
        81: "Rain Showers",
        82: "Heavy Rain Showers",
        85: "Snow Showers",
        86: "Heavy Snow Showers",
        95: "Thunderstorms",
        96: "Thunderstorms with Hail",
        99: "Severe Thunderstorms"
    }
    
    return weather_codes.get(code, "Partly Cloudy")


def interpret_wind_direction(degrees: float) -> str:
    """Convert wind degrees to cardinal direction."""
    directions = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                  "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    index = int((degrees + 11.25) / 22.5) % 16
    return directions[index]


def estimate_precip_probability(amount: float) -> int:
    """Estimate precipitation probability from amount."""
    if amount == 0:
        return 0
    elif amount < 0.1:
        return 20
    elif amount < 0.25:
        return 40
    elif amount < 0.5:
        return 60
    elif amount < 1.0:
        return 80
    else:
        return 90


def create_snapshot(
    station_id: str,
    station_name: str,
    latitude: float,
    longitude: float,
    nws_periods: List[Dict],
    wu_periods: List[Dict],
    ecmwf_periods: List[Dict],
    nws_metadata: Dict = None,
    wu_metadata: Dict = None,
    ecmwf_metadata: Dict = None
) -> Dict:
    """Create forecast snapshot JSON structure."""
    
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
            },
            'weatherUnderground': {
                'source': 'Weather Underground',
                'periods': wu_periods or [],
                'metadata': wu_metadata or {}
            },
            'ecmwf': {
                'source': 'ECMWF via Open-Meteo',
                'periods': ecmwf_periods or [],
                'metadata': ecmwf_metadata or {}
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
    """Create hourly forecast snapshot JSON structure (NWS only) with optional observations."""
    
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
    
    # Get configuration from environment variables
    station_id = os.getenv('STATION_ID', 'DEFAULT_STATION')
    station_name = os.getenv('STATION_NAME', 'Default Station')
    latitude = float(os.getenv('STATION_LAT', '42.7325'))
    longitude = float(os.getenv('STATION_LON', '-84.5555'))
    output_dir = Path(os.getenv('OUTPUT_DIR', 'snapshots'))
    
    log(f"📍 Station: {station_name} ({station_id})")
    log(f"📍 Location: {latitude}, {longitude}")
    log(f"📁 Output directory: {output_dir}")
    
    # Fetch daily forecasts from all sources
    log("\n" + "=" * 60)
    log("DAILY FORECASTS")
    log("=" * 60)
    
    nws_result = fetch_nws_forecast(latitude, longitude)
    nws_periods, nws_metadata = (nws_result if nws_result else (None, {}))
    
    wu_result = fetch_weather_underground_forecast(latitude, longitude)
    wu_periods, wu_metadata = (wu_result if wu_result else ([], {}))
    
    ecmwf_result = fetch_ecmwf_forecast(latitude, longitude)
    ecmwf_periods, ecmwf_metadata = (ecmwf_result if ecmwf_result else (None, {}))
    
    # Check if we got at least one successful forecast
    if not nws_periods and not wu_periods and not ecmwf_periods:
        log("❌ Failed to fetch any daily forecasts - aborting")
        sys.exit(1)
    
    # Create daily snapshot
    snapshot = create_snapshot(
        station_id=station_id,
        station_name=station_name,
        latitude=latitude,
        longitude=longitude,
        nws_periods=nws_periods,
        wu_periods=wu_periods,
        ecmwf_periods=ecmwf_periods,
        nws_metadata=nws_metadata,
        wu_metadata=wu_metadata,
        ecmwf_metadata=ecmwf_metadata
    )
    
    # Save daily snapshot
    daily_file, latest_file = save_snapshot(snapshot, output_dir)
    
    # Fetch and save hourly forecasts
    log("\n" + "=" * 60)
    log("HOURLY FORECASTS & OBSERVATIONS")
    log("=" * 60)
    
    nws_hourly_result = fetch_nws_hourly_forecast(latitude, longitude)
    
    if nws_hourly_result:
        nws_hourly_periods, nws_hourly_metadata = nws_hourly_result
        log(f"✅ Successfully fetched hourly forecast")
    else:
        log("⚠️  Failed to fetch hourly forecast - creating empty snapshot")
        nws_hourly_periods = []
        nws_hourly_metadata = {'error': 'Failed to fetch hourly forecast'}
    
    # Fetch current observations for archival (NEW)
    observations = fetch_wu_hourly_observations(station_id)
    
    # Create hourly snapshot with observations (even if fetch failed, to indicate the attempt)
    hourly_snapshot = create_hourly_snapshot(
        station_id=station_id,
        station_name=station_name,
        latitude=latitude,
        longitude=longitude,
        nws_hourly_periods=nws_hourly_periods,
        nws_hourly_metadata=nws_hourly_metadata,
        observations=observations  # NEW - include observations for archival
    )
    
    # Save hourly snapshot
    hourly_file, latest_hourly_file = save_hourly_snapshot(hourly_snapshot, output_dir)
    
    # Summary
    log("\n" + "=" * 60)
    log("📊 Snapshot Summary:")
    log("=" * 60)
    log("DAILY FORECASTS:")
    log(f"   NWS periods: {len(nws_periods) if nws_periods else 0}")
    if nws_metadata.get('updated'):
        log(f"   NWS updated: {nws_metadata['updated']}")
    log(f"   WU periods: {len(wu_periods) if wu_periods else 0}")
    if wu_metadata.get('fetched_at'):
        log(f"   WU fetched: {wu_metadata['fetched_at']}")
    log(f"   ECMWF periods: {len(ecmwf_periods) if ecmwf_periods else 0}")
    if ecmwf_metadata.get('model_run_time'):
        log(f"   ECMWF model run: {ecmwf_metadata['model_run_time']}")
    log(f"   Files created: {daily_file.name}, {latest_file.name}")
    
    log("\nHOURLY FORECASTS:")
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
