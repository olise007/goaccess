# Client attribution and external-only reporting — 27 October 2026

## Changes

Apache trusted the stale tunnel address `172.19.0.8`, while the running connector
used `172.28.0.8`. OCI Compose now pins the tunnel at its current address, and
Apache trusts only that address for `CF-Connecting-IP`. The application origin
remains published only on loopback. No entire Docker subnet is trusted.

The origin uses a named combined-format log with `%a`, the effective client IP.
`laravel_access.log` remains the full audit trail. Conditional logging writes
`laravel_external_access.log` after remote-IP processing, excluding the shared
internal CIDRs in `traffic.py`. GoAccess Live reads the external log; historical
snapshots apply the same source-address policy to the audit archives. Bot and
curl user agents are deliberately not excluded. Both access logs rotate daily,
retain 30 archives and compress. This retains an additional copy of external
traffic, so the earlier 0.9 GB uncompressed projection becomes roughly 1.8 GB
for both streams before compression, assuming the same traffic rate.

The toolbar identifies the report as External traffic. Historical metadata counts
excluded records and warns that older private tunnel-IP records cannot be
attributed or reconstructed. Counts will be lower than previous unfiltered
reports; excluding those old records does not prove there was no external traffic.
New Live history begins when the external-only log was enabled (01:57 UTC).
Use date reports for older retained public-IP records.

All source remains in the GoAccess fork. No local RMS source was modified.
OCI runtime changes were restricted to the tunnel's network configuration,
Apache's origin configuration, access-log rotation and the monitoring image.

## Verification

- All eleven tests passed in the compiled ARM64 image, including mixed internal
  and public IPv4/IPv6 fixtures, IPv4-mapped loopback, public curl preservation,
  snapshot totals, date boundaries and previous regression coverage.
- Apache configuration passed `apache2ctl configtest` and was applied with a
  graceful reload. The web container was not recreated.
- A real public probe through Cloudflare was logged with a public client IP.
- A request made from inside the web container appeared as `127.0.0.1` in the
  audit log and was absent from the external-only log.
- A request from the monitoring container with a forged `CF-Connecting-IP`
  remained attributed to its private Docker source and was excluded from the
  external log. It could not masquerade as the supplied public address.
- A synthetic request sent from the tunnel network namespace used its trusted
  forwarded public IP and appeared in both logs. This was explicitly a test,
  not evidence of a real visit from that IP. Probe query strings are labelled
  `goaccess-proof` and retained in the audit trail.
- The browser showed only public source addresses in Live and a connected
  WebSocket. Layout inspection covered 375 × 812 and 1440 × 900 viewports.
- A regenerated Today report matched its embedded GoAccess total and reported
  excluded internal records. Evidence is saved in the rollout backup.
- The installed logrotate configuration passed debug validation for both access
  streams. No production rotation or reboot was forced for testing.

The tunnel's current IP already equals the pin; it was not recreated solely to
exercise the future allocation. This proves the current request path and saved
Compose setting, not a tested tunnel-recreation or host-reboot result.

## Backup and rollback

Backup directory: `/opt/rms/backups/external-traffic-20261027`.
It holds the prior Apache host/enabled configurations, OCI Compose configuration,
rotation policy, container IDs and Today verification metadata. The previous
monitoring image is tagged `goaccess-before-external:20261027`.

For rollback, restore only the corresponding tunnel service block and Apache
configuration from this backup, copy the host Apache file into the enabled site,
run `apache2ctl configtest`, then gracefully reload Apache. Restore the rotation
policy if needed. Retag the preserved monitoring image as
`goaccess-imaorise:date-reports` and recreate only `rms-goaccess-live` using
`--no-deps --no-build`. Keep all logs; do not delete the new external log or
archives. Restoring the old Apache setting also restores its known attribution
limitation, so use this rollback only for a deployment regression.

## User-requested fresh baseline

After verification, the user explicitly requested clearing monitoring logs.
At **2026-10-27 02:02:51 UTC (03:02:51 Nigeria time)**, the active Apache access,
external access and error logs were truncated in place, preserving open file
handles. Old numbered/date archives and legacy September log backups were removed
from the monitored directory. Before clearing, all were compressed into a protected
archive outside that directory:
`/opt/rms/backups/monitoring-reset-20261027T020248Z/apache-logs.tar.gz`.
The user subsequently requested permanent removal of the archived logs. The
archive was deleted (22,635,490 bytes), and no compressed archives remain in the
monitored log directory. It is no longer available for recovery. The accompanying
`reset.json` records the reset and archive deletion; configuration/image backups
were retained.

Only the monitoring container was recreated to clear generated reports and API
cache. Its empty external log successfully generated a zero-request live report.
The source directory dropped from about 258 MB to about 8 KB; new internal health
checks remain in the audit log but not the external stream. Application/database
logs were not cleared. Previous counts, source-IP probes and the 604 excluded
Today records above describe pre-reset verification; they are not retained in
the fresh dashboard's dataset. Thirty-day retention now accumulates from the
new baseline rather than reconstructing deleted reporting history.
