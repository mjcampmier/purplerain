# Running purplerain on GitHub Actions

The repository includes two workflows in `.github/workflows/`:

| Workflow | File | Triggers | Secrets |
| --- | --- | --- | --- |
| **CI** | `ci.yml` | Every push to `main`/`master` and every pull request | None |
| **Download PurpleAir data** | `download.yml` | Monthly schedule and manual runs | `PURPLEAIR_API_KEY`, `PURPLERAIN_SENSOR_TABLE` |

## CI

`ci.yml` runs the following on Python 3.10, 3.11, 3.12 and 3.13:

1. `ruff check .` and `ruff format --check .`
2. `pytest`

The tests make no network calls and need no secrets, so CI also works for pull requests from forks. You don't need to set anything up.

To reproduce CI locally:

```bash
pip install -e ".[dev]"
ruff check . && ruff format --check . && pytest
```

## Data download workflow

> [!WARNING]
> **Run the download workflow only in a private repository.** It uploads the downloaded data as a workflow artifact, and anyone who can read the repository can download artifacts and read run logs. Read keys are masked in the logs, but the sensor data itself is not, and data from private sensors should stay private.

### What it does

1. **Picks the date window.** By default this is the previous calendar month in UTC, from the 1st of last month up to (but not including) the 1st of this month.
2. **Reads the sensor table.** It decodes the table from the `PURPLERAIN_SENSOR_TABLE` secret and masks every read key in it, so no key can appear in the logs.
3. **Downloads the data** by running `scripts/download_all.py` into `data/`.
4. **Writes a summary** to the run's page: chunks planned, downloaded, empty and failed.
5. **Uploads `data/`** as an artifact named `purpleair-<start>-to-<end>`, kept for 90 days.

### One-time setup

You need admin access to the repository and the [GitHub CLI](https://cli.github.com/) logged in (`gh auth login`). Run these commands from the repository root. You can also add secrets in the web interface under **Settings → Secrets and variables → Actions → New repository secret**.

**1. The PurpleAir API key**

```bash
gh secret set PURPLEAIR_API_KEY
# paste the key when prompted
```

**2. The sensor table**

The workflow needs the same deployment history that you use locally. That history contains each sensor's private read key, so it is passed in as a secret and never committed. The secret holds a base64-encoded, gzipped CSV with these columns:

| Column | Meaning |
| --- | --- |
| `purpleair_sensor_index` | PurpleAir sensor ID |
| `private_key` | Sensor read key (blank for public sensors) |
| `effective_date` | Date the deployment started (`YYYY-MM-DD`) |
| `discontinue_date` | Date the deployment ended (blank if still active) |

To create the secret from your existing `history.feather`:

```bash
TMP="$(mktemp -d)"
python - "$TMP/sensors.csv.gz" <<'EOF'
import sys
import pandas as pd

cols = ["purpleair_sensor_index", "private_key", "effective_date", "discontinue_date"]
history = pd.read_feather("path/to/history.feather", columns=cols)
history.to_csv(sys.argv[1], index=False, date_format="%Y-%m-%d")
EOF
base64 < "$TMP/sensors.csv.gz" | gh secret set PURPLERAIN_SENSOR_TABLE
rm -r "$TMP"
```

The full SAMOSA history (1,144 deployments) encodes to about 18 KB, well under GitHub's 48 KB secret limit. Re-run these commands whenever the history changes, for example when sensors are added or read keys change.

If the table ever grows past 48 KB, follow GitHub's guide to [storing large secrets](https://docs.github.com/actions/security-guides/using-secrets-in-github-actions#storing-large-secrets). In short: commit a `gpg`-encrypted copy of the file, store only the passphrase as a secret, and decrypt it in the "Decode sensor table" step.

### Running a download

**On a schedule.** The workflow runs at 06:00 UTC on the 2nd of every month and downloads the previous calendar month. GitHub only runs schedules from the default branch and may start them a little late.

**Manually from the browser.** Open the **Actions** tab, choose **Download PurpleAir data**, then **Run workflow**. Leave the dates blank to download last month.

**Manually from the command line:**

```bash
gh workflow run download.yml -f start=2025-03-01 -f end=2025-04-01
gh run watch                      # follow progress
```

| Input | Default | Notes |
| --- | --- | --- |
| `start` | 1st of last month | Inclusive, `YYYY-MM-DD`, UTC |
| `end` | 1st of this month | **Exclusive**, `YYYY-MM-DD`, UTC |
| `installed_after` | `2024-03-01` | Only includes sensors installed on or after this date (SAMOSA Phase 2). Use an earlier date to include Phase 1 sensors. |

The workflow downloads every sensor whose deployment overlaps the window, up to the earlier of its discontinue date and `end`. Requests are split at month boundaries and are never longer than 30 days, which is PurpleAir's limit for raw data.

### Getting the data

```bash
gh run list --workflow download.yml          # find the run ID
gh run download <run-id> --dir downloads/    # fetch its artifact
```

Each artifact contains:

```
download_progress.feather
download.log
YYYY-MM/sensor_<id>_<start YYYYMMDD>_<end YYYYMMDD>.feather
```

Artifacts are deleted after 90 days, so copy them somewhere permanent. Every data file name is unique, so you can merge artifacts into one dataset without overwriting anything:

```bash
rsync -a --ignore-existing downloads/purpleair-*/20??-??/ ~/path/to/dataset/
```

Don't merge the `download_progress.feather` files. Each one only describes its own run.

### Failures and re-runs

- **The job is marked as failed if any chunk failed.** The script exits with status 1, but whatever did download is still uploaded, and the run summary shows the counts. Check `download.log` in the artifact, or the job log, for each failure.
- **Each run starts from scratch.** Runs don't share progress, so **Re-run jobs** downloads the whole window again.
- **Common errors:**
  - `An invalid sensor data read_key ... was provided`: that sensor's key in the history table is wrong. Fix it and update the `PURPLERAIN_SENSOR_TABLE` secret.
  - `Real-time history maximum time span is thirty (30) days`: `--chunk-days` was set above 30.
  - `401`/`403` on every request: `PURPLEAIR_API_KEY` is missing or invalid.
- **Rate limits.** The workflow uses a concurrency group, so only one download runs at a time. The client also retries `429` and `5xx` responses with exponential backoff.
- **Run time and API points.** One month for about 160 sensors takes roughly 10 minutes and about 330 requests. Every request uses PurpleAir API points. The job times out after 5 hours; GitHub-hosted runners allow at most 6.

### Security notes

- **Pull requests can't reach the secrets.** The download workflow only runs on its schedule or when started manually by someone with write access. GitHub doesn't pass secrets to workflows triggered from forks.
- **Inputs can't inject commands.** Workflow inputs reach shell scripts through environment variables, never by being pasted directly into the script text.
- **Minimal permissions.** The workflow's `GITHUB_TOKEN` can only read the repository's contents.
- **Keys are masked.** GitHub automatically hides a secret's whole value in logs, but not individual pieces of it, so it wouldn't catch a single read key from the sensor table. The workflow therefore masks every key with `::add-mask::` before the download starts, and the client also removes keys from its own error messages.
- **Changing the API key.** Run `gh secret set PURPLEAIR_API_KEY` again. No code change is needed.

### Customizing

| To change… | Edit |
| --- | --- |
| How often it runs | The `cron` line in `download.yml` |
| Which sensors are included | The `installed_after` default, or the sensor table itself |
| Where the data goes | Replace the "Upload data" step, for example with a step that syncs `data/` to S3 or Google Cloud Storage |
| Fields or averaging period | `scripts/download_all.py`, or call `PurpleAirNetworkDownloader` from your own script (see the [README](../README.md#library)) |
