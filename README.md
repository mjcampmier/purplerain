# purplerain

Resumable bulk downloads of historical data from the [PurpleAir API](https://api.purpleair.com/).

- `PurpleAirClient`: a small API client with retries, rate limiting, and support for private sensors (read keys).
- `PurpleAirNetworkDownloader`: downloads long histories for many sensors in fixed-size chunks. It records progress after every chunk, so an interrupted run picks up where it left off.

## Installation

Requires Python 3.10+.

```bash
pip install -e .            # library + script dependencies
pip install -e ".[dev]"     # also installs pytest and ruff
```

## Configuration

Secrets and machine-specific paths come from environment variables. The easiest way to set them is a `.env` file at the repository root. Git ignores this file.

```bash
cp .env.example .env
# then edit .env
```

| Variable              | Description                                                   |
| --------------------- | ------------------------------------------------------------- |
| `PURPLEAIR_API_KEY`   | PurpleAir API read key (required)                             |
| `PURPLERAIN_DATA_DIR` | Directory containing `history.feather`, used by the script    |

Never commit `.env` or put API keys directly in source files.

## Usage

### Command line

`scripts/download_all.py` reads the sensor list from `$PURPLERAIN_DATA_DIR/history.feather` and downloads raw data into the same directory:

```bash
python scripts/download_all.py --start 2025-10-01 --end 2026-03-31
python scripts/download_all.py --help
```

You can re-run the same command to resume an interrupted download or retry failed chunks.

### Library

```python
from dotenv import load_dotenv
from purplerain import PurpleAirClient, PurpleAirNetworkDownloader

load_dotenv()  # loads PURPLEAIR_API_KEY from .env

with PurpleAirClient(timezone="Asia/Kolkata") as client:
    # A single sensor
    df = client.get_sensor_history(
        sensor_id=123456,
        start_timestamp="2025-10-01",
        end_timestamp="2025-10-02",
        read_key="...",  # only needed for private sensors
    )

    # Many sensors, resumable
    downloader = PurpleAirNetworkDownloader(
        client, output_dir="data/raw", chunk_days=30
    )
    downloader.download_network_data(
        sensors,  # DataFrame: sensor_id, read_key, start_date, end_date
        privacy_date="2022-03-10",
    )
```

Timestamps can be Unix seconds, strings, `datetime`s, or `pd.Timestamp`s. Naive values are treated as UTC.

### Output layout

```
output_dir/
├── download_progress.feather
├── download.log                      # written by scripts/download_all.py
└── YYYY-MM/
    └── sensor_<id>_<start YYYYMMDD>_<end YYYYMMDD>.feather
```

Each file holds one sensor's data for one chunk and has a UTC `time_stamp` column plus the requested fields. Chunks never cross a calendar-month boundary (in UTC), so each `YYYY-MM/` folder holds only that month's data. The end date in the filename is exclusive.

PurpleAir allows at most 30 days of raw data per request, so a 31-day month is saved as two files: days 1–30 and day 31.

The downloader never overwrites an existing data file. If a chunk's file is already on disk, the chunk counts as downloaded. Don't point two downloads at the same `output_dir` at the same time.

## Development

```bash
pytest              # run the test suite (no network access needed)
ruff check .        # lint
ruff format .       # format
```

## License

MIT. See [LICENSE](LICENSE).
