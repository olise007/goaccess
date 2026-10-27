"""Private GoAccess snapshot API; nginx serves the UI and generated reports.

Only the single worker reads logs or invokes GoAccess. No database or RMS writes
occur. Source logs remain read-only; cache failures never replace a good report.
"""
import datetime as dt
import gzip
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit
from traffic import is_internal

LAGOS = ZoneInfo('Africa/Lagos')
STAMP = re.compile(rb'\[([^]]+)\]')
LOGS = Path(os.environ.get('LOG_DIR', '/var/log/apache2'))
REPORTS = Path(os.environ.get('REPORT_DIR', '/usr/share/nginx/html/reports'))
STATE = {}
LOCK = threading.Lock()
WORKER = ThreadPoolExecutor(max_workers=1)


def bounds(data, today=None):
    """Return inclusive Lagos dates; reject unknown periods and invalid ranges."""
    today = today or dt.datetime.now(LAGOS).date()
    period = data.get('period')
    if period == 'custom':
        start, end = (dt.date.fromisoformat(data.get(k, '')) for k in ('start', 'end'))
    elif period in ('today', 'yesterday', '7days', '30days'):
        end = today - dt.timedelta(days=period == 'yesterday')
        start = end - dt.timedelta(days={'today': 0, 'yesterday': 0, '7days': 6, '30days': 29}[period])
    else:
        raise ValueError('Choose a supported period.')
    if not today - dt.timedelta(days=29) <= start <= end <= today:
        raise ValueError('Choose ordered dates within the last 30 days, including today.')
    return start, end


def timestamp(line):
    """Parse Apache's numeric-offset timestamp without exposing request data."""
    match = STAMP.search(line)
    return parse_stamp(match[1]) if match else None


@lru_cache(maxsize=16384)
def parse_stamp(value):
    """Reuse parsed seconds shared by requests; cap memory for long histories."""
    return dt.datetime.strptime(value.decode('ascii'), '%d/%b/%Y:%H:%M:%S %z').astimezone(LAGOS)


def sources():
    """Exclude unrelated logs and backup files; include numbered/date archives."""
    return sorted(p for p in LOGS.glob('laravel_access.log*')
                  if re.fullmatch(r'laravel_access\.log(?:\.\d+(?:\.gz)?|-\d{8}(?:\.gz)?)?', p.name))


def filter_logs(start, end, output, cutoff=None, statistics=None):
    """Copy a stable log snapshot, retrying rename/truncate races without deduping hits.

    Each file is read only to its initial size. Appends are allowed; changes to
    archive membership, inode replacement, or truncation invalidate the snapshot.
    Identical legitimate requests are deliberately preserved. Internal source
    records remain in the audit logs but are omitted from report snapshots.
    """
    cutoff = cutoff or dt.datetime.now(LAGOS)
    for attempt in range(3):
        count, earliest, latest = 0, None, None
        excluded_internal = 0
        paths = sources()
        signatures = {}
        try:
            with open(output, 'wb') as target:
                for p in paths:
                    with open(p, 'rb') as raw:
                        stat = os.fstat(raw.fileno())
                        signatures[p] = (stat.st_ino, stat.st_size)
                        # Bound the current file so concurrent appends cannot extend the report.
                        stream = gzip.GzipFile(fileobj=raw) if p.suffix == '.gz' else raw
                        remaining = stat.st_size
                        for line in stream:
                            if stream is raw:
                                remaining -= len(line)
                                if remaining < 0:
                                    break
                            if not line.endswith(b'\n'):
                                continue
                            try:
                                stamp = timestamp(line)
                            except (ValueError, UnicodeError):
                                continue
                            if stamp is None or stamp > cutoff:
                                continue
                            earliest = stamp if earliest is None else min(earliest, stamp)
                            latest = stamp if latest is None else max(latest, stamp)
                            if start <= stamp.date() <= end:
                                address = line.split(None, 1)[0].decode('ascii', errors='replace')
                                if is_internal(address):
                                    excluded_internal += 1
                                    continue
                                target.write(line)
                                count += 1
            if paths != sources():
                raise OSError('Log rotation changed the file list.')
            for p, (inode, size) in signatures.items():
                stat = p.stat()
                if stat.st_ino != inode or stat.st_size < size:
                    raise OSError('A source log rotated or was truncated.')
            if statistics is not None:
                statistics['excludedInternal'] = excluded_internal
            return count, earliest, latest
        except (OSError, EOFError):
            if attempt == 2:
                raise RuntimeError('Logs rotated during generation. Please retry.')
    raise RuntimeError('Unable to capture logs.')


def generate(key, start, end):
    """Build one bounded report and atomically publish it, preserving earlier output."""
    try:
        REPORTS.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(REPORTS).free < 1024 ** 3 or shutil.disk_usage(LOGS).free < 1024 ** 3:
            raise RuntimeError('Low disk space: less than 1 GiB free. Report generation paused.')
        with tempfile.TemporaryDirectory(prefix='.work-', dir=REPORTS) as work:
            work = Path(work)
            cutoff = dt.datetime.now(LAGOS)
            statistics = {}
            count, earliest, latest = filter_logs(start, end, work / 'input.log', cutoff, statistics)
            result = {'status': 'empty' if count == 0 else 'ready', 'count': count,
                      'generatedAt': cutoff.isoformat(), 'start': str(start), 'end': str(end),
                      'trafficScope': 'external', **statistics,
                      'availableFrom': earliest.isoformat() if earliest else None,
                      'availableThrough': latest.isoformat() if latest else None,
                      'incomplete': earliest is None or earliest > dt.datetime.combine(start, dt.time(), LAGOS)}
            if count:
                args = ['goaccess', str(work / 'input.log'), '--log-format=%h %^[%x] "%r" %s %b "%R" "%u"',
                        '--datetime-format=%d/%b/%Y:%H:%M:%S %z',
                        '--tz=Africa/Lagos', '--no-progress', '--output=' + str(work / 'report.html'),
                        '--html-report-title=RMS traffic: ' + str(start) + ' to ' + str(end)]
                geo = Path('/usr/share/GeoIP/dbip-country-lite.mmdb')
                if geo.exists():
                    args.append('--geoip-database=' + str(geo))
                subprocess.run(args, check=True, capture_output=True, timeout=120)
                os.replace(work / 'report.html', REPORTS / (key + '.html'))
                result['url'] = '/reports/' + key + '.html'
            result['completed'] = time.time()
            with LOCK:
                STATE[key] = result
            # Cache files are expendable; source logs and latest valid reports are not.
            for p in REPORTS.glob('*.html'):
                if time.time() - p.stat().st_mtime > 86400:
                    p.unlink(missing_ok=True)
    except Exception as error:
        with LOCK:
            previous = STATE[key].get('previous', {})
            STATE[key] = {**previous, 'status': 'error', 'error': str(error) if isinstance(error, RuntimeError) else 'Report generation failed; check monitoring logs.'}
        print('Report generation failed:', type(error).__name__, str(error), flush=True)


class Handler(BaseHTTPRequestHandler):
    """JSON-only, loopback API; date requests cannot supply commands or paths."""

    def reply(self, code, payload):
        """Send a non-cacheable JSON response."""
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        """Return task state or lightweight service and storage health."""
        if self.path == '/api/health':
            free = shutil.disk_usage(LOGS).free
            self.reply(200, {'status': 'ok', 'timezone': 'Africa/Lagos', 'dateReports': True, 'trafficScope': 'external', 'lowDisk': free < 1024 ** 3})
            return
        key = self.path.removeprefix('/api/reports/')
        with LOCK:
            result = STATE.get(key)
        self.reply(200 if result else 404, result or {'error': 'Report not found.'})

    def do_POST(self):
        """Validate, reuse a fresh cache, or enqueue a single report generation."""
        try:
            if self.path != '/api/reports':
                self.reply(404, {'error': 'Not found.'})
                return
            if self.headers.get_content_type() != 'application/json':
                self.reply(415, {'error': 'Use application/json.'})
                return
            origin = self.headers.get('Origin')
            if origin and urlsplit(origin).netloc != self.headers.get('Host'):
                self.reply(403, {'error': 'Cross-origin report requests are not allowed.'})
                return
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 1024:
                raise ValueError('Invalid request size.')
            start, end = bounds(json.loads(self.rfile.read(length)))
            key = str(start) + '_' + str(end)
            with LOCK:
                prior = STATE.get(key, {})
                if prior.get('status') == 'loading' or (prior.get('status') in ('ready', 'empty') and time.time() - prior['completed'] < 300):
                    self.reply(200, {'id': key, **prior})
                    return
                if any(v.get('status') == 'loading' for v in STATE.values()):
                    self.reply(429, {'error': 'Another report is being generated. Please retry shortly.'})
                    return
                STATE[key] = {'status': 'loading', 'previous': prior}
                WORKER.submit(generate, key, start, end)
            self.reply(202, {'id': key, 'status': 'loading'})
        except (ValueError, TypeError, AttributeError):
            self.reply(400, {'error': 'Choose valid dates within the last 30 days, including today.'})


if __name__ == '__main__':
    REPORTS.mkdir(parents=True, exist_ok=True)
    ThreadingHTTPServer(('127.0.0.1', 8080), Handler).serve_forever()
