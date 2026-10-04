"""Offline Mail protocol, journal, parser, and actual JXA fixture tests."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("apple_desk_mail_cli", ROOT / "cli/grok-mail/lib/cli.py")
mail = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mail)


class MailTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="apple-desk-mail-tests-")
        self.directory = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"APPLE_DESK_STATE_DIR": str(self.directory / "state")})
        self.env.start()
        self.content = {"from": "me@example.invalid", "to": ["you@example.invalid"], "subject": "Hello 日本語", "body": "$(not executable)\n`not a command`"}
        self.input = self.directory / "draft.json"
        self.input.write_text(json.dumps(self.content))
        self.fixture = self.directory / "mail-fixture.js"
        self.fixture.write_text(mail.LIB.read_text() + "\n" + (ROOT / "tests/fixtures/mail-offline.js").read_text())

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def args(self, *args):
        return mail.build_parser().parse_args(args)

    def create(self):
        return mail.execute(self.args("draft", "create", "--input", str(self.input)))

    def test_legacy_positional_query_and_structured_options(self):
        args = self.args("search", "renewal", "--account", "a", "--subject", "invoice", "--max-scan", "17", "--timeout", "120", "--unread")
        self.assertEqual(args.query, "renewal")
        with patch.object(mail, "run_bridge", return_value={}) as run:
            mail.execute(args)
            self.assertEqual(run.call_args.args[1]["subject"], "invoice")
            self.assertIn("unread", run.call_args.args[2])

    def test_invalid_timeout_precedes_any_backend(self):
        with patch.object(mail, "run_bridge") as run:
            with self.assertRaises(mail.ToolError):
                mail.execute(self.args("accounts", "--timeout", "nan"))
            run.assert_not_called()

    def test_missing_force_prevents_external_mutation(self):
        reference = "mailmsg:v1:%7B%7D"
        with patch.object(mail, "run_bridge") as run:
            with self.assertRaises(mail.ToolError) as result:
                mail.execute(self.args("mark", reference, "--read"))
            self.assertEqual(result.exception.code, "CONFIRMATION_REQUIRED")
            run.assert_not_called()

    def test_permission_preflight_blocks_jxa_without_prompt(self):
        status = {"running": True, "allowed": False, "authorization": "notDetermined", "prompts": False}
        with patch.object(mail, "native_permission", return_value=status), patch.object(mail, "spawn_bridge") as spawn:
            with self.assertRaises(mail.ToolError) as result:
                mail.run_bridge("accounts")
            self.assertEqual(result.exception.code, "PERMISSION_REQUIRED")
            spawn.assert_not_called()

    def test_doctor_reports_not_authorized_without_jxa(self):
        status = {"running": False, "allowed": False, "prompts": False}
        with patch.object(mail, "native_permission", return_value=status), patch.object(mail, "spawn_bridge") as spawn:
            self.assertEqual(mail.run_bridge("doctor"), status)
            spawn.assert_not_called()

    def test_draft_persistence_private_files_and_literal_body(self):
        record = self.create()
        file = self.directory / "state" / mail.draft_path(record["id"])
        self.assertEqual(file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(file.read_text())["content"]["body"], self.content["body"])
        shown = mail.execute(self.args("draft", "show", record["id"]))
        self.assertEqual(shown["content"]["subject"], self.content["subject"])

    def test_draft_validation(self):
        for patch_value in ({"from": "me@x\r\nBcc:bad@x"}, {"subject": "bad\nheader"}, {"to": "you@x"}, {"attachments": ["/missing/fixture"]}, {"replyAll": True}):
            value = dict(self.content, **patch_value)
            with self.assertRaises(mail.ToolError):
                mail.validate_draft(value)

    def test_accepted_send_replay_does_not_execute_or_preflight_twice(self):
        draft = self.create()
        calls = []
        def fake(action, options, flags, positionals=None, content=None):
            calls.append(set(flags))
            return {"dryRun": True} if "dry-run" in flags else {"accepted": True, "deliveryConfirmed": False}
        with patch.object(mail, "run_bridge", side_effect=fake):
            first = mail.execute(self.args("draft", "send", draft["id"], "--force", "--idempotency-key", "send-one"))
            replay = mail.execute(self.args("draft", "send", draft["id"].upper(), "--force", "--idempotency-key", "send-one"))
        self.assertTrue(first["accepted"])
        self.assertTrue(replay["replayed"])
        self.assertEqual(len(calls), 2)

    def test_uncertain_send_never_retried_even_with_new_key(self):
        draft = self.create()
        actual_sends = []
        def fake(action, options, flags, positionals=None, content=None):
            if "dry-run" in flags:
                return {"dryRun": True}
            actual_sends.append(1)
            raise mail.ToolError("SEND_STATUS_UNKNOWN", "fixture uncertainty")
        with patch.object(mail, "run_bridge", side_effect=fake):
            for key in ("uncertain", "uncertain", "new-key"):
                with self.assertRaises(mail.ToolError):
                    mail.execute(self.args("draft", "send", draft["id"], "--force", "--idempotency-key", key))
        self.assertEqual(len(actual_sends), 1)
        self.assertEqual(mail.draft_record(mail.StateStore(), draft["id"])["state"], "unknown")

    def test_send_preflight_failure_keeps_draft_editable_and_key_available(self):
        draft = self.create()
        with patch.object(mail, "run_bridge", side_effect=mail.ToolError("INVALID_INPUT", "sender missing")):
            with self.assertRaises(mail.ToolError):
                mail.execute(self.args("draft", "send", draft["id"], "--force", "--idempotency-key", "preflight"))
        self.assertEqual(mail.draft_record(mail.StateStore(), draft["id"])["state"], "ready")
        self.assertIsNone(mail.StateStore().read(mail.StateStore.operation_path("preflight")))

    def test_protocol_error_is_shared_envelope(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = mail.main(["draft", "--to", "you@x"])
        response = json.loads(output.getvalue())
        self.assertEqual(code, 2)
        self.assertFalse(response["ok"])
        self.assertEqual(response["schemaVersion"], "1.0")
        self.assertIn("meta", response)

    def test_triage_dry_run_is_structural_offline_preview(self):
        from urllib.parse import quote
        reference = "mailmsg:v1:" + quote(json.dumps({"accountID": "a", "mailboxPath": ["INBOX"], "id": 1, "messageID": "<fixture>"}), safe="")
        with patch.object(mail, "run_bridge") as run:
            preview = mail.execute(self.args("move", reference, "--to", "Archive", "--dry-run"))
        self.assertTrue(preview["dryRun"])
        self.assertFalse(preview["targetVerified"])
        run.assert_not_called()

    def test_derived_reply_cannot_send_without_explicit_recipients(self):
        from urllib.parse import quote
        reference = "mailmsg:v1:" + quote(json.dumps({"accountID": "a", "mailboxPath": ["INBOX"], "id": 1, "messageID": "<fixture>"}), safe="")
        self.input.write_text(json.dumps({"from": "me@example.invalid", "body": "Reply"}))
        draft = mail.execute(self.args("draft", "reply", reference, "--input", str(self.input)))
        with patch.object(mail, "run_bridge") as run:
            with self.assertRaises(mail.ToolError) as stopped:
                mail.execute(self.args("draft", "send", draft["id"], "--force", "--idempotency-key", "reply"))
        self.assertEqual(stopped.exception.code, "INVALID_INPUT")
        self.assertEqual(mail.draft_record(mail.StateStore(), draft["id"])["state"], "ready")
        run.assert_not_called()

    @unittest.skipUnless(Path("/usr/bin/osascript").is_file(), "JXA requires macOS")
    def test_nonsearch_read_timeout_does_not_claim_write(self):
        with self.assertRaises(mail.ToolError) as stopped:
            mail.spawn_bridge("read", {"fixture": "read-stall", "timeout": "1"}, script_path=self.fixture)
        self.assertEqual(stopped.exception.code, "TIMEOUT")
        self.assertTrue(stopped.exception.details["readOnly"])
        self.assertFalse(stopped.exception.details["writeMayHaveTakenEffect"])
        self.assertIn("No mail was modified", stopped.exception.message)

    @unittest.skipUnless(Path("/usr/bin/osascript").is_file(), "JXA requires macOS")
    def test_fixed_jxa_fixture_suite(self):
        result = mail.spawn_bridge("self-test", {"fixture": "suite"}, script_path=self.fixture)
        self.assertTrue(result["passed"])
        self.assertFalse(result["mailAccessed"])
        self.assertGreaterEqual(len(result["checks"]), 15)

    @unittest.skipUnless(Path("/usr/bin/osascript").is_file(), "JXA requires macOS")
    def test_actual_hard_kill_preserves_checkpoint_and_resume(self):
        options = {"account": "a", "mailbox": "INBOX", "limit": "10", "fixture": "stall", "timeout": "1"}
        with self.assertRaises(mail.ToolError) as stopped:
            mail.spawn_bridge("search", options, script_path=self.fixture)
        error = stopped.exception
        self.assertEqual(error.code, "TIMEOUT")
        self.assertEqual(error.details["action"], "search")
        self.assertTrue(error.details["readOnly"])
        self.assertTrue(error.details["resumeAvailable"])
        self.assertFalse(error.details["writeMayHaveTakenEffect"])
        self.assertEqual(error.data["coverage"]["nextOffset"], 1)
        self.assertEqual(len(error.data["messages"]), 1)
        options.update(fixture="resume", timeout="3", cursor=error.data["nextCursor"])
        result = mail.spawn_bridge("search", options, script_path=self.fixture)
        self.assertEqual([m["id"] for m in result["messages"]], [101, 102])
        self.assertTrue(result["coverage"]["reachedEnd"])

    @unittest.skipUnless(Path("/usr/bin/osascript").is_file(), "JXA requires macOS")
    def test_native_timeout_is_error_with_partial_data(self):
        with self.assertRaises(mail.ToolError) as stopped:
            mail.spawn_bridge("search", {"account": "a", "mailbox": "INBOX", "fixture": "native-timeout"}, script_path=self.fixture)
        self.assertEqual(stopped.exception.code, "TIMEOUT")
        self.assertEqual(stopped.exception.data["coverage"]["nextOffset"], 1)


if __name__ == "__main__":
    unittest.main()
