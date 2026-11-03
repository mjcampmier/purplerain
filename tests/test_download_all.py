import importlib.util
from pathlib import Path

import pandas as pd

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
