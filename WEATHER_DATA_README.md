# Weather Forecast Snapshots

Automated daily collection of weather forecasts from multiple sources for historical comparison and accuracy analysis.

## Overview

This repository automatically captures daily weather forecasts at 6:00 AM EST using GitHub Actions. Forecasts are collected from:

- **National Weather Service (NWS)** - Official US government weather forecasts
- **Weather Underground (WU)** - Community-driven weather data
- **ECMWF** (via Open-Meteo) - European Centre for Medium-Range Weather Forecasts

## Repository Structure

```
weather-data/
├── snapshots/              # Daily forecast snapshots
│   ├── 2026-03-06.json    # Historical snapshots by date
│   ├── 2026-03-07.json
│   ├── 2026-03-08.json
│   └── latest.json        # Most recent snapshot
├── .github/
│   └── workflows/
│       └── fetch-forecasts.yml  # GitHub Actions workflow
├── scripts/
│   └── fetch_forecasts.py      # Python script for data collection
└── README.md
```

## Snapshot Format

Each snapshot is a JSON file containing forecasts from all three sources:

```json
{
  "timestamp": "2026-03-06T06:00:00-05:00",
  "station": {
    "id": "KMILANSY123",
    "name": "Lansing Station",
    "latitude": 42.7325,
    "longitude": -84.5555
  },
  "forecasts": {
    "nws": {
      "source": "National Weather Service",
      "periods": [ /* forecast periods */ ]
    },
    "weatherUnderground": {
      "source": "Weather Underground",
      "periods": [ /* forecast periods */ ]
    },
    "ecmwf": {
      "source": "ECMWF via Open-Meteo",
      "periods": [ /* forecast periods */ ]
    }
  }
}
```

## Setup Instructions

### 1. Create Repository

1. Create a new GitHub repository named `weather-data` (or your preferred name)
2. Set visibility to Public or Private based on your preference
3. Clone this repository to your local machine

### 2. Configure Station Coordinates

Add the following secrets to your GitHub repository (Settings → Secrets and variables → Actions):

- `STATION_ID`: Your weather station identifier (e.g., `KMILANSY123`)
- `STATION_NAME`: Display name for your station (e.g., `Lansing Station`)
- `STATION_LAT`: Latitude of your station (e.g., `42.7325`)
- `STATION_LON`: Longitude of your station (e.g., `-84.5555`)

### 3. Enable GitHub Actions

1. Go to the "Actions" tab in your repository
2. Enable workflows if prompted
3. The workflow will run automatically every day at 6:00 AM EST
4. You can also trigger it manually using the "Run workflow" button

### 4. Update iOS App

In your iOS Weather App, update `GitHubSnapshotService.swift`:

```swift
private let githubUsername = "YOUR_GITHUB_USERNAME"
private let repositoryName = "weather-data"
```

Replace `YOUR_GITHUB_USERNAME` with your actual GitHub username.

## Usage in iOS App

The iOS Weather App can fetch historical snapshots using direct GitHub raw URLs:

```swift
// Fetch latest snapshot
let snapshot = await snapshotService.fetchLatestSnapshot()

// Fetch specific date
let snapshot = await snapshotService.fetchSnapshot(for: "2026-03-06")

// List available snapshots
let dates = await snapshotService.fetchAvailableSnapshotDates()
```

### Accessing Snapshots Directly

You can also access snapshots directly via browser or curl:

```bash
# Latest snapshot
https://raw.githubusercontent.com/USERNAME/weather-data/main/snapshots/latest.json

# Specific date
https://raw.githubusercontent.com/USERNAME/weather-data/main/snapshots/2026-03-06.json
```

## Workflow Schedule

The GitHub Actions workflow runs on the following schedule:

- **Scheduled Run**: Daily at 6:00 AM EST (11:00 UTC)
- **Manual Trigger**: Can be triggered anytime from the Actions tab
- **Estimated Runtime**: ~1 minute per execution
- **Monthly Usage**: ~30 minutes (well within free tier limits)

## Data Sources

### National Weather Service (NWS)
- **API**: `api.weather.gov`
- **Rate Limit**: No strict limit, reasonable usage expected
- **Coverage**: United States
- **Forecast Range**: 7-10 days

### Weather Underground (WU)
- **Status**: Free API deprecated
- **Note**: Currently returns empty data. Implement alternative if needed.
- **Options**: Use paid WU API, Weather.com API, or scraping

### ECMWF (Open-Meteo)
- **API**: `api.open-meteo.com`
- **Model**: ECMWF IFS HRES 9km
- **Rate Limit**: 10,000 requests/day (free tier)
- **Coverage**: Global
- **Forecast Range**: 10 days

## Storage Considerations

- **File Size**: ~50KB per snapshot
- **Daily Storage**: ~50KB
- **Annual Storage**: ~18MB
- **GitHub Free Tier**: 1GB repository size limit

This usage is well within GitHub's limits.

## Troubleshooting

### Workflow Not Running

1. Check if Actions are enabled in repository settings
2. Verify the cron schedule (uses UTC time)
3. Check workflow run history in the Actions tab

### No Data Collected

1. Verify station coordinates are set correctly in secrets
2. Check individual API endpoints:
   - NWS: `https://api.weather.gov/points/LAT,LON`
   - Open-Meteo: `https://api.open-meteo.com/v1/forecast?latitude=LAT&longitude=LON&daily=temperature_2m_max`
3. Review workflow logs for error messages

### iOS App Not Loading Snapshots

1. Verify GitHub username is correct in `GitHubSnapshotService.swift`
2. Check if repository is public (or properly authenticated if private)
3. Test snapshot URLs directly in browser
4. Check iOS app network logs

## Future Enhancements

Potential improvements for this system:

- [ ] Add actual weather observations for forecast accuracy comparison
- [ ] Calculate and track forecast accuracy metrics
- [ ] Support multiple weather stations
- [ ] Add automated cleanup of old snapshots (retention policy)
- [ ] Implement Weather Underground paid API or alternative
- [ ] Add notifications for significant forecast changes
- [ ] Create web dashboard for viewing historical data
- [ ] Add more forecast sources (Weather.com, AccuWeather, etc.)

## License

This project is provided as-is for personal use. Weather data is sourced from public APIs:

- NWS data is public domain (US Government)
- Open-Meteo data is provided under CC BY 4.0 license
- Weather Underground data subject to their terms of service

## Contributing

Feel free to submit issues or pull requests for:

- Bug fixes
- Additional weather sources
- Improved error handling
- Documentation improvements

## Questions or Issues?

Open an issue in this repository or check the workflow run logs in the Actions tab for debugging information.

---

**Last Updated**: March 6, 2026
