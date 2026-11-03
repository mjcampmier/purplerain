# Getting started

## Requirements

- Python 3.10 or newer
- A PurpleAir API **read** key, from the [PurpleAir developer portal](https://develop.purpleair.com/)
- For private sensors, each sensor's read key

## Installation

Clone the repository and install it in editable mode:

```bash
git clone https://github.com/mjcampmier/purplerain.git
cd purplerain
pip install -e .            # library and download script
pip install -e ".[dev]"     # also installs pytest and ruff
pip install -e ".[docs]"    # also installs Sphinx, to build this site
```

## Configuration

Secrets and machine-specific paths come from environment variables. Locally, the easiest way to set them is a `.env` file at the repository root. Git ignores `.env`, so it is never committed.

```bash
cp .env.example .env
```

Then fill in the values:

```bash
PURPLEAIR_API_KEY=your-read-key
PURPLERAIN_DATA_DIR="/path/to/folder/containing/history.feather"
```

| Variable | Used by | Description |
| --- | --- | --- |
| `PURPLEAIR_API_KEY` | Library and script | PurpleAir API read key (required) |
| `PURPLERAIN_DATA_DIR` | Script | Folder containing `history.feather`. Downloads are written there too, unless you pass `--output-dir`. |

Never put API keys directly in source files or notebooks. If a key has been committed or shared, generate a new one in the PurpleAir developer portal and delete the old one.

## Your first download

Download one month for every sensor in your history table:

```bash
python scripts/download_all.py --start 2025-10-01 --end 2025-11-01
```

You'll see a progress bar and then a summary like this:

```
Done: 48 downloaded, 0 already complete, 278 empty, 2 failed
```

- **downloaded:** written to disk.
- **already complete:** found on disk from an earlier run and skipped.
- **empty:** the sensor uploaded no data for that period.
- **failed:** an error such as an invalid read key. Each failure is logged.

If anything failed, run the same command again; only the missing chunks are requested. The script exits with status 1 while any chunk is still failing.

Next steps:

- {doc}`usage`: the sensor table format, using the library from Python, and how output is organized.
- {doc}`github-actions`: run downloads automatically on GitHub.
