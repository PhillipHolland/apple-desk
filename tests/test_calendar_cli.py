import base64
from contextlib import redirect_stdout
from datetime import datetime, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("apple_desk_calendar_cli", ROOT / "cli/grok-calendar/lib/cli.py")
cal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cal)


class CalendarCLITests(unittest.TestCase):
    def args(self, *words):
        return cal.build_parser().parse_args(list(words))

    def test_doctor_only_requests_status(self):
        with patch.object(cal, "native", return_value={"fullAccess": False}) as native:
            cal.execute(self.args("doctor", "--json"))
            native.assert_called_once_with("doctor")

    def test_permission_is_explicit_command(self):
        with patch.object(cal, "native", return_value={}) as native:
            cal.execute(self.args("permissions", "request"))
            native.assert_called_once_with("permissions")

    def test_local_timed_start_requires_zone(self):
        with self.assertRaises(cal.ToolError):
            cal.execute(self.args("create", "--calendar-id", "work", "--title", "Focus", "--start", "2026-10-03 09:00", "--dry-run"))

    def test_dry_run_has_end_and_never_calls_native_or_state(self):
        with patch.object(cal, "native", side_effect=AssertionError("called native")), patch.object(cal, "StateStore", side_effect=AssertionError("state touched")):
            result = cal.execute(self.args("create", "--calendar-id", "work", "--title", "Focus", "--start", "2026-10-03 09:00", "--time-zone", "America/New_York", "--dry-run"))
        self.assertEqual(cal.stamp(result["event"]["end"]).timestamp() - cal.stamp(result["event"]["start"]).timestamp(), 3600)
        self.assertFalse(result["targetVerified"])
        self.assertFalse(result["calendarVerified"])

    def test_all_day_end_is_exclusive_next_day(self):
        result = cal.execute(self.args("create", "--calendar", "Calendar", "--title", "Away", "--start", "2026-03-08", "--all-day", "--dry-run"))
        self.assertEqual(result["event"]["end"], "2026-03-09")

    def test_all_day_supplied_zone_is_normalized_to_system_floating(self):
        result = cal.execute(self.args("create", "--calendar-id", "c", "--title", "Away", "--start", "2026-03-08", "--all-day", "--time-zone", "Pacific/Auckland", "--dry-run"))
        self.assertEqual(result["event"]["start"], "2026-03-08")
        self.assertEqual(result["event"]["end"], "2026-03-09")
        self.assertNotIn("timeZone", result["event"])
        self.assertNotIn("timeZone", result["options"])

    def test_native_timeout_reports_read_and_write_semantics(self):
        with tempfile.TemporaryDirectory() as directory:
            helper = Path(directory) / "helper"; helper.touch(); helper.chmod(0o700)
            for action, writes in (("events", False), ("update", True)):
                with self.subTest(action=action), patch.object(cal, "HELPER", helper), patch.object(cal.subprocess, "run", side_effect=subprocess.TimeoutExpired("helper", 45)):
                    with self.assertRaises(cal.ToolError) as context:
                        cal.native(action)
                    self.assertEqual(context.exception.details["writeMayHaveTakenEffect"], writes)
                    self.assertEqual(context.exception.details["readOnly"], not writes)

    def test_all_day_day_length_tracks_dst(self):
        z = cal.zone("America/New_York")
        a = cal.stamp("2026-03-08", z, True)
        b = cal.stamp("2026-03-09", z, True)
        self.assertEqual(b.timestamp() - a.timestamp(), 23 * 3600)

    def test_invalid_dates_gap_and_ambiguity_rejected(self):
        z = cal.zone("America/New_York")
        for value in ("2026-02-30T09:00", "2026-03-08T02:30", "2026-11-01T01:30", "2026-10-03T09:00+24:00"):
            with self.subTest(value=value), self.assertRaises(cal.ToolError): cal.stamp(value, z)
        self.assertNotEqual(cal.stamp("2026-11-01T01:30:00-04:00").timestamp(), cal.stamp("2026-11-01T01:30:00-05:00").timestamp())

    def test_equal_end_start_rejected_offline(self):
        with self.assertRaises(cal.ToolError):
            cal.execute(self.args("create", "--calendar-id", "c", "--title", "x", "--start", "2026-10-03T10:00:00Z", "--end", "2026-10-03T10:00:00Z", "--dry-run"))

    def test_range_date_end_inclusive_timestamp_end_exclusive(self):
        first = cal.ranges(self.args("list", "--from", "2026-10-03", "--to", "2026-10-03", "--time-zone", "Etc/UTC"))
        self.assertEqual(cal.stamp(first["to"]).timestamp() - cal.stamp(first["from"]).timestamp(), 86400)
        second = cal.ranges(self.args("list", "--from", "2026-10-03T09:00:00Z", "--to", "2026-10-03T10:00:00Z"))
        self.assertEqual(cal.stamp(second["to"]).timestamp() - cal.stamp(second["from"]).timestamp(), 3600)

    def test_list_keeps_actual_ids_and_end_fields(self):
        event = {"id": "real", "uid": "real", "reference": "event:real", "calendarId": "calendar-real", "start": "2026-10-03T09:00:00Z", "end": "2026-10-03T10:00:00Z", "allDay": False, "timeZone": "Etc/UTC"}
        with patch.object(cal, "native", return_value={"events": [event], "total": 1, "offset": 0, "truncated": False}) as native:
            result = cal.execute(self.args("list", "--calendar-id", "calendar-real", "--from", "2026-10-03", "--to", "2026-10-04", "--light", "--live"))
        self.assertIs(result["events"][0], event)
        self.assertEqual(native.call_args.args[0], "events")
        self.assertEqual(native.call_args.args[1]["calendarId"], "calendar-real")
        self.assertTrue(native.call_args.args[1]["light"])

    def test_read_recurring_reference_needs_no_scope(self):
        ref = "event:" + base64.urlsafe_b64encode(json.dumps({"id": "id", "calendarId": "c", "occurrence": "2026-10-03T09:00:00Z"}).encode()).decode().rstrip("=")
        with patch.object(cal, "native", return_value={"event": {}}) as native:
            cal.execute(self.args("show", "--uid", ref))
        self.assertEqual(native.call_args.args[0], "read")

    def test_recurring_write_reference_demands_scope(self):
        ref = "event:" + base64.urlsafe_b64encode(json.dumps({"id": "id", "calendarId": "c", "occurrence": "2026-10-03T09:00:00Z"}).encode()).decode().rstrip("=")
        with self.assertRaises(cal.ToolError): cal.execute(self.args("delete", "--uid", ref, "--dry-run"))
        result = cal.execute(self.args("delete", "--uid", ref, "--scope", "this", "--dry-run"))
        self.assertTrue(result["wouldDelete"])
        with self.assertRaises(cal.ToolError): cal.execute(self.args("delete", "--uid", ref, "--scope", "this", "--calendar-id", "other", "--dry-run"))

    def test_delete_without_force_cannot_call_native(self):
        with patch.object(cal, "native", side_effect=AssertionError("called native")):
            with self.assertRaises(cal.ToolError) as context: cal.execute(self.args("delete", "--uid", "id"))
        self.assertEqual(context.exception.code, "CONFIRMATION_REQUIRED")

    def test_create_requires_idempotency_before_native(self):
        with patch.object(cal, "native", side_effect=AssertionError("called native")):
            with self.assertRaises(cal.ToolError): cal.execute(self.args("create", "--calendar-id", "c", "--title", "x", "--start", "2026-10-03T09:00:00Z"))

    def test_create_retry_does_not_duplicate(self):
        args = self.args("create", "--calendar-id", "c", "--title", "x", "--start", "2026-10-03T09:00:00Z", "--idempotency-key", "repeat-key")
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"APPLE_DESK_STATE_DIR": directory}), patch.object(cal, "native", side_effect=[{"validated": True}, {"event": {"id": "created"}}]) as native:
            first, second = cal.execute(args), cal.execute(args)
        self.assertEqual(native.call_count, 2)
        self.assertFalse(first["replayed"])
        self.assertTrue(second["replayed"])

    def test_unsupported_fields_and_invalid_recurrence_fail_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            value = {"title": "x", "calendarId": "c", "start": "2026-10-03T09:00:00Z", "attendees": ["x@example.com"]}
            path.write_text(json.dumps(value))
            with self.assertRaises(cal.ToolError): cal.execute(self.args("create", "--input", str(path), "--dry-run"))
            value.pop("attendees"); value["recurrence"] = {"frequency": "daily", "interval": True}; path.write_text(json.dumps(value))
            with self.assertRaises(cal.ToolError): cal.execute(self.args("create", "--input", str(path), "--dry-run"))

    def test_native_receives_fixed_json_stdin_not_source(self):
        value = {"title": "`touch /tmp/no` $(bad) \" ;", "notes": "line\nline"}
        with tempfile.TemporaryDirectory() as directory:
            helper = Path(directory) / "helper"; helper.touch(); helper.chmod(0o700)
            with patch.object(cal, "HELPER", helper), patch.object(cal.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, '{"ok":true,"data":{}}', "")) as run:
                cal.native("validate-create", {}, value)
        self.assertEqual(run.call_args.args[0], [str(helper)])
        self.assertEqual(json.loads(run.call_args.kwargs["input"])["input"], value)
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_encoding_failure_after_write_is_uncertain(self):
        with tempfile.TemporaryDirectory() as directory:
            helper = Path(directory) / "helper"; helper.touch(); helper.chmod(0o700)
            response = '{"ok":false,"error":{"code":"ENCODING_ERROR","message":"failed"}}'
            with patch.object(cal, "HELPER", helper), patch.object(cal.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, response, "")):
                with self.assertRaises(cal.ToolError) as context: cal.native("update")
            self.assertEqual(context.exception.code, "WRITE_STATUS_UNKNOWN")
            self.assertTrue(context.exception.details["writeMayHaveTakenEffect"])

    def test_bad_arguments_produce_shared_error_envelope(self):
        output = io.StringIO()
        with redirect_stdout(output): code = cal.main(["delete", "--uid", "id", "--json"])
        payload = json.loads(output.getvalue())
        self.assertNotEqual(code, 0)
        self.assertEqual(payload["schemaVersion"], "1.0")
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "CONFIRMATION_REQUIRED")


if __name__ == "__main__": unittest.main()
