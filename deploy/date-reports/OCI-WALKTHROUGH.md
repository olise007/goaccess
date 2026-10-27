# OCI native GoAccess date reports — 27 October 2026

## Delivered

Fork: https://github.com/olise007/goaccess, based on upstream `fb62f16c` (GoAccess
1.12). Development checkout: `/home/imaorise/webdevfiles/Projects/goaccess-imaorise`.
All enhancement source, tests and documentation are in this fork. The local RMS
checkout was restored to its original clean state. The earlier wrapper prototype
was moved out of the Projects directory; it is not the delivered interface.

Date controls are embedded by GoAccess's existing resource compilation into its
own HTML header. They reuse its native layout, buttons and theme settings.
There is no wrapper or iframe. The private Python service generates complete
snapshots, with the API and period semantics documented in README.md here.

## Deployment and rollback

- Native source: `/opt/goaccess-imaorise`.
- Existing endpoint: `http://100.124.91.34:7891`, with the live WebSocket on 7890.
- Only the OCI runtime Compose block for `rms-goaccess-live` changed: its build
  context now points to the separate fork, its Dockerfile is
  `deploy/date-reports/Dockerfile`, its image is `goaccess-imaorise:date-reports`,
  and `WS_URL` retains the existing Tailscale WebSocket address.
- Host ports, network and read-only log/GeoIP mounts were preserved. The original
  monitoring source files under `/opt/rms/docker/monitoring` were restored;
  its new wrapper source files were removed after being backed up.
- Final ARM64 image ID:
  `sha256:41fe3b69f9b6efda09fc07272e04596d32f7c224d64b2249a4ec3c970098f14f`.
- Original configuration and exported image:
  `/opt/rms/backups/goaccess-dates-20261027`. The stock-image rollback script
  there was executed and the old report verified before the fork rollout.
- Native rollout backup: `/opt/rms/backups/goaccess-native-20261027`. It contains
  `oci-compose.yaml` (before), `oci-compose.native.yaml` (after), and
  `restore-monitor-service.py`, which restores only the selected monitoring
  service block, preserving unrelated live services and configuration.
- A native-to-previous-image rollback drill was executed: the restored service
  answered its health API and reported GoAccess 1.9.4. The native service block
  was reapplied and GoAccess 1.12 verified. The previous wrapper image remains
  tagged `goaccess-wrapper-before-native:20261027`; its source is archived in
  the native backup's `monitoring-wrapper` directory.

To restore the prior monitoring image, run as root on OCI:

```sh
python3 /opt/rms/backups/goaccess-native-20261027/restore-monitor-service.py \
  /opt/rms/backups/goaccess-native-20261027/oci-compose.yaml
docker compose --env-file /opt/rms/secrets/compose.env \
  -f /opt/rms/docker/oci-compose.yaml up -d --no-deps --no-build rms-goaccess-live
```

To return to the native fork, repeat using `oci-compose.native.yaml` instead.
Use the preserved image without rebuilding the previous wrapper from the restored
stock source. Initial-stock rollback instructions are in the original backup.
Neither rollback command changes logs or the installed retention policy.

## Retention and resource evidence

The root-owned `/etc/logrotate.d/rms-monitoring` now retains 30 daily compressed
access-log archives. Error logs keep the previous four-file, 50 MB policy.
`logrotate --debug` successfully parsed both groups; the host timer was enabled
and active. No production rotation was forced for testing. Existing numbered
archives were preserved as a finite migration set.

Measured access history: 246,986,923 bytes uncompressed over about 8.25 days,
projecting to about 898 MB over 30 days before compression. There were about
17 GB free before builds and 16 GB afterward. This is a projection, not a storage
reservation. Below 1 GiB free, historical generation pauses with a warning rather
than deleting logs. Available records begin on 18 October; deleted earlier
history cannot be recovered. The 30-day report is therefore labelled incomplete.

## Validation

- Ten focused tests passed inside the compiled ARM64 image. These exercise date
  presets, invalid/future/reversed bounds, Nigeria midnight conversion through
  the C parser, inclusive custom dates, snapshot cutoff, plain/gzip archives,
  legitimate duplicate requests, missing archives, rotation retries, cache
  expiry, concurrent requests, empty data and failure-safe publishing.
- API checks also reject non-JSON and cross-origin POSTs. Temporary source-log
  snapshot paths are blocked by Nginx rather than publicly served.
- The long-line regression failed on the first build (one request counted as
  two), then passed with the supported `--with-getline` build option. OCI had
  19 access records longer than the default 4 KB buffer. The fixed build avoids
  phantom failed records and is used for both live and historical parsing.
- The final period verification compares each report's embedded GoAccess total
  with the number of selected source records, checks native controls/no iframe,
  and confirms five-minute cache reuse. Exact counts and generation durations
  are saved in the native backup's `verification.json`.
- Browser inspection covered 375 × 812 and 1440 × 900 layouts, light and dark
  themes, custom dates, keyboard selection/submission, focus, disabled/loading,
  empty/error feedback, history expansion and scrolling. Error feedback was
  simulated locally; it kept the previous dashboard visible. The native layout
  had no outer horizontal overflow in the inspected states.
- The OCI browser showed a connected live WebSocket and navigated from Live to
  a native historical report with matching displayed totals and no iframe.
- Runtime JS, CSS, server, entrypoint, Nginx and Dockerfile hashes matched the
  local fork. Only the monitoring container was recreated; application, database,
  tunnel and other container IDs remained unchanged. Public RMS returned HTTP 200.

No authenticated RMS workflow or actual phone acceptance was claimed. Thirty-day
future retention has not yet elapsed. Rotation tests simulate detected changes;
they do not eliminate Apache copytruncate's inherent logging loss window.
