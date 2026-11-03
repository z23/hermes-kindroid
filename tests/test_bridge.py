"""Offline tests: only the loopback HTTP server receives requests."""
import importlib.util
import json
import os
import socket
import sys
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("kindroid_bridge_test", ROOT / "__init__.py")
bridge = importlib.util.module_from_spec(spec) if spec else None
if (ROOT / "__init__.py").exists():
    spec.loader.exec_module(bridge)


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers['Content-Length']))
        self.server.received.append((self.path, dict(self.headers), json.loads(body)))
        with self.server.counter_lock:
            self.server.active += 1
            self.server.max_active = max(self.server.max_active, self.server.active)
        time.sleep(self.server.delay)
        self.send_response(self.server.status)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        if self.server.claimed_length is not None:
            self.send_header('Content-Length', str(self.server.claimed_length))
        if self.server.location:
            self.send_header('Location', self.server.location)
        self.end_headers()
        try:
            self.wfile.write(self.server.body)
        except (BrokenPipeError, ConnectionResetError):
            pass
        with self.server.counter_lock:
            self.server.active -= 1

    def log_message(self, *args):
        pass


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.received = []
        self.server.active = 0
        self.server.max_active = 0
        self.server.counter_lock = threading.Lock()
        self.server.status = 200
        self.server.body = 'External Kin reply ✓'.encode()
        self.server.delay = 0
        self.server.location = None
        self.server.claimed_length = None
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}/v1/send-message'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def client(self, **kwargs):
        self.assertTrue(hasattr(bridge, '_Bridge'), 'Missing bridge implementation')
        return bridge._Bridge('test-key', 'fixed-kin', 'Test Kin',
                              _url=self.url, **kwargs)

    def test_registered_handler_exercises_real_http_with_fixed_target(self):
        client = self.client()
        ctx = Context()
        with patch.object(bridge, '_settings', return_value=('test-key', 'fixed-kin', 'Test Kin')):
            bridge.register(ctx)
            self.assertTrue(ctx.tools[0]['check_fn']())
            with patch.object(bridge, '_Bridge', return_value=client):
                result = json.loads(ctx.tools[0]['handler']({'message': 'Hermes relay: Hi'}, task_id='offline-test'))
        self.assertTrue(result['success'])
        self.assertEqual(result['reply'], 'External Kin reply ✓')
        self.assertEqual(self.server.received[0][2]['ai_id'], 'fixed-kin')
        self.assertEqual(len(self.server.received), 1)

    def test_truncated_http_response_reports_unknown_delivery(self):
        self.server.claimed_length = 1000
        result = self.client().send({'message': 'Hi'})
        self.assertFalse(result['success'])
        self.assertEqual(result['delivery'], 'unknown')
        self.assertEqual(len(self.server.received), 1)

    def test_unusable_responses_fail_without_claiming_reply(self):
        for body in (b'', b' \r\n', b'\xff'):
            with self.subTest(body=body):
                self.server.body = body
                result = self.client().send({'message': 'Hi'})
                self.assertFalse(result['success'])
                self.assertEqual(result['delivery'], 'unknown')
                self.assertNotIn('reply', result)

    def test_same_kin_sends_are_serialized_across_instances(self):
        self.server.delay = 0.08
        clients = [self.client(), self.client()]
        results = []
        workers = [threading.Thread(target=lambda c=c: results.append(c.send({'message': 'Hi'}))) for c in clients]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(2)
            self.assertFalse(worker.is_alive())
        self.assertEqual(len(results), 2)
        self.assertTrue(all(result['success'] for result in results))
        self.assertEqual(self.server.max_active, 1)

    def test_200_error_sentinels_are_not_replies(self):
        for body in (b'<<ERROR>>private test-key', b' \r\n<<HTTP_ERROR>>private test-key'):
            with self.subTest(body=body):
                self.server.body = body
                result = self.client().send({'message': 'Hi'})
                self.assertFalse(result['success'])
                self.assertIn('error', result)
                self.assertNotIn('reply', result)
                self.assertNotIn('private', str(result))
                self.assertNotIn('test-key', str(result))
        self.assertEqual(len(self.server.received), 2)

    def test_network_failure_is_sanitized_and_delivery_unknown(self):
        with socket.socket() as reserved:
            reserved.bind(('127.0.0.1', 0))
            client = self.client()
            client._url = f'http://127.0.0.1:{reserved.getsockname()[1]}/'
            result = client.send({'message': 'private transcript'})
        self.assertFalse(result['success'])
        self.assertEqual(result['delivery'], 'unknown')
        self.assertIn('No automatic retry', result['error'])
        self.assertNotIn('test-key', str(result))
        self.assertNotIn('private transcript', str(result))
        self.assertEqual(self.server.received, [])

    def test_timeout_reports_unknown_delivery_without_retry(self):
        self.server.delay = 0.15
        result = self.client(_timeout=0.03).send({'message': 'Hi'})
        self.assertFalse(result['success'])
        self.assertEqual(result['delivery'], 'unknown')
        self.assertIn('No automatic retry', result['error'])
        self.assertEqual(len(self.server.received), 1)

    def test_redirects_never_forward_authorization(self):
        for status in (301, 302, 303, 307, 308):
            with self.subTest(status=status):
                self.server.status = status
                self.server.location = self.url + '/stolen'
                result = self.client().send({'message': 'Hi'})
                self.assertFalse(result['success'])
                self.assertEqual(result['http_status'], status)
        self.assertEqual(len(self.server.received), 5)
        self.assertTrue(all(item[0] == '/v1/send-message' for item in self.server.received))

    def test_http_errors_are_sanitized_without_retry(self):
        for status in (400, 401, 403, 429, 500):
            with self.subTest(status=status):
                self.server.status = status
                self.server.body = b'private transcript test-key'
                result = self.client().send({'message': 'Hi'})
                self.assertFalse(result['success'])
                self.assertEqual(result['http_status'], status)
                self.assertNotIn('private', str(result))
                self.assertNotIn('test-key', str(result))
        self.assertEqual(len(self.server.received), 5)

    def test_invalid_arguments_never_send(self):
        client = self.client()
        for args in ({}, None, [], {'message': None}, {'message': 42},
                     {'message': ''}, {'message': ' \n\t'},
                     {'message': 'Hi', 'kin_id': 'other'},
                     {'message': 'Hi', 'url': 'https://elsewhere.invalid'}):
            with self.subTest(args=args):
                result = client.send(args)
                self.assertFalse(result['success'])
                self.assertIn('message', result['error'])
        self.assertEqual(self.server.received, [])

    def test_send_returns_attributed_plaintext_and_fixed_payload(self):
        result = self.client().send({'message': 'Hermes relay: Please advise.'})
        self.assertTrue(result['success'])
        self.assertEqual(result['reply'], 'External Kin reply ✓')
        self.assertEqual(result['source'], 'external_kindroid')
        self.assertEqual(result['display_name'], 'Test Kin')
        path, headers, payload = self.server.received[0]
        self.assertEqual(path, '/v1/send-message')
        self.assertEqual(headers['Authorization'], 'Bearer test-key')
        self.assertEqual(headers['Content-Type'], 'application/json')
        self.assertEqual(payload, {'ai_id': 'fixed-kin', 'message': '[via Hermes]\nHermes relay: Please advise.', 'stream': False})
        self.assertEqual(len(self.server.received), 1)


class Context:
    def __init__(self):
        self.tools = []
        self.skills = []

    def register_tool(self, **kwargs):
        self.tools.append(kwargs)

    def register_skill(self, name, path, **kwargs):
        self.skills.append((name, path, kwargs))


class RegistrationTests(unittest.TestCase):
    def test_missing_or_malformed_setup_fails_closed(self):
        cases = [(None, {}), ({}, {}), ({'plugins': []}, {}),
                 ({'plugins': {'kindroid-bridge': []}}, {}),
                 ({'plugins': {'kindroid-bridge': {'kin_id': 'fixed'}}}, {}),
                 ({'plugins': {'kindroid-bridge': {'kin_id': 'fixed'}}}, {'KINDROID_API_KEY': ' '}),
                 ({'plugins': {'kindroid-bridge': {'kin_id': 'fixed'}}}, {'KINDROID_API_KEY': 'bad\nkey'}),
                 ({'plugins': {'kindroid-bridge': {'kin_id': ' fixed '}}}, {'KINDROID_API_KEY': 'dummy'}),
                 ({'plugins': {'kindroid-bridge': {'kin_id': 123}}}, {'KINDROID_API_KEY': 'dummy'}),
                 ({'plugins': {'kindroid-bridge': {'kin_id': 'fixed', 'display_name': []}}}, {'KINDROID_API_KEY': 'dummy'})]
        for config, env in cases:
            with self.subTest(config=config, env=env):
                fake = SimpleNamespace(load_config_readonly=lambda: config)
                with patch.dict(sys.modules, {'hermes_cli.config': fake}), patch.dict(os.environ, env, clear=True):
                    self.assertIsNone(bridge._settings())
        def broken():
            raise RuntimeError('sensitive config error')
        with patch.dict(sys.modules, {'hermes_cli.config': SimpleNamespace(load_config_readonly=broken)}):
            self.assertIsNone(bridge._settings())

    def test_settings_read_hermes_config_and_environment_without_normalizing_values(self):
        config = {'plugins': {'kindroid-bridge': {'kin_id': 'configured-kin', 'display_name': 'Example Kin'}}}
        fake = SimpleNamespace(load_config_readonly=lambda: config)
        with patch.dict(sys.modules, {'hermes_cli.config': fake}), patch.dict(os.environ, {'KINDROID_API_KEY': 'dummy-key'}, clear=True):
            self.assertEqual(bridge._settings(), ('dummy-key', 'configured-kin', 'Example Kin'))

    def test_registration_succeeds_but_tool_is_unavailable_without_setup(self):
        self.assertTrue(hasattr(bridge, 'register'), 'Missing native plugin entrypoint')
        ctx = Context()
        with patch.object(bridge, '_settings', return_value=None):
            bridge.register(ctx)
            self.assertEqual(len(ctx.tools), 1)
            tool = ctx.tools[0]
            self.assertEqual(tool['name'], 'kindroid_send_message')
            self.assertFalse(tool['check_fn']())
            self.assertEqual(tool['requires_env'], ['KINDROID_API_KEY'])
            result = json.loads(tool['handler']({'message': 'Hi'}))
            self.assertFalse(result['success'])
            self.assertIn('KINDROID_API_KEY', result['error'])
            self.assertIn('kin_id', result['error'])
        parameters = tool['schema']['parameters']
        self.assertEqual(parameters['required'], ['message'])
        self.assertEqual(set(parameters['properties']), {'message'})
        self.assertFalse(parameters['additionalProperties'])
        self.assertEqual(len(ctx.skills), 1)
        self.assertEqual(ctx.skills[0][0], 'kindroid-relay')
        self.assertTrue(Path(ctx.skills[0][1]).is_file())


if __name__ == '__main__':
    unittest.main()
