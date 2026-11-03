# Changelog

## 0.1.0 (unreleased)

### Fixed

- **Downloads could silently overwrite earlier data.** Earlier versions saved every chunk to `YYYY-MM/sensor_<id>.feather`, using the month in which the chunk *started*. When two chunks for a sensor started in the same month, the second replaced the first, yet both were still marked as complete. This happened most often when a 30-day chunk began on the 1st of a 31-day month, because the next chunk then also started in that month (on the 31st). See {ref}`checking-old-downloads` below.
- **Plain `datetime` values without a timezone** were read as the computer's local time. They are now treated as UTC, the same as `pandas.Timestamp`s already were.
- **`--end` didn't limit the download.** A sensor with a later discontinue date was downloaded past `--end`. Sensors installed after the window were also downloaded.
- **Logs could contain sensors' read keys,** because error messages included the full request URL. Keys are now masked in logs.

### Changed

- **New file layout.** Chunks follow calendar months and each has its own file: `YYYY-MM/sensor_<id>_<start>_<end>.feather`. Existing files are never overwritten.
- **API key from the environment.** It is read from `PURPLEAIR_API_KEY` (or a `.env` file) instead of being written in the code.
- **Retries and timeouts.** Requests time out after 60 seconds by default. Rate-limit (`429`) and server (`5xx`) errors are retried with exponential backoff.
- **Code layout.** The package is split into `purplerain.client` and `purplerain.downloader`. The download script moved to `scripts/download_all.py` and gained command-line options.
- **Unused options removed.** The downloader's `batch_size` and `max_workers` arguments had no effect and are gone.

### Added

- **Sensor tables as CSV.** `--history` accepts a CSV (optionally gzipped) as well as feather.
- **GitHub Actions:** CI (lint and tests), a scheduled data download, and this documentation site.

(checking-old-downloads)=
## Checking downloads made with earlier versions

Old download folders include a `download_progress.feather`. Any sensor and month with more than one completed chunk had its file overwritten. To list them:

```python
import pandas as pd

progress = pd.read_feather("path/to/download_progress.feather")
done = progress[progress.status == "completed"].sort_values("timestamp")
done["folder"] = done.chunk_start.dt.strftime("%Y-%m")
lost = done[done.duplicated(["sensor_id", "folder"], keep="last")]
print(lost[["sensor_id", "folder", "chunk_start", "chunk_end"]])
```

Each row is a chunk whose data was replaced. To recover it, re-download those periods with the current version into a **new** output folder.
