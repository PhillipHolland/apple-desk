import importlib.util
import contextlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('dispatcher', ROOT / 'cli/apple-desk/lib/cli.py')
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


class DispatcherTests(unittest.TestCase):
    def call(self, argv):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = cli.main(argv)
        return code, json.loads(output.getvalue())

    def test_discovery_is_offline(self):
        with patch.object(cli.subprocess, 'run', side_effect=AssertionError('must be offline')):
            for command in ['version', 'capabilities', 'schema', '--help']:
                code, result = self.call([command])
                self.assertEqual(code, 0)
                self.assertTrue(result['ok'])
                self.assertEqual(result['schemaVersion'], '1.0')

    def test_pass_through_partial_mail_timeout(self):
        partial = {'schemaVersion': '1.0', 'ok': False, 'data': {'messages': [1], 'nextCursor': 'x'},
                   'error': {'code': 'TIMEOUT', 'details': {'readOnly': True, 'writeMayHaveTakenEffect': False}}, 'meta': {}}
        with patch.object(cli, 'run_json', return_value=(5, partial)):
            code, result = self.call(['mail', 'search', '--subject', 'renewal'])
        self.assertEqual(code, 5)
        self.assertEqual(result, partial)

    def test_legacy_error_is_not_success(self):
        with patch.object(cli, 'run_json', return_value=(0, {'ok': False, 'error': 'denied', 'message': 'blocked'})):
            code, result = self.call(['notes', 'list'])
        self.assertNotEqual(code, 0)
        self.assertFalse(result['ok'])

    def test_doctor_reports_denial_without_requesting_access(self):
        calls = []
        def fake(surface, args, timeout):
            calls.append(args)
            return 0, {'ok': True, 'data': {'authorization': 'denied', 'fullAccess': False}}
        with patch.object(cli, 'run_json', side_effect=fake):
            code, result = self.call(['doctor'])
        self.assertEqual(code, 0)
        self.assertFalse(result['data']['permissionsRequested'])
        self.assertEqual(calls, [['doctor'], ['doctor']])
        self.assertFalse(result['data']['checks']['calendar']['report']['data']['fullAccess'])

    def test_permissions_failure_is_not_success(self):
        with patch.object(cli, 'run_json', return_value=(3, {'ok': False, 'error': {'code': 'PERMISSION_REQUIRED'}})):
            code, result = self.call(['permissions', 'request', '--calendar'])
        self.assertEqual(code, 3)
        self.assertFalse(result['ok'])


class DispatcherDeadlineTests(unittest.TestCase):
    def test_outer_read_timeout_has_no_write_uncertainty(self):
        with patch.object(cli.subprocess, 'Popen', side_effect=cli.subprocess.TimeoutExpired('fixture', 1)):
            with self.assertRaises(cli.ToolError) as caught:
                cli.run_json('mail', ['search', '--account', 'fixture'], timeout=1)
        self.assertEqual(caught.exception.exit_code, 5)
        self.assertTrue(caught.exception.details['readOnly'])
        self.assertFalse(caught.exception.details['writeMayHaveTakenEffect'])

    def test_outer_write_timeout_is_uncertain(self):
        with patch.object(cli.subprocess, 'Popen', side_effect=cli.subprocess.TimeoutExpired('fixture', 1)):
            with self.assertRaises(cli.ToolError) as caught:
                cli.run_json('calendar', ['update', '--uid', 'fixture'], timeout=1)
        self.assertEqual(caught.exception.exit_code, 6)
        self.assertTrue(caught.exception.details['writeMayHaveTakenEffect'])
