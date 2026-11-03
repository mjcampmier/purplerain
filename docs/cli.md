# Command-line reference

The download script reads `PURPLEAIR_API_KEY` (and optionally `PURPLERAIN_DATA_DIR`) from the environment or from a `.env` file at the repository root. Run it from the repository root:

```bash
python scripts/download_all.py [options]
```

```{eval-rst}
.. argparse::
   :filename: ../scripts/download_all.py
   :func: build_parser
   :prog: download_all.py
   :nodescription:
```

## Exit status

| Status | Meaning |
| --- | --- |
| `0` | Every chunk was downloaded, or was already complete or empty |
| `1` | At least one chunk failed. Run the same command again to retry only those chunks. |
| `2` | Invalid arguments |
