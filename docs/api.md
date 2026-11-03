# API reference

Everything below can be imported from the top-level package:

```python
from purplerain import PurpleAirClient, PurpleAirNetworkDownloader, DEFAULT_FIELDS
```

## Client

```{eval-rst}
.. autoclass:: purplerain.client.PurpleAirClient
   :members: get_sensor_history, get_network_data, close
```

## Network downloader

```{eval-rst}
.. autoclass:: purplerain.downloader.PurpleAirNetworkDownloader
   :members: download_network_data, chunk_path
```

## Constants and helpers

```{eval-rst}
.. autodata:: purplerain.client.DEFAULT_FIELDS
   :no-value:

.. autodata:: purplerain.client.API_KEY_ENV_VAR

.. autodata:: purplerain.client.TimeLike
   :no-value:

.. autofunction:: purplerain.client.to_utc

.. autofunction:: purplerain.client.to_unix

.. autofunction:: purplerain.client.describe_error
```

The default fields are `pm2.5_cf_1_a`, `pm2.5_cf_1_b`, `humidity`, `temperature`, `scattering_coefficient_a` and `scattering_coefficient_b`. `TimeLike` means a Unix timestamp in seconds, a string, a `datetime` or a `pandas.Timestamp`.
