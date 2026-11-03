from datetime import datetime, timezone
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest
import requests

from purplerain import API_KEY_ENV_VAR, PurpleAirClient
from purplerain.client import describe_error, to_unix

PAYLOAD = {
    "fields": ["time_stamp", "humidity", "temperature"],
    "data": [[1_700_000_060, 41, 80], [1_700_000_000, 40, 79]],
}


@pytest.fixture
def client():
    client = PurpleAirClient("test-key", request_interval=0)
    response = Mock()
    response.json.return_value = PAYLOAD
    client.session.get = Mock(return_value=response)
    return client


def sent_params(client):
    return client.session.get.call_args.kwargs["params"]


def test_api_key_falls_back_to_environment(monkeypatch):
    monkeypatch.setenv(API_KEY_ENV_VAR, "env-key")
    assert PurpleAirClient().session.headers["X-API-Key"] == "env-key"


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv(API_KEY_ENV_VAR, raising=False)
    with pytest.raises(ValueError, match=API_KEY_ENV_VAR):
        PurpleAirClient()


@pytest.mark.parametrize(
    "value",
    [
        1_700_000_000,
        np.int64(1_700_000_000),
        datetime(2023, 11, 14, 22, 13, 20),
        datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc),
        pd.Timestamp("2023-11-15 03:43:20", tz="Asia/Kolkata"),
        "2023-11-14 22:13:20",
    ],
)
def test_to_unix_treats_naive_values_as_utc(value):
    assert to_unix(value) == 1_700_000_000


def test_get_sensor_history_parses_and_sorts(client):
    df = client.get_sensor_history(123, 1_700_000_000, 1_700_000_100)

    assert list(df.columns) == ["humidity", "temperature"]
    assert df.index.name == "time_stamp"
    assert str(df.index.tz) == "UTC"
    assert df.index.is_monotonic_increasing
    assert sent_params(client)["start_timestamp"] == 1_700_000_000
    assert "read_key" not in sent_params(client)


def test_timezone_conversion():
    client = PurpleAirClient("k", timezone="Asia/Kolkata", request_interval=0)
    client.session.get = Mock(return_value=Mock(json=Mock(return_value=PAYLOAD)))
    df = client.get_sensor_history(1, 0, 1)
    assert str(df.index.tz) == "Asia/Kolkata"


@pytest.mark.parametrize(
    ("end", "expected"),
    [("2022-03-09", None), ("2022-03-10", "secret"), ("2023-01-01", "secret")],
)
def test_read_key_respects_privacy_date(client, end, expected):
    client.get_sensor_history(
        1, "2022-01-01", end, read_key="secret", privacy_date=datetime(2022, 3, 10)
    )
    assert sent_params(client).get("read_key") == expected


@pytest.mark.parametrize("read_key", [None, float("nan"), "", "  "])
def test_blank_read_keys_are_not_sent(client, read_key):
    client.get_sensor_history(1, 0, 1, read_key=read_key)
    assert "read_key" not in sent_params(client)


def test_http_errors_propagate(client):
    client.session.get.return_value.raise_for_status.side_effect = requests.HTTPError(
        "403"
    )
    with pytest.raises(requests.HTTPError):
        client.get_sensor_history(1, 0, 1)


def test_get_network_data_skips_failed_sensors(client):
    good = client.session.get.return_value
    bad = Mock(raise_for_status=Mock(side_effect=requests.HTTPError("500")))
    client.session.get.side_effect = lambda url, **_: bad if "/2/" in url else good

    sensors = pd.DataFrame({"sensor_id": [1, 2, 3]})
    result = client.get_network_data(sensors, 0, 1, max_workers=2)

    assert sorted(result) == [1, 3]


def test_describe_error_redacts_read_key_and_adds_description():
    response = Mock(status_code=404)
    response.json.return_value = {
        "description": "An invalid sensor data read_key 'SECRET123' was provided."
    }
    exc = requests.HTTPError(
        "404 Client Error: Not Found for url: "
        "https://api.purpleair.com/v1/sensors/1/history?average=0&read_key=SECRET123",
        response=response,
    )
    message = describe_error(exc)
    assert "SECRET123" not in message
    assert "read_key=***" in message
    assert message.endswith("(An invalid sensor data read_key '***' was provided.)")
