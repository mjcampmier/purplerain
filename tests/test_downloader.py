import pandas as pd
import pytest
import requests

from purplerain import PurpleAirNetworkDownloader
from purplerain.downloader import _write_feather_atomic


class FakeClient:
    """Stands in for PurpleAirClient; returns one row per requested chunk."""

    def __init__(self, fail_sensors=()):
        self.calls = []
        self.fail_sensors = set(fail_sensors)

    def get_sensor_history(self, sensor_id, start, end, **kwargs):
        self.calls.append((sensor_id, start, end, kwargs))
        if sensor_id in self.fail_sensors:
            raise requests.HTTPError("boom")
        index = pd.DatetimeIndex([pd.Timestamp(start, tz="UTC")], name="time_stamp")
        return pd.DataFrame({"humidity": [sensor_id]}, index=index)


@pytest.fixture
def sensors():
    return pd.DataFrame(
        {
            "sensor_id": [101, 202],
            "read_key": ["key-a", None],
            "start_date": pd.Timestamp("2025-10-01"),
            "end_date": [pd.Timestamp("2025-11-15"), pd.Timestamp("2025-10-10")],
        }
    )


def chunks(start, end, chunk_days=30):
    downloader = PurpleAirNetworkDownloader.__new__(PurpleAirNetworkDownloader)
    downloader.chunk_days = chunk_days
    return [
        (f"{a:%Y-%m-%d}", f"{b:%Y-%m-%d}")
        for a, b in downloader._get_time_chunks(start, end)
    ]


def test_chunks_never_cross_month_boundaries():
    assert chunks("2025-10-01", "2025-11-15") == [
        ("2025-10-01", "2025-10-31"),  # 30-day request limit
        ("2025-10-31", "2025-11-01"),
        ("2025-11-01", "2025-11-15"),
    ]
    assert chunks("2025-01-15", "2025-03-02") == [
        ("2025-01-15", "2025-02-01"),
        ("2025-02-01", "2025-03-01"),
        ("2025-03-01", "2025-03-02"),
    ]
    assert chunks("2025-11-01", "2025-12-01") == [("2025-11-01", "2025-12-01")]
    assert chunks("2025-10-01", "2025-11-01", chunk_days=7)[-1] == (
        "2025-10-29",
        "2025-11-01",
    )


def test_each_month_folder_holds_only_that_month(tmp_path, sensors):
    downloader = PurpleAirNetworkDownloader(FakeClient(), tmp_path, chunk_days=30)
    downloader.download_network_data(sensors.iloc[[0]])

    files = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.glob("*/*.feather"))
    assert files == [
        "2025-10/sensor_101_20251001_20251031.feather",
        "2025-10/sensor_101_20251031_20251101.feather",
        "2025-11/sensor_101_20251101_20251115.feather",
    ]
    df = pd.read_feather(tmp_path / files[0])
    assert list(df.columns) == ["time_stamp", "humidity"]


def test_existing_files_are_never_overwritten(tmp_path, sensors):
    downloader = PurpleAirNetworkDownloader(FakeClient(), tmp_path)
    path = downloader.chunk_path(
        202, pd.Timestamp("2025-10-01"), pd.Timestamp("2025-10-10")
    )
    path.parent.mkdir(parents=True)
    sentinel = pd.DataFrame({"time_stamp": [pd.Timestamp(0, tz="UTC")], "x": [1]})
    sentinel.to_feather(path)

    client = FakeClient()
    PurpleAirNetworkDownloader(client, tmp_path).download_network_data(
        sensors.iloc[[1]]
    )

    assert client.calls == []
    pd.testing.assert_frame_equal(pd.read_feather(path), sentinel)
    with pytest.raises(FileExistsError):
        _write_feather_atomic(sentinel, path)


def test_download_passes_read_key_and_privacy_date(tmp_path, sensors):
    client = FakeClient()
    downloader = PurpleAirNetworkDownloader(client, tmp_path)
    downloader.download_network_data(sensors, privacy_date="2022-03-10")

    _, _, _, kwargs = client.calls[0]
    assert kwargs["read_key"] == "key-a"
    assert kwargs["privacy_date"] == "2022-03-10"


def test_resume_skips_completed_chunks(tmp_path, sensors):
    first = FakeClient()
    PurpleAirNetworkDownloader(first, tmp_path).download_network_data(sensors)
    assert len(first.calls) == 4

    second = FakeClient()
    PurpleAirNetworkDownloader(second, tmp_path).download_network_data(sensors)
    assert second.calls == []


def test_failed_chunks_are_retried_on_next_run(tmp_path, sensors):
    failing = FakeClient(fail_sensors={202})
    failed = PurpleAirNetworkDownloader(failing, tmp_path).download_network_data(
        sensors
    )
    assert failed == 1

    retry = FakeClient()
    PurpleAirNetworkDownloader(retry, tmp_path).download_network_data(sensors)
    assert [call[0] for call in retry.calls] == [202]


def test_global_dates_do_not_mutate_input(tmp_path, sensors):
    original = sensors.copy()
    PurpleAirNetworkDownloader(FakeClient(), tmp_path).download_network_data(
        sensors,
        global_start_date="2025-10-01",
        global_end_date="2025-10-02",
    )
    pd.testing.assert_frame_equal(sensors, original)


def test_missing_dates_raise(tmp_path):
    downloader = PurpleAirNetworkDownloader(FakeClient(), tmp_path)
    with pytest.raises(ValueError, match="start_date"):
        downloader.download_network_data(pd.DataFrame({"sensor_id": [1]}))
