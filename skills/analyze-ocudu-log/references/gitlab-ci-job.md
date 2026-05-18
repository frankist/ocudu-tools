# GitLab CI Job — Artifact Retrieval Steps

A CI job may contain several independent test runs, each with their own artifacts. Do **not** download any artifacts before the user selects a specific test run.

## Step 1 — Fetch the raw job log (lightweight)

```bash
curl -fsSL "https://gitlab.com/<group>/<project>/-/jobs/<job_id>/raw" -o /tmp/job.log
# If the project is private: add --header "PRIVATE-TOKEN: $GITLAB_TOKEN"
```

## Step 2 — Extract the run list

The raw log contains ANSI escape codes — strip them before processing:
```bash
sed 's/\x1b\[[0-9;]*m//g' /tmp/job.log > /tmp/job_clean.log
```

For pytest-based jobs, extract the short test summary at the end of the log:
```bash
grep -A200 'short test summary info' /tmp/job_clean.log | \
  grep -E '(FAILED|PASSED|SKIPPED|ERROR) tests/'
```

This produces lines like:
```
FAILED tests/ue_simulator.py::test_gnb[performance/mobility/paging::paging] - Failed: Test didn't pass the following criteria: 5GS NAS Service Accept, Warnings
FAILED tests/ue_simulator.py::test_gnb[performance/mobility/paging::rrc_inactive_t308_expire] - Failed: Stop stage. GNB_1 has 9 errors: RealtimeSanitizer: unsafe-library-call
```

The **Retina test framework** (used for OCUDU e2e CI tests) also emits per-component warning summaries at test end — high-value fast signals:
```bash
grep -E 'has [0-9]+ errors|has [0-9]+ warnings' /tmp/job_clean.log | head -20
```
Example: `[WARNING] GNB_1 has 9 errors and 23705 warnings. First error is: RealtimeSanitizer: unsafe-library-call`

For non-pytest jobs, fall back to:
```bash
grep -E '(PASSED|FAILED|SKIPPED|ERROR):' /tmp/job_clean.log
```

Build a numbered list showing status, test name, and failure reason. Present it to the user. **Do not proceed until they pick a run.**

## Step 3 — Download the job artifacts

There is one artifact archive per job (not per test):
```bash
curl -fsSL "https://gitlab.com/<group>/<project>/-/jobs/<job_id>/artifacts/download" \
  -o /tmp/job_artifacts.zip
python3 -m zipfile -e /tmp/job_artifacts.zip /tmp/run_artifacts/
find /tmp/run_artifacts -maxdepth 3 | sort
```

> **Note**: use `python3 -m zipfile` rather than `unzip`. The `unzip` CLI interprets `[...]` in
> paths as shell glob patterns and silently skips entries whose names contain brackets — a common
> occurrence with pytest parameterized test names such as
> `test_gnb[band:41-scs:30-bandwidth:50-udp-uplink]`.

Artifacts are typically organised in per-test subdirectories: `e2e/<test_name>/gnb.log`, `e2e/<test_name>/ue.pcap`, etc. Inspect the structure returned by `find` to confirm before navigating into a subdirectory.

There is typically one `Test report ---> <url>` line at the end of the job log, pointing to a consolidated HTML report for the whole job.

## Step 4 — Proceed as a run folder

Treat the downloaded files as a run folder and apply **case 2 (Folder path provided)** from SKILL.md.
