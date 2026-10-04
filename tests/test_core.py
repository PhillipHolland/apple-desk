import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'cli/shared'))
from agent_core import StateStore, ToolError, emit_error, emit_success


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = StateStore(Path(self.temp.name) / 'state')

    def test_completed_operation_replays_without_preflight_or_write(self):
        calls = []
        first = self.store.perform('abc', 'send', {'a': 1}, lambda: calls.append('write') or {'accepted': True})
        second = self.store.perform('abc', 'send', {'a': 1}, lambda: self.fail('duplicate'), preflight=lambda: self.fail('replayed preflight'))
        self.assertEqual(calls, ['write'])
        self.assertFalse(first['replayed'])
        self.assertTrue(second['replayed'])

    def test_uncertain_write_cannot_retry(self):
        calls = []
        def write():
            calls.append('write')
            raise ToolError('TIMEOUT', 'timed out')
        for _ in range(2):
            with self.assertRaises(ToolError) as caught:
                self.store.perform('abc', 'send', {}, write)
            self.assertEqual(caught.exception.code, 'OPERATION_STATUS_UNKNOWN')
            self.assertTrue(caught.exception.details['writeMayHaveTakenEffect'])
        self.assertEqual(calls, ['write'])
        self.assertEqual(self.store.operation('abc')['status'], 'unknown')

    def test_preflight_does_not_consume_key(self):
        def invalid():
            raise ToolError('INVALID_ARGUMENT', 'bad')
        with self.assertRaises(ToolError):
            self.store.perform('abc', 'create', {}, lambda: self.fail('mutation'), preflight=invalid)
        self.assertIsNone(self.store.read(self.store.operation_path('abc')))
        self.assertFalse(self.store.perform('abc', 'create', {}, lambda: {})['replayed'])

    def test_payload_conflict(self):
        self.store.perform('abc', 'send', {'a': 1}, lambda: {})
        with self.assertRaises(ToolError) as caught:
            self.store.perform('abc', 'send', {'a': 2}, lambda: self.fail('duplicate'))
        self.assertEqual(caught.exception.code, 'IDEMPOTENCY_CONFLICT')

    def test_pending_journal_survives_interruption(self):
        def killed():
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.store.perform('abc', 'send', {}, killed)
        self.assertEqual(self.store.operation('abc')['status'], 'pending')
        with self.assertRaises(ToolError) as caught:
            self.store.perform('abc', 'send', {}, lambda: self.fail('duplicate'))
        self.assertEqual(caught.exception.exit_code, 6)

    def test_atomic_private_state_and_traversal(self):
        self.store.write('drafts/a.json', {'body': 'hello'})
        self.assertEqual(self.store.read('drafts/a.json')['body'], 'hello')
        self.assertEqual(self.store.directory.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.store.directory / 'drafts/a.json').stat().st_mode & 0o777, 0o600)
        for name in ['../x', '/tmp/x']:
            with self.assertRaises(ToolError):
                self.store.write(name, {})
        (self.store.directory / 'bad').symlink_to(self.temp.name)
        with self.assertRaises(ToolError):
            self.store.write('bad/x', {})

    def test_lock_is_busy_across_instances_and_reentrant_locally(self):
        with self.store.locked():
            with self.store.locked():
                self.store.write('test.json', {})
            with self.assertRaises(ToolError) as caught:
                with StateStore(self.store.directory).locked():
                    self.fail('concurrent lock')
            self.assertEqual(caught.exception.code, 'BUSY')

    def test_readonly_timeout_preserves_data(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = emit_error(ToolError('TIMEOUT', 'stalled', {'readOnly': True, 'writeMayHaveTakenEffect': False}, {'messages': [1], 'nextCursor': 'abc'}))
        result = json.loads(output.getvalue())
        self.assertEqual(code, 5)
        self.assertFalse(result['ok'])
        self.assertEqual(result['data']['nextCursor'], 'abc')
        self.assertFalse(result['error']['details']['writeMayHaveTakenEffect'])
