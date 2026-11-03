# purplerain

Resumable bulk downloads of historical data from the [PurpleAir API](https://api.purpleair.com/), built for long-running sensor networks such as SAMOSA.

- **Resumable.** Progress is saved after every request. To continue an interrupted download, run the same command again.
- **Safe on disk.** Each request's data gets its own file, and existing files are never overwritten.
- **Easy to navigate.** Data is filed by calendar month, so each `YYYY-MM/` folder holds exactly that month's data.
- **Supports private sensors.** Each sensor's read key is sent only when needed and never appears in logs.
- **Automatable.** GitHub Actions workflows run the tests, download data monthly, and publish this site.

```bash
pip install -e .
cp .env.example .env    # add your PurpleAir API key
python scripts/download_all.py --start 2025-10-01 --end 2025-11-01
```

```{toctree}
:maxdepth: 1
:caption: User guide

getting-started
usage
github-actions
```

```{toctree}
:maxdepth: 1
:caption: Reference

cli
api
changelog
```
