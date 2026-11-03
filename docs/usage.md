# Usage

## Command line

`scripts/download_all.py` reads a sensor history table, picks every sensor that was deployed during the requested window, and downloads raw (2-minute) data for each:

```bash
# Uses $PURPLERAIN_DATA_DIR/history.feather and writes into the same folder
python scripts/download_all.py --start 2025-03-01 --end 2025-04-01

# Explicit input and output, e.g. on a CI runner
python scripts/download_all.py --history sensors.csv.gz --output-dir data \
    --start 2025-03-01 --end 2025-04-01
```

`--end` is exclusive. Every option is listed in the {doc}`cli`.

### Sensor history table

The script needs a table describing each deployment. It can be a feather file or a CSV (optionally gzipped), and other columns are ignored.

| Column | Meaning |
| --- | --- |
| `purpleair_sensor_index` | PurpleAir sensor ID |
| `private_key` | Sensor read key (blank for public sensors) |
| `effective_date` | Date the deployment started |
| `discontinue_date` | Date the deployment ended (blank if still active) |

These options decide which sensors are downloaded:

- **`--installed-after`:** only sensors whose deployment started on or after this date. The default, `2024-03-01`, selects SAMOSA Phase 2; use an earlier date to include Phase 1.
- **The window:** only sensors whose deployment overlaps `[--start, --end)`.

Each selected sensor is downloaded from `--start` until the earlier of its discontinue date and `--end`. A sensor that appears in several deployment rows is downloaded once.

## Library

```python
from dotenv import load_dotenv
import pandas as pd

from purplerain import PurpleAirClient, PurpleAirNetworkDownloader

load_dotenv()  # loads PURPLEAIR_API_KEY from .env

with PurpleAirClient(timezone="Asia/Kolkata") as client:
    # One sensor, one window (at most 30 days of raw data per request)
    df = client.get_sensor_history(
        sensor_id=123456,
        start_timestamp="2025-10-01",
        end_timestamp="2025-10-02",
        read_key="...",  # only for private sensors
    )

    # Many sensors over a long period: resumable, written to disk
    sensors = pd.DataFrame(
        {
            "sensor_id": [123456, 234567],
            "read_key": ["...", None],
            "start_date": pd.Timestamp("2025-01-01"),
            "end_date": pd.Timestamp("2025-07-01"),
        }
    )
    downloader = PurpleAirNetworkDownloader(client, output_dir="data/raw")
    failed = downloader.download_network_data(sensors, privacy_date="2022-03-10")
```

Timestamps can be Unix seconds, strings, `datetime` objects or `pandas.Timestamp`s. Values without a timezone are treated as **UTC**. Returned DataFrames are indexed by a timezone-aware `time_stamp`, in UTC unless you pass `timezone=`.

`privacy_date` is for sensors that became private partway through their history. Requests for windows that end before this date are sent without a read key.

See the {doc}`api` for the full API.

## Output layout

```
output_dir/
├── download_progress.feather
├── download.log                      # written by scripts/download_all.py
└── YYYY-MM/
    └── sensor_<id>_<start YYYYMMDD>_<end YYYYMMDD>.feather
```

- **One file per request.** Each file holds one sensor's data for one request (a "chunk"). It has a UTC `time_stamp` column plus one column per requested field. The end date in the file name is exclusive.
- **Folders match their month.** Requests never cross a calendar-month boundary (in UTC), so every `YYYY-MM/` folder holds only that month's data.
- **31-day months need two files.** PurpleAir allows at most 30 days of raw data per request, so these months are saved as days 1–30 and then day 31.
- **Nothing is overwritten.** If a file is already on disk, that chunk counts as downloaded and the file is left alone. Don't point two downloads at the same `output_dir` at the same time.
- **Empty periods are retried.** A period with no data isn't recorded as done, so the next run checks it again.

To load a month back into one DataFrame:

```python
from pathlib import Path
import pandas as pd

month = pd.concat(
    pd.read_feather(f).assign(sensor_id=int(f.name.split("_")[1]))
    for f in sorted(Path("data/raw/2025-03").glob("sensor_*.feather"))
)
```
