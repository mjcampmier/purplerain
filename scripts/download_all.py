"""Download raw PurpleAir data for every sensor listed in ``history.feather``.

Configuration is read from environment variables, which may be set in a ``.env``
file at the repository root (see ``.env.example``):

    PURPLEAIR_API_KEY    PurpleAir API read key (required)
    PURPLERAIN_DATA_DIR  Directory containing history.feather (or pass --data-dir)

Example:

    python scripts/download_all.py --start 2025-10-01 --end 2026-03-31
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from tqdm.contrib.logging import logging_redirect_tqdm

from purplerain import PurpleAirClient, PurpleAirNetworkDownloader

logger = logging.getLogger("download_all")

HISTORY_COLUMNS = {
    "purpleair_sensor_index": "sensor_id",
    "private_key": "read_key",
    "effective_date": "start_date",
    "discontinue_date": "end_date",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    data_dir = os.environ.get("PURPLERAIN_DATA_DIR")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(data_dir) if data_dir else None,
        help="directory containing history.feather (default: $PURPLERAIN_DATA_DIR)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="where downloaded data is written (default: --data-dir)",
    )
    parser.add_argument(
        "--installed-after",
        type=pd.Timestamp,
        default="2024-03-01",
        help="only include sensors with an effective_date on or after this date",
    )
    parser.add_argument(
        "--start",
        type=pd.Timestamp,
        default="2025-10-01",
        help="start of the download window, applied to every sensor",
    )
    parser.add_argument(
        "--end",
        type=pd.Timestamp,
        default="2026-03-31",
        help="end of the download window (earlier if a sensor was discontinued)",
    )
    parser.add_argument(
        "--privacy-date",
        type=pd.Timestamp,
        default="2022-03-10",
        help="windows ending before this date are requested without a read key",
    )
    parser.add_argument("--chunk-days", type=int, default=30)
    args = parser.parse_args(argv)

    if args.data_dir is None:
        parser.error("set PURPLERAIN_DATA_DIR in .env or pass --data-dir")
    args.output_dir = args.output_dir or args.data_dir
    return args


def build_download_table(
    history: pd.DataFrame,
    installed_after: pd.Timestamp,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    """Select sensors and per-sensor download windows from the history table.

    Includes sensors installed on or after ``installed_after`` whose deployment
    overlaps ``[start, end)``. Each is downloaded from ``start`` until the earlier
    of its discontinue date and ``end``. Sensors with several deployment rows are
    merged into one row covering their full window.
    """
    deployments = history.loc[
        history["effective_date"] >= installed_after, list(HISTORY_COLUMNS)
    ].rename(columns=HISTORY_COLUMNS)
    active = (deployments["start_date"] < end) & (
        deployments["end_date"].isna() | (deployments["end_date"] > start)
    )
    sensors = deployments[active].copy()
    sensors["start_date"] = start
    sensors["end_date"] = sensors["end_date"].fillna(end).clip(upper=end)
    return sensors.groupby("sensor_id", as_index=False).agg(
        read_key=("read_key", "first"),
        start_date=("start_date", "min"),
        end_date=("end_date", "max"),
    )


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(args.output_dir / "download.log"),
            logging.StreamHandler(),
        ],
    )

    history = pd.read_feather(args.data_dir / "history.feather")
    sensors = build_download_table(history, args.installed_after, args.start, args.end)

    with PurpleAirClient() as client, logging_redirect_tqdm():
        downloader = PurpleAirNetworkDownloader(
            client=client,
            output_dir=args.output_dir,
            chunk_days=args.chunk_days,
        )
        failed = downloader.download_network_data(
            sensors=sensors, privacy_date=args.privacy_date
        )

    if failed:
        logger.warning("%d chunks failed; re-run to retry them", failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
