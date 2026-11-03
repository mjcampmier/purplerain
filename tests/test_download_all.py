import importlib.util
from pathlib import Path

import pandas as pd
import pytest

_spec = importlib.util.spec_from_file_location(
    "download_all", Path(__file__).parents[1] / "scripts" / "download_all.py"
)
download_all = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(download_all)


def test_build_download_table_selects_and_clips_windows():
    ts = pd.Timestamp
    history = pd.DataFrame(
        {
            "purpleair_sensor_index": [1, 2, 3, 4, 5, 5],
            "private_key": ["a", "b", "c", "d", "e", "e"],
            "effective_date": [
                ts("2024-05-01"),  # active whole window
                ts("2024-05-01"),  # discontinued mid-window -> clipped
                ts("2023-01-01"),  # installed before cutoff -> excluded
                ts("2025-02-01"),  # installed after window -> excluded
                ts("2024-05-01"),  # two deployment rows -> merged
                ts("2024-12-10"),
            ],
            "discontinue_date": [
                pd.NaT,
                ts("2024-12-15"),
                pd.NaT,
                pd.NaT,
                ts("2024-12-10"),
                ts("2025-06-01"),  # beyond window -> clipped to end
            ],
        }
    )
    out = download_all.build_download_table(
        history, ts("2024-03-01"), ts("2024-12-01"), ts("2025-01-01")
    )

    assert out["sensor_id"].tolist() == [1, 2, 5]
    assert (out["start_date"] == ts("2024-12-01")).all()
    assert out["end_date"].tolist() == [
        ts("2025-01-01"),
        ts("2024-12-15"),
        ts("2025-01-01"),
    ]
    assert out["read_key"].tolist() == ["a", "b", "e"]


def test_read_history_from_gzipped_csv(tmp_path):
    path = tmp_path / "sensors.csv.gz"
    pd.DataFrame(
        {
            "purpleair_sensor_index": [1, 2],
            "private_key": ["KEY1", None],
            "effective_date": ["2024-05-01", "2024-06-01"],
            "discontinue_date": [None, "2024-12-15"],
            "site_name": ["ignored", "ignored"],
        }
    ).to_csv(path, index=False)

    history = download_all.read_history(path)

    assert list(history.columns) == list(download_all.HISTORY_COLUMNS)
    assert pd.api.types.is_datetime64_any_dtype(history["effective_date"])
    assert pd.api.types.is_datetime64_any_dtype(history["discontinue_date"])
    out = download_all.build_download_table(
        history,
        pd.Timestamp("2024-03-01"),
        pd.Timestamp("2024-12-01"),
        pd.Timestamp("2025-01-01"),
    )
    assert out["end_date"].tolist() == [
        pd.Timestamp("2025-01-01"),
        pd.Timestamp("2024-12-15"),
    ]


def test_history_and_output_dir_replace_data_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("PURPLERAIN_DATA_DIR", raising=False)
    args = download_all.parse_args(
        ["--history", "s.csv.gz", "--output-dir", str(tmp_path)]
    )
    assert args.history == Path("s.csv.gz")
    assert args.output_dir == tmp_path

    with pytest.raises(SystemExit):
        download_all.parse_args(["--history", "s.csv.gz"])
