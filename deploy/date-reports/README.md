# Native date reports for the Imaorise GoAccess fork

This fork embeds compact date controls in GoAccess's own generated HTML, inside
its dashboard header. There is no wrapper page or iframe. The controls inherit
the selected GoAccess theme. Ordinary offline HTML reports continue to work;
controls appear only when the same-origin reporting API advertises support.

## Build and run

From this repository root:

```sh
export GOACCESS_LOG_DIR=/absolute/path/to/apache/logs
export MONITOR_BIND=127.0.0.1
export GOACCESS_WS_URL=127.0.0.1:7890
docker compose -f deploy/date-reports/compose.yaml up -d --build
```

Open `http://127.0.0.1:7891`. For remote private access, use your Tailscale address
for both `MONITOR_BIND` and `GOACCESS_WS_URL` (include `:7890` in the latter).
The service has no application login: keep it on loopback or a trusted private
network, or put authenticated access in front of both HTTP and WebSocket ports.
Never publish the raw log directory. Source logs are mounted read-only.

The Dockerfile compiles this repository, rather than installing stock GoAccess.
To build only the CLI, use the upstream build instructions in the root README;
the native UI code is embedded by the existing asset-generation process.

## Period semantics and API

- Live reads the current access log and uses the normal GoAccess WebSocket.
- Today and Yesterday use Africa/Lagos calendar days. Last 7/30 days include
  today and the preceding 6/29 days. Custom dates include both end days.
- `POST /api/reports` accepts JSON `{ "period": "today" }`, or
  `{ "period": "custom", "start": "2026-10-20", "end": "2026-10-22" }`.
  The other period values are `yesterday`, `7days`, and `30days`.
- `GET /api/reports/<id>` returns `loading`, `ready`, `empty`, or `error`.
  Successful metadata includes count, snapshot time, date bounds, available
  timestamps, incomplete-history indication, and the generated report URL.
- `GET /api/health` advertises `dateReports`, timezone and a low-disk warning.
  JSON POSTs must originate from the same host when an Origin header is present.
- Only one generation runs at a time. Repeated requests for that range share the
  job; other ranges receive 429 and can be retried. Results are cached for five
  minutes. Generated HTML cache files expire after a day when a new job finishes.
- The browser navigates to a complete static report after generation. Historical
  pages have no live WebSocket, so live events cannot replace filtered totals.
  Selecting Live returns to `/live.html`. Empty/error results keep the existing
  dashboard visible and explicitly say so.

The worker reads the current file, numbered archives and date-suffixed archives,
including gzip files. It snapshots initial file sizes and retries detectable
rename/truncation races. Identical legitimate requests are preserved. It does
not ingest legacy files with unrelated backup names. Coverage timestamps describe
retained records, not proof that every intervening request was logged. Apache
`copytruncate` has an inherent copy/truncate loss window; this change does not
claim to eliminate that logging limitation.

Use the full timestamp format, including `%z`, with `--tz=Africa/Lagos`.
The stock COMBINED preset alone does not shift daily groupings across UTC
midnight. The entrypoint and snapshot service both use the explicit format.

## Retention and resource limits

`logrotate.conf` is the OCI policy template: access logs rotate daily with
30 compressed archives, independently of the previous error-log size policy.
Install it as root-owned mode 0644 at `/etc/logrotate.d/rms-monitoring`, after
backing up the existing policy. Inspect `logrotate --debug` first; do not force
production rotation as a test. The host's enabled daily timer applies it.
Existing numbered archives are preserved as a finite migration set. They remain
readable, but reports reject date ranges outside the last 30 days.

OCI's existing records began on 18 October 2026. Earlier history is unavailable;
the UI labels a request starting before the earliest record as incomplete.
The initial measured 246,986,923 uncompressed bytes over 8.25 days project to
about 898 MB for 30 days before compression, compared with about 17 GB free.
Actual growth can change. The API warns and pauses generation below 1 GiB free
on either the source-log or report filesystem; it never deletes source logs to
make room. Each job needs temporary space for its selected uncompressed records
plus GoAccess output. Report storage is container-private and disposable.

## Tests and rollback

```sh
python3 -m unittest discover -s deploy/date-reports/tests -v
docker build -f deploy/date-reports/Dockerfile -t goaccess-imaorise:date-reports .
docker run --rm --entrypoint python3 -v "$PWD:/work:ro" \
  goaccess-imaorise:date-reports -m unittest discover -s /work/deploy/date-reports/tests -v
```

The container test also exercises the compiled C parser's Nigeria-midnight
conversion. Tests cover archive formats, legitimate duplicate records, inclusive
bounds, snapshot cutoff, detectable rotation and missing-file retries, cache
expiry, concurrency, empty data and preservation after generation failure.

Before updating a deployed monitoring service, save its Compose service block,
source configuration, logrotate policy and image. Retain an image tag and a
`docker image save` export. Roll back only the monitoring service's image/build
settings and rotation policy, then recreate that service with `--no-deps`.
Do not restart the application, database, or tunnel. Keep the data mounts and
private host-port bindings identical. The OCI walkthrough records exact backup
paths, the executed rollback drill and final verification limits.
