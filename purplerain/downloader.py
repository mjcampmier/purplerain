"""Resumable, chunked bulk downloads for networks of PurpleAir sensors."""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from datetime import timedelta
from pathlib import Path

import pandas as pd
import requests
from tqdm import tqdm

from purplerain.client import PurpleAirClient, TimeLike, describe_error

logger = logging.getLogger(__name__)

ChunkKey = tuple[int, pd.Timestamp, pd.Timestamp]


def _write_feather_atomic(
    df: pd.DataFrame, path: Path, *, overwrite: bool = False
) -> None:
    """Write ``df`` to ``path`` so an interrupted run never leaves a partial file.

    Raises:
        FileExistsError: ``path`` already exists and ``overwrite`` is False.
    """
    if not overwrite and path.exists():
        raise FileExistsError(f"Refusing to overwrite existing file: {path}")
    tmp = path.with_name(path.name + ".tmp")
    df.to_feather(tmp)
    tmp.replace(path)


class PurpleAirNetworkDownloader:
    """Download long histories for many sensors in month-aligned time chunks.

    Progress is recorded after every chunk, so an interrupted run can be resumed
    by calling :meth:`download_network_data` again with the same arguments.

    Output layout::

        output_dir/
            download_progress.feather
            YYYY-MM/sensor_<id>_<start YYYYMMDD>_<end YYYYMMDD>.feather

    Chunks never cross a calendar-month boundary (in UTC), so each ``YYYY-MM``
    folder holds only that month's data. Each chunk has its own file, named by
    its start and exclusive end date. Existing data files are never overwritten:
    a file already on disk counts as a completed download of that chunk.

    Do not run two downloaders against the same ``output_dir`` at once.

    Args:
        client: Configured :class:`PurpleAirClient`.
        output_dir: Directory for downloaded data and the progress file.
        chunk_days: Maximum length of each request in days. PurpleAir allows at
            most 30 days of raw (``average=0``) data per request, so a 31-day
            month is downloaded as two chunks (days 1-30, then day 31).
    """

    PROGRESS_FILENAME = "download_progress.feather"
    PROGRESS_COLUMNS = ["sensor_id", "chunk_start", "chunk_end", "status", "timestamp"]

    def __init__(
        self,
        client: PurpleAirClient,
        output_dir: str | Path,
        chunk_days: int = 30,
    ) -> None:
        if chunk_days < 1:
            raise ValueError("chunk_days must be at least 1")
        self.client = client
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.chunk_days = chunk_days
        self.progress_file = self.output_dir / self.PROGRESS_FILENAME
        self._load_progress()

    # Progress tracking

    def _load_progress(self) -> None:
        if self.progress_file.exists():
            self.progress_df = pd.read_feather(self.progress_file)
        else:
            self.progress_df = pd.DataFrame(columns=self.PROGRESS_COLUMNS)

        done = self.progress_df[self.progress_df["status"] == "completed"]
        self._completed: set[ChunkKey] = set(
            zip(
                done["sensor_id"].astype(int),
                done["chunk_start"],
                done["chunk_end"],
                strict=True,
            )
        )

    def _is_chunk_downloaded(
        self, sensor_id: int, chunk_start: pd.Timestamp, chunk_end: pd.Timestamp
    ) -> bool:
        return (int(sensor_id), chunk_start, chunk_end) in self._completed

    def _mark_chunk_complete(
        self, sensor_id: int, chunk_start: pd.Timestamp, chunk_end: pd.Timestamp
    ) -> None:
        row = pd.DataFrame(
            [
                {
                    "sensor_id": int(sensor_id),
                    "chunk_start": chunk_start,
                    "chunk_end": chunk_end,
                    "status": "completed",
                    "timestamp": pd.Timestamp.now(tz="UTC"),
                }
            ]
        )
        self.progress_df = (
            row
            if self.progress_df.empty
            else pd.concat([self.progress_df, row], ignore_index=True)
        )
        self._completed.add((int(sensor_id), chunk_start, chunk_end))
        _write_feather_atomic(self.progress_df, self.progress_file, overwrite=True)

    # Chunking

    def _get_time_chunks(
        self, start_date: TimeLike, end_date: TimeLike
    ) -> Iterator[tuple[pd.Timestamp, pd.Timestamp]]:
        """Split ``[start_date, end_date)`` into chunks of at most ``chunk_days``
        that never cross a calendar-month boundary."""
        current, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
        step = timedelta(days=self.chunk_days)
        while current < end:
            next_month = current.normalize().replace(day=1) + pd.DateOffset(months=1)
            chunk_end = min(current + step, next_month, end)
            yield current, chunk_end
            current = chunk_end

    def chunk_path(
        self, sensor_id: int, chunk_start: pd.Timestamp, chunk_end: pd.Timestamp
    ) -> Path:
        """Path of the file holding one sensor's data for one chunk."""
        name = (
            f"sensor_{int(sensor_id)}_{chunk_start:%Y%m%d}_{chunk_end:%Y%m%d}.feather"
        )
        return self.output_dir / f"{chunk_start:%Y-%m}" / name

    # Downloading

    @staticmethod
    def _prepare_sensors(
        sensors: pd.DataFrame,
        global_start_date: TimeLike | None,
        global_end_date: TimeLike | None,
    ) -> pd.DataFrame:
        if "sensor_id" not in sensors.columns:
            raise ValueError("sensors DataFrame must contain a 'sensor_id' column")

        sensors = sensors.copy()
        if "read_key" not in sensors.columns:
            sensors["read_key"] = None
        if global_start_date is not None:
            sensors["start_date"] = pd.Timestamp(global_start_date)
        if global_end_date is not None:
            sensors["end_date"] = pd.Timestamp(global_end_date)

        missing = {"start_date", "end_date"} - set(sensors.columns)
        if missing:
            raise ValueError(
                "Provide global_start_date/global_end_date, or include "
                f"{sorted(missing)} column(s) in the sensors DataFrame"
            )
        return sensors

    def download_network_data(
        self,
        sensors: pd.DataFrame,
        fields: Sequence[str] | None = None,
        global_start_date: TimeLike | None = None,
        global_end_date: TimeLike | None = None,
        privacy_date: TimeLike | None = None,
        average: int = 0,
    ) -> int:
        """Download every not-yet-completed chunk for every sensor.

        Args:
            sensors: DataFrame with a ``sensor_id`` column, an optional
                ``read_key`` column and, unless the global dates are given,
                per-sensor ``start_date`` and ``end_date`` columns.
            fields: Fields to request; defaults to the client's default fields.
            global_start_date: Overrides every sensor's ``start_date``.
            global_end_date: Overrides every sensor's ``end_date``.
            privacy_date: Windows ending before this date are requested without
                a read key (see :meth:`PurpleAirClient.get_sensor_history`).
            average: Averaging period in minutes (``0`` for raw data).

        Returns:
            Number of chunks that failed to download. Re-run to retry them.
        """
        sensors = self._prepare_sensors(sensors, global_start_date, global_end_date)
        plan = [
            (sensor, chunk_start, chunk_end)
            for sensor in sensors.itertuples(index=False)
            for chunk_start, chunk_end in self._get_time_chunks(
                sensor.start_date, sensor.end_date
            )
        ]
        logger.info(
            "Planning %d chunks for %d sensors into %s",
            len(plan),
            len(sensors),
            self.output_dir,
        )

        downloaded = skipped = empty = failed = 0
        for sensor, chunk_start, chunk_end in tqdm(
            plan, desc="Downloading", unit="chunk"
        ):
            if self._is_chunk_downloaded(sensor.sensor_id, chunk_start, chunk_end):
                skipped += 1
                continue

            # Filenames encode the sensor and exact chunk range, and files are
            # written atomically, so an existing file is a finished download of
            # this chunk (e.g. a run was interrupted before saving progress).
            path = self.chunk_path(sensor.sensor_id, chunk_start, chunk_end)
            if path.exists():
                self._mark_chunk_complete(sensor.sensor_id, chunk_start, chunk_end)
                skipped += 1
                continue

            try:
                data = self.client.get_sensor_history(
                    sensor.sensor_id,
                    chunk_start,
                    chunk_end,
                    read_key=sensor.read_key,
                    average=average,
                    fields=fields,
                    privacy_date=privacy_date,
                )
            except requests.RequestException as exc:
                failed += 1
                logger.error(
                    "Sensor %s, %s to %s: %s",
                    sensor.sensor_id,
                    chunk_start,
                    chunk_end,
                    describe_error(exc),
                )
                continue

            # Empty chunks are not marked complete, so they are retried next run.
            if data.empty:
                empty += 1
                logger.debug(
                    "Sensor %s, %s to %s: no data",
                    sensor.sensor_id,
                    chunk_start,
                    chunk_end,
                )
                continue

            path.parent.mkdir(parents=True, exist_ok=True)
            _write_feather_atomic(data.reset_index(), path)
            self._mark_chunk_complete(sensor.sensor_id, chunk_start, chunk_end)
            downloaded += 1

        logger.info(
            "Done: %d downloaded, %d already complete, %d empty, %d failed",
            downloaded,
            skipped,
            empty,
            failed,
        )
        return failed
