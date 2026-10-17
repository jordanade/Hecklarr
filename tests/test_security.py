import concurrent.futures
import http.client
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from load_app import loadApp


app = loadApp('hecklarr_test_security')


class RedirectTest(unittest.TestCase):
    def setUp(self):
        self.received = []
        received = self.received
        class RedirectHandler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                path = self.path.split('?')[0]
                if path in ['/same', '/cross', '/port']:
                    host = 'localhost' if path == '/cross' else '127.0.0.1'
                    port = self.server.other_port if path == '/port' else self.server.server_port
                    self.send_response(302)
                    self.send_header('Location', f'http://{host}:{port}/sink')
                    self.end_headers()
                else:
                    received.append(dict(self.headers))
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'{}')
        self.servers = [ThreadingHTTPServer(('127.0.0.1', 0), RedirectHandler) for _ in range(2)]
        self.servers[0].other_port = self.servers[1].server_port
        self.threads = []
        for server in self.servers:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.threads.append(thread)
        self.base = 'http://127.0.0.1:' + str(self.servers[0].server_port)

    def tearDown(self):
        for server, thread in zip(self.servers, self.threads, strict=True):
            server.shutdown()
            server.server_close()
            thread.join()

    def test_cross_origin_redirect_never_receives_credentials(self):
        for path in ['/cross', '/port']:
            for key, tmdb in [('dummy-radarr-key', False), ('dummy.tmdb.token', True), ('dummy-tmdb-key', True)]:
                with self.subTest(path=path, tmdb=tmdb), self.assertRaisesRegex(ValueError, 'different origin'):
                    app.requestJson(self.base + path, key, tmdb=tmdb)
        self.assertEqual([], self.received)

    def test_same_origin_redirect_still_authenticates(self):
        self.assertEqual({}, app.requestJson(self.base + '/same', 'dummy-radarr-key'))
        self.assertEqual('dummy-radarr-key', self.received[0]['X-Api-Key'])

    def test_https_downgrade_and_embedded_credentials_are_blocked(self):
        request = urllib.request.Request('https://example.test/api')
        for target in ['http://example.test/api', 'https://user:password@example.test/api']:
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, 'different origin'):
                app.SameOriginRedirectHandler().redirect_request(request, None, 302, '', {}, target)


class PrivateFileTest(unittest.TestCase):
    def test_temporary_file_is_private_before_any_data_is_written(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            original_fdopen = os.fdopen
            observed = []
            def inspectOpen(fd, *args, **kwargs):
                observed.append(os.fstat(fd).st_mode & 0o777)
                return original_fdopen(fd, *args, **kwargs)
            old_mask = os.umask(0o022)
            try:
                with patch.object(app.os, 'fdopen', side_effect=inspectOpen):
                    app.saveJson(path, {'key': 'dummy-key'})
            finally:
                os.umask(old_mask)
            self.assertEqual([0o600], observed)
            self.assertEqual(0o600, path.stat().st_mode & 0o777)
            self.assertEqual({'key': 'dummy-key'}, json.loads(path.read_text()))
            self.assertEqual([], list(Path(directory).glob('*.tmp')))

    def test_failed_write_preserves_existing_file_and_removes_temporary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            app.saveJson(path, {'key': 'old-key'})
            with patch.object(app.json, 'dumps', side_effect=ValueError('failed')), self.assertRaises(ValueError):
                app.saveJson(path, {'key': 'new-key'})
            self.assertEqual({'key': 'old-key'}, json.loads(path.read_text()))
            self.assertEqual([], list(Path(directory).glob('*.tmp')))

    def test_fixed_temporary_symlink_is_not_followed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            victim = Path(directory) / 'other.json'
            victim.write_text('unchanged')
            path.with_suffix('.tmp').symlink_to(victim)
            app.saveJson(path, {'key': 'dummy-key'})
            self.assertEqual('unchanged', victim.read_text())

    def test_interrupted_metadata_write_is_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory) / 'snapshot.interrupted.tmp'
            temporary.write_text('cached metadata')
            with patch.object(app, 'STATE_DIR', Path(directory)), patch.object(app, 'SNAPSHOT', {}):
                app.expireMetadata()
            self.assertFalse(temporary.exists())


class PasswordConcurrencyTest(unittest.TestCase):
    def test_only_two_password_hashes_run_at_once(self):
        two_hashes = threading.Event()
        release = threading.Event()
        lock = threading.Lock()
        active = 0
        peak = 0
        def hashPassword(*args, **kwargs):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
                if active == 2:
                    two_hashes.set()
            release.wait(timeout=5)
            with lock:
                active -= 1
            return b'hash'
        with patch.object(app.hashlib, 'scrypt', side_effect=hashPassword):
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
                futures = [pool.submit(app.checkPassword, 'dummy', 'scrypt$16384$8$1$c2FsdA==$aGFzaA==')
                           for _ in range(6)]
                try:
                    self.assertTrue(two_hashes.wait(timeout=5))
                finally:
                    release.set()
                self.assertTrue(all(future.result(timeout=5) for future in futures))
        self.assertEqual(2, peak)


class LoginAndServerTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.patches = [patch.object(app, 'STATE_DIR', Path(self.directory.name)),
                        patch.object(app, 'SETTINGS', {'apiKey': 'dummy-key', 'authUser': 'tester', 'authHash': 'dummy-hash'}),
                        patch.object(app, 'SNAPSHOT', {}), patch.object(app, 'FAILURES', {}),
                        patch.object(app, 'SESSIONS', {})]
        for item in self.patches:
            item.start()
        self.server = app.LimitedThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        for item in reversed(self.patches):
            item.stop()
        self.directory.cleanup()

    def login(self):
        client = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
        try:
            client.request('POST', '/api/login', json.dumps({'username': 'tester', 'password': 'dummy-password'}),
                           {'X-Hecklarr': '1'})
            response = client.getresponse()
            response.read()
            return response.status
        finally:
            client.close()

    def test_concurrent_logins_reserve_attempts_before_hashing(self):
        release = threading.Event()
        eight_checks = threading.Event()
        counter_lock = threading.Lock()
        checks = []
        def failPassword(*args):
            with counter_lock:
                checks.append(1)
                if len(checks) == 8:
                    eight_checks.set()
            release.wait(timeout=5)
            return False
        with patch.object(app, 'checkPassword', side_effect=failPassword):
            with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
                futures = [pool.submit(self.login) for _ in range(12)]
                try:
                    self.assertTrue(eight_checks.wait(timeout=5))
                    self.assertEqual(8, len(app.FAILURES['127.0.0.1']))
                finally:
                    release.set()
                statuses = [future.result(timeout=10) for future in futures]
        self.assertEqual(8, statuses.count(401))
        self.assertEqual(4, statuses.count(429))
        self.assertEqual(8, len(checks))
        self.assertEqual(8, len(app.FAILURES['127.0.0.1']))

    def test_expired_attempts_do_not_lock_out_login_and_success_resets_budget(self):
        app.FAILURES['127.0.0.1'] = [time.time() - 601] * 8
        with patch.object(app, 'checkPassword', return_value=True):
            self.assertEqual(200, self.login())
        self.assertNotIn('127.0.0.1', app.FAILURES)

    def test_incomplete_post_body_times_out_before_authentication(self):
        with patch.object(app.Handler, 'timeout', 0.2):
            client = socket.create_connection(self.server.server_address, timeout=2)
            try:
                client.sendall(b'POST /api/login HTTP/1.0\r\nX-Hecklarr: 1\r\nContent-Length: 100\r\n\r\n{')
                response = http.client.HTTPResponse(client)
                response.begin()
                self.assertEqual(408, response.status)
                response.read()
            finally:
                client.close()
        self.assertEqual({}, app.FAILURES)

    def test_dripping_headers_cannot_extend_the_total_read_deadline(self):
        stop = threading.Event()
        with patch.object(app.Handler, 'timeout', 0.3):
            client = socket.create_connection(self.server.server_address, timeout=2)
            client.sendall(b'GET / HTTP/1.0\r\nX-Test: ')
            def dripBytes():
                while not stop.wait(0.04):
                    try:
                        client.sendall(b'x')
                    except OSError:
                        break
            thread = threading.Thread(target=dripBytes, daemon=True)
            start = time.monotonic()
            thread.start()
            try:
                self.assertEqual(b'', client.recv(4096))
                self.assertLess(time.monotonic() - start, 1.5)
            finally:
                stop.set()
                thread.join()
                client.close()

    def test_worker_limit_rejects_excess_requests_and_timeout_restores_capacity(self):
        ready = threading.Event()
        class ShortTimeoutHandler(app.Handler):
            timeout = 0.3
            def setup(self):
                super().setup()
                ready.set()
        server = app.LimitedThreadingHTTPServer(('127.0.0.1', 0), ShortTimeoutHandler, max_workers=1)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        client = socket.create_connection(server.server_address, timeout=2)
        try:
            client.sendall(b'GET / HTTP/1.0\r\nHost: localhost\r\n')
            self.assertTrue(ready.wait(timeout=2))
            request = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=2)
            request.request('GET', '/')
            response = request.getresponse()
            self.assertEqual(503, response.status)
            response.read()
            request.close()
            self.assertEqual(b'', client.recv(4096))
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                request = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=2)
                request.request('GET', '/')
                response = request.getresponse()
                status = response.status
                response.read()
                request.close()
                if status == 200:
                    break
                time.sleep(0.01)
            self.assertEqual(200, status)
        finally:
            client.close()
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
