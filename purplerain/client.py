"""HTTP client for the PurpleAir v1 REST API."""

from __future__ import annotations

import logging
import numbers
import os
import re
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

API_KEY_ENV_VAR = "PURPLEAIR_API_KEY"

DEFAULT_FIELDS: tuple[str, ...] = (
    "pm2.5_cf_1_a",
    "pm2.5_cf_1_b",
    "humidity",
    "temperature",
    "scattering_coefficient_a",
    "scattering_coefficient_b",
)

#: Anything that can be interpreted as a point in time. Numbers are Unix epoch
#: seconds; naive datetimes and strings are interpreted as UTC.
TimeLike = int | float | str | datetime | pd.Timestamp


def to_utc(value: TimeLike) -> pd.Timestamp:
    """Coerce a time-like value to a timezone-aware UTC ``pd.Timestamp``."""
    if isinstance(value, numbers.Real):
        return pd.Timestamp(value, unit="s", tz="UTC")
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def to_unix(value: TimeLike) -> int:
    """Convert a time-like value to integer Unix epoch seconds."""
    return int(to_utc(value).timestamp())


def _clean_read_key(read_key: Any) -> str | None:
    """Treat ``None``, ``NaN`` and empty strings as "no read key"."""
    if read_key is None or (not isinstance(read_key, str) and pd.isna(read_key)):
        return None
    read_key = str(read_key).strip()
    return read_key or None


_READ_KEY_IN_URL = re.compile(r"read_key=([^&\s'\"]+)")


def describe_error(exc: requests.RequestException) -> str:
    """Summarize a request error for logging, with sensor read keys redacted.

    ``requests`` puts the full URL (including the ``read_key`` query parameter)
    into its error messages, and PurpleAir's error descriptions can quote the
    key back. This appends PurpleAir's description when there is one, then masks
    every occurrence of the key.
    """
    message = str(exc)
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            description = response.json().get("description")
        except (ValueError, AttributeError):
            description = None
        if description:
            message = f"{message} ({description})"
    for key in set(_READ_KEY_IN_URL.findall(message)):
        message = message.replace(key, "***")
    return message


class PurpleAirClient:
    """Minimal client for the PurpleAir API.

    Args:
        api_key: PurpleAir API read key. If omitted, the ``PURPLEAIR_API_KEY``
            environment variable is used.
        timezone: Optional IANA timezone name (e.g. ``"Asia/Kolkata"``). When
            set, returned DataFrames are indexed in this timezone; otherwise UTC.
        request_interval: Seconds to pause after every request, to stay under
            PurpleAir's rate limits.
        timeout: Per-request timeout in seconds.
        max_retries: Retries for rate-limited (429) and 5xx responses, with
            exponential backoff.
    """

    BASE_URL = "https://api.purpleair.com/v1"

    def __init__(
        self,
        api_key: str | None = None,
        timezone: str | None = None,
        *,
        request_interval: float = 0.5,
        timeout: float = 60.0,
        max_retries: int = 5,
    ) -> None:
        api_key = api_key or os.environ.get(API_KEY_ENV_VAR)
        if not api_key:
            raise ValueError(
                f"No PurpleAir API key found. Pass api_key=... or set the "
                f"{API_KEY_ENV_VAR} environment variable (see .env.example)."
            )

        self.timezone = timezone
        self.request_interval = request_interval
        self.timeout = timeout

        retry = Retry(
            total=max_retries,
            backoff_factor=1.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            raise_on_status=False,
        )
        self.session = requests.Session()
        self.session.headers["X-API-Key"] = api_key
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> PurpleAirClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def get_sensor_history(
        self,
        sensor_id: int,
        start_timestamp: TimeLike,
        end_timestamp: TimeLike,
        read_key: str | None = None,
        average: int = 0,
        fields: Sequence[str] | None = None,
        *,
        privacy_date: TimeLike | None = None,
    ) -> pd.DataFrame:
        """Fetch historical data for a single sensor.

        Args:
            sensor_id: PurpleAir sensor index.
            start_timestamp: Start of the requested window.
            end_timestamp: End of the requested window.
            read_key: Read key for private sensors.
            average: Averaging period in minutes (``0`` for raw/real-time data).
            fields: Fields to request; defaults to :data:`DEFAULT_FIELDS`.
            privacy_date: If given, ``read_key`` is only sent when the window
                ends on or after this date.

        Returns:
            DataFrame indexed by a timezone-aware ``time_stamp`` index, sorted
            ascending, with one column per requested field.
        """
        fields = DEFAULT_FIELDS if fields is None else fields
        read_key = _clean_read_key(read_key)
        if privacy_date is not None and to_utc(end_timestamp) < to_utc(privacy_date):
            read_key = None

        params: dict[str, Any] = {
            "start_timestamp": to_unix(start_timestamp),
            "end_timestamp": to_unix(end_timestamp),
            "average": average,
            "fields": ", ".join(fields),
        }
        if read_key is not None:
            params["read_key"] = read_key

        response = self.session.get(
            f"{self.BASE_URL}/sensors/{sensor_id}/history",
            params=params,
            timeout=self.timeout,
        )
        if self.request_interval:
            time.sleep(self.request_interval)
        response.raise_for_status()

        return self._to_frame(response.json())

    def _to_frame(self, payload: dict[str, Any]) -> pd.DataFrame:
        df = pd.DataFrame(payload["data"], columns=payload["fields"])
        df.index = pd.to_datetime(df.pop("time_stamp"), unit="s", utc=True)
        if self.timezone:
            df.index = df.index.tz_convert(self.timezone)
        return df.sort_index()

    def get_network_data(
        self,
        sensor_df: pd.DataFrame,
        start_timestamp: TimeLike,
        end_timestamp: TimeLike,
        privacy_date: TimeLike | None = None,
        average: int = 0,
        fields: Sequence[str] | None = None,
        max_workers: int = 5,
    ) -> dict[int, pd.DataFrame]:
        """Fetch the same time window for many sensors in parallel.

        Args:
            sensor_df: DataFrame with a ``sensor_id`` column and, optionally, a
                ``read_key`` column.
            start_timestamp: Start of the requested window.
            end_timestamp: End of the requested window.
            privacy_date: See :meth:`get_sensor_history`.
            average: Averaging period in minutes.
            fields: Fields to request; defaults to :data:`DEFAULT_FIELDS`.
            max_workers: Maximum number of concurrent requests.

        Returns:
            Mapping of sensor ID to DataFrame. Sensors that failed or returned
            no data are omitted (failures are logged).
        """
        if "sensor_id" not in sensor_df.columns:
            raise ValueError("sensor_df must contain a 'sensor_id' column")
        read_keys = sensor_df.get("read_key", pd.Series(None, index=sensor_df.index))

        results: dict[int, pd.DataFrame] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self.get_sensor_history,
                    sensor_id,
                    start_timestamp,
                    end_timestamp,
                    read_key=read_key,
                    average=average,
                    fields=fields,
                    privacy_date=privacy_date,
                ): sensor_id
                for sensor_id, read_key in zip(
                    sensor_df["sensor_id"], read_keys, strict=True
                )
            }
            for future in as_completed(futures):
                sensor_id = futures[future]
                try:
                    df = future.result()
                except requests.RequestException as exc:
                    logger.error(
                        "Failed to fetch sensor %s: %s", sensor_id, describe_error(exc)
                    )
                    continue
                if not df.empty:
                    results[sensor_id] = df

        return results
