"""Exercise date semantics, archive snapshots and failure-safe publishing."""
import datetime as dt
import gzip
import importlib.util
from pathlib import Path
import tempfile
import shutil
import subprocess
import unittest
import threading
import json
import urllib.request
import urllib.error
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('reports', Path(__file__).parents[1] / 'server.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


def line(stamp):
    """Return a valid combined-log fixture with a caller-controlled timestamp."""
    return f'127.0.0.1 - - [{stamp}] "GET / HTTP/1.1" 200 10 "-" "test"\n'.encode()


class ReportsTest(unittest.TestCase):
    """Use disposable logs; never read production traffic."""

    def setUp(self):
        """Isolate all source and generated files."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.logs = Path(self.temp.name) / 'logs'
        self.logs.mkdir()
        self.output = Path(self.temp.name) / 'filtered'
        self.patcher = patch.object(r, 'LOGS', self.logs)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_periods_and_validation(self):
        """Presets include today and reject dates outside the retained window."""
        today = dt.date(2026, 10, 27)
        for period, expected in [('today', 27), ('yesterday', 26), ('7days', 21), ('30days', 28)]:
            start, end = r.bounds({'period': period}, today)
            self.assertEqual(start.day, expected)
        for data in [{'period': 'invalid'}, {'period': 'custom', 'start': 'x', 'end': 'x'},
                     {'period': 'custom', 'start': '2026-10-28', 'end': '2026-10-28'},
                     {'period': 'custom', 'start': '2026-10-27', 'end': '2026-10-26'}]:
            with self.assertRaises(ValueError):
                r.bounds(data, today)

    def test_midnight_archives_and_duplicates(self):
        """Include Lagos midnight and both identical legitimate requests exactly once."""
        (self.logs / 'laravel_access.log').write_bytes(line('26/Oct/2026:23:00:00 +0000') * 2)
        (self.logs / 'laravel_access.log.1').write_bytes(line('26/Oct/2026:22:59:59 +0000'))
        with gzip.open(self.logs / 'laravel_access.log.2.gz', 'wb') as f:
            f.write(line('27/Oct/2026:22:59:59 +0000') + line('27/Oct/2026:23:00:00 +0000'))
        day = dt.date(2026, 10, 27)
        count, earliest, latest = r.filter_logs(day, day, self.output, dt.datetime(2026, 10, 29, tzinfo=r.LAGOS))
        self.assertEqual(count, 3)
        self.assertEqual(earliest.date(), dt.date(2026, 10, 26))
        self.assertEqual(len(self.output.read_bytes().splitlines()), 3)

    def test_missing_archive_retries(self):
        """A disappearing archive retries rather than returning partial success."""
        missing = self.logs / 'laravel_access.log.1'
        with patch.object(r, 'sources', return_value=[missing]):
            with self.assertRaises(RuntimeError):
                r.filter_logs(dt.date.today(), dt.date.today(), self.output)

    def test_empty_snapshot(self):
        """No source records produces an explicit empty snapshot."""
        self.assertEqual(r.filter_logs(dt.date.today(), dt.date.today(), self.output)[0], 0)

    def test_rotation_retry(self):
        """Changed source membership triggers a fresh scan without duplicate output."""
        current = self.logs / 'laravel_access.log'
        current.write_bytes(line('27/Oct/2026:01:00:00 +0000'))
        with patch.object(r, 'sources', side_effect=[[current], [], [current], [current]]):
            self.assertEqual(r.filter_logs(dt.date(2026, 10, 27), dt.date(2026, 10, 27), self.output, dt.datetime(2026, 10, 28, tzinfo=r.LAGOS))[0], 1)

    def test_failure_preserves_previous(self):
        """A failed rebuild leaves the preceding report and URL usable."""
        report_dir = Path(self.temp.name) / 'reports'
        report_dir.mkdir()
        old = report_dir / 'example.html'
        old.write_text('previous valid report')
        r.STATE['example'] = {'status': 'loading', 'previous': {'url': '/reports/example.html'}}
        with patch.object(r, 'REPORTS', report_dir), patch.object(r, 'filter_logs', side_effect=RuntimeError('fixture failure')):
            r.generate('example', dt.date.today(), dt.date.today())
        self.assertEqual(old.read_text(), 'previous valid report')
        self.assertEqual(r.STATE['example']['status'], 'error')
        self.assertEqual(r.STATE['example']['url'], '/reports/example.html')


    @unittest.skipUnless(shutil.which('goaccess'), 'Requires the compiled GoAccess binary')
    def test_goaccess_groups_offset_timestamp_in_nigeria(self):
        """Check the real C parser, since --tz alone does not shift COMBINED dates."""
        source = self.logs / 'midnight.log'
        source.write_bytes(line('26/Oct/2026:23:00:00 +0000'))
        output = Path(self.temp.name) / 'report.json'
        subprocess.run(['goaccess', str(source), '--log-format=%h %^[%x] "%r" %s %b "%R" "%u"',
                        '--datetime-format=%d/%b/%Y:%H:%M:%S %z', '--tz=Africa/Lagos',
                        '--no-progress', '--output=' + str(output)], check=True, capture_output=True)
        data = json.loads(output.read_text())
        self.assertEqual(data['visitors']['data'][0]['data'], '20261027')
        self.assertEqual(data['general']['total_requests'], 1)

    def test_snapshot_cutoff_and_inclusive_custom_dates(self):
        """The selected last day is inclusive, but requests after capture are excluded."""
        day = dt.date(2026, 10, 27)
        (self.logs / 'laravel_access.log').write_bytes(line('26/Oct/2026:23:00:00 +0000') + line('27/Oct/2026:23:00:00 +0000'))
        start, end = r.bounds({'period': 'custom', 'start': str(day), 'end': str(day)}, day)
        count, _, _ = r.filter_logs(start, end, self.output, dt.datetime(2026, 10, 27, 12, tzinfo=r.LAGOS))
        self.assertEqual(count, 1)

    def test_api_cache_expiry_and_concurrency(self):
        """Reuse fresh results, serialize generation and rebuild expired snapshots."""
        server = r.ThreadingHTTPServer(('127.0.0.1', 0), r.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        r.STATE.clear()
        key = str(dt.datetime.now(r.LAGOS).date())
        key = key + '_' + key
        url = 'http://127.0.0.1:' + str(server.server_port) + '/api/reports'
        def post(period):
            """Submit a period using the same HTTP contract as the browser."""
            return urllib.request.urlopen(urllib.request.Request(url, json.dumps({'period': period}).encode(), {'Content-Type': 'application/json'}))
        with patch.object(r.WORKER, 'submit') as submit:
            r.STATE[key] = {'status': 'ready', 'completed': r.time.time(), 'count': 1}
            self.assertEqual(json.load(post('today'))['status'], 'ready')
            submit.assert_not_called()
            r.STATE[key]['completed'] -= 301
            self.assertEqual(json.load(post('today'))['status'], 'loading')
            self.assertEqual(json.load(post('today'))['status'], 'loading')
            self.assertEqual(submit.call_count, 1)
            with self.assertRaises(urllib.error.HTTPError) as context:
                post('yesterday')
            self.assertEqual(context.exception.code, 429)
            context.exception.close()
        r.STATE.clear()


if __name__ == '__main__':
    unittest.main()
