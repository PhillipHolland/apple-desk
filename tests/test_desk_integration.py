"""Offline fixtures for passive desk probes, EventKit indexes and safe previews."""
import contextlib
import importlib.util
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DESK = ROOT / "cli/grok-desk/lib"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


common = load("desk_test_common", DESK / "common.py")
with patch.dict(sys.modules, {"common": common}):
    calendar = load("desk_test_calendar", DESK / "calendar_index.py")
    with patch.dict(sys.modules, {"calendar_index": calendar}):
        sys.path.insert(0, str(DESK))
        try:
            desk = load("desk_test_cli", DESK / "cli.py")
        finally:
            sys.path.remove(str(DESK))
reminders = load("desk_test_reminder_wrap", ROOT / "cli/grok-reminders/lib/pim_wrap.py")


def envelope(data, ok=True, error=None, code=0):
    return {"ok": code == 0, "code": code, "stdout": json.dumps({"schemaVersion": "1.0", "ok": ok,
            "data": data, "error": error, "meta": {"version": "0.2.0"}}), "stderr": ""}


def event(ident="event-real", calendar_id="cal-real", **changes):
    row = {"id": ident, "uid": ident, "calendarId": calendar_id, "calendar": "Shared name",
           "title": "Fixture meeting", "start": "2026-10-03T12:00:00+02:00", "end": "2026-10-03T13:00:00+02:00",
           "allDay": False, "timeZone": "Europe/Paris", "reference": "event:opaque-fixture", "occurrence": "2026-10-03T10:00:00Z"}
    row.update(changes)
    return row


def page(events, offset=0, total=None):
    total = len(events) + offset if total is None else total
    return {"ok": True, "data": {"events": events, "offset": offset, "total": total,
                                   "truncated": offset + len(events) < total}}


class DeskEnvelopeTests(unittest.TestCase):
    def test_success_exit_does_not_override_error_envelope(self):
        result = common.unwrap_result(envelope(None, ok=False, error={"code": "PERMISSION_REQUIRED", "message": "fixture"}))
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "PERMISSION_REQUIRED")

    def test_empty_successful_process_is_not_authorized(self):
        self.assertFalse(common.unwrap_result({"ok": True, "code": 0, "stdout": ""})["ok"])

    def test_doctor_denied_and_timeout_never_become_authorized(self):
        for data in [{"authorization": "denied", "fullAccess": False},
                     {"authorization": "timeout", "fullAccess": False, "checked": False},
                     {"authorization": "fullAccess", "fullAccess": False}]:
            with patch.object(common, "which", return_value="fixture-cli"), patch.object(common, "version_of", return_value="0.2.0"), patch.object(common, "run_cmd", return_value=envelope(data)) as run:
                result = desk._run_surface_doctor("grok-calendar", 8)
            self.assertFalse(result["ok"])
            self.assertFalse(result["authorized"])
            self.assertEqual(run.call_args.args[0], ["fixture-cli", "doctor", "--json"])

    def test_positive_doctor_requires_report_and_permission_evidence(self):
        with patch.object(common, "which", return_value="fixture-cli"), patch.object(common, "version_of", return_value="0.2.0"), patch.object(common, "run_cmd", return_value=envelope({"authorization": "fullAccess", "fullAccess": True})):
            self.assertTrue(desk._run_surface_doctor("grok-calendar", 8)["authorized"])

    def test_mail_requires_native_allowed_evidence(self):
        for allowed in [True, False, None]:
            data = {"authorization": "authorized", "allowed": allowed, "running": True, "prompts": False}
            with patch.object(common, "which", return_value="fixture-cli"), patch.object(common, "version_of", return_value="0.2.0"), patch.object(common, "run_cmd", return_value=envelope(data)):
                result = desk._run_surface_doctor("grok-mail", 8)
            self.assertEqual(result["authorized"], allowed is True)

    def test_legacy_doctor_is_not_called_during_passive_status(self):
        with patch.object(common, "which", return_value="fixture-cli"), patch.object(common, "version_of", return_value="fixture"), patch.object(common, "run_cmd", side_effect=AssertionError("must not probe legacy app")):
            result = desk._run_surface_doctor("grok-reminders", 8)
        self.assertEqual(result["checked"], "version")
        self.assertIsNone(result["authorized"])

    def test_onboarding_never_indexes_links_or_requests_permissions(self):
        with patch.object(desk, "safe_doctors", return_value=[]), patch.object(desk, "do_reindex", side_effect=AssertionError("must not index")), patch.object(common, "link_if_needed", side_effect=AssertionError("must not link")), patch.object(common, "read_signature", return_value=None):
            result = desk.do_onboard(True, True)
            guided, code = desk.do_guided_onboard(True)
        self.assertTrue(result["passive"])
        self.assertEqual(result["indexes"], [])
        self.assertFalse(guided["prompts"])
        self.assertEqual(code, 0)


class CalendarIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "index.sqlite"
        self.patches = [patch.object(common, "db_path", return_value=self.path),
                        patch.object(common, "which", return_value="fixture-calendar"),
                        patch.object(calendar, "window_days", return_value=(0, 1, date(2026, 10, 3), date(2026, 10, 5))),
                        patch.object(calendar, "_midnight", side_effect=lambda day: datetime.combine(day, datetime.min.time(), timezone.utc))]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def build(self, pages, calendars=None):
        calendars = calendars or [{"id": "cal-real", "title": "Shared name", "writable": True}]
        responses = [{"ok": True, "data": {"authorization": "fullAccess", "fullAccess": True}},
                     {"ok": True, "data": {"calendars": calendars}}] + pages
        with patch.object(calendar, "_run", side_effect=responses) as run:
            result = calendar.build()
        return result, run

    def test_actual_ids_exact_ends_timezone_reference_and_pagination(self):
        second = event("day-real", start="2026-10-04", end="2026-10-05", allDay=True, timeZone="America/New_York", occurrence=None)
        result, run = self.build([page([event()], total=2), page([second], offset=1, total=2)])
        self.assertTrue(result["ok"])
        self.assertEqual(result["rows"], 2)
        self.assertIn("cal-real", run.call_args_list[2].args[0])
        self.assertEqual(run.call_args_list[3].args[0][-3:], ["--offset", "1", "--json"])
        self.assertIn("--light", run.call_args_list[2].args[0])
        cached = calendar.cached_search("Fixture", 20)
        self.assertTrue(cached["ok"])
        self.assertEqual(cached["hits"][0]["end"], "2026-10-03T13:00:00+02:00")
        self.assertEqual(cached["hits"][0]["calendarId"], "cal-real")
        self.assertEqual(cached["hits"][0]["reference"], "event:opaque-fixture")
        self.assertTrue(cached["hits"][1]["allDay"])
        self.assertEqual(cached["hits"][1]["timeZone"], "America/New_York")

    def test_overlap_uses_instants_and_exclusive_end_not_lexical_offsets(self):
        self.build([page([event()])])
        overlap = calendar.cached_search("Fixture", 20, "2026-10-03T09:30:00Z", "2026-10-03T10:30:00Z")
        adjacent = calendar.cached_search("Fixture", 20, "2026-10-03T11:00:00Z", "2026-10-03T12:00:00Z")
        self.assertEqual(overlap["count"], 1)
        self.assertEqual(adjacent["count"], 0)
        outside = calendar.cached_search("Fixture", 20, "2026-10-02T00:00:00Z", "2026-10-04T00:00:00Z")
        self.assertEqual(outside["error"], "cache_window_miss")

    def test_all_day_dst_end_is_preserved(self):
        row = calendar._event(event(start="2026-03-08", end="2026-03-09", allDay=True, timeZone="America/New_York"), {"id": "cal-real", "name": "Shared name"})
        self.assertEqual(row[-1] - row[-2], 23 * 3600)
        self.assertEqual(row[4:6], ("2026-03-08", "2026-03-09"))

    def test_missing_end_is_not_invented_and_partial_cache_is_explicit(self):
        result, _ = self.build([page([event(end=None)])])
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "partial")
        cached = calendar.cached_search("Fixture", 20)
        self.assertFalse(cached["ok"])
        self.assertEqual(cached["error"], "cache_partial")
        self.assertFalse(cached["cacheComplete"])

    def test_empty_authorized_calendar_window_is_valid(self):
        result, _ = self.build([page([])])
        self.assertTrue(result["ok"])
        self.assertEqual(result["rows"], 0)
        self.assertTrue(calendar.cached_search("Fixture", 20)["ok"])

    def test_failed_refresh_retains_old_data_without_refreshing_timestamp(self):
        self.build([page([event()])])
        old = calendar.cache_status()["indexedAt"]
        with patch.object(calendar, "_run", return_value={"ok": True, "data": {"authorization": "notDetermined", "fullAccess": False}}) as run:
            result = calendar.build()
        self.assertFalse(result["ok"])
        self.assertEqual(run.call_count, 1)
        self.assertEqual(calendar.cache_status()["indexedAt"], old)
        cached = calendar.cached_search("Fixture", 20)
        self.assertEqual(cached["error"], "cache_stale")
        self.assertEqual(cached["count"], 1)

    def test_age_expiration_is_reported_even_when_saved_status_is_ok(self):
        self.build([page([event()])])
        with contextlib.closing(sqlite3.connect(self.path)) as con:
            con.execute("UPDATE meta SET value=? WHERE key='indexed_at'", ((datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),))
            con.commit()
        self.assertTrue(calendar.cached_search("Fixture", 20)["stale"])

    def test_duplicate_names_and_reused_uids_keep_calendar_identity(self):
        calendars = [{"id": "one", "title": "Shared name", "writable": True}, {"id": "two", "title": "Shared name", "writable": False}]
        result, _ = self.build([page([event(calendar_id="one")]), page([event(calendar_id="two")])], calendars)
        self.assertEqual(result["rows"], 2)
        self.assertEqual(calendar.cached_search("Fixture", 20, calendar_id="two")["hits"][0]["calendarId"], "two")

    def test_missing_pagination_metadata_cannot_claim_complete(self):
        result, _ = self.build([{"ok": True, "data": {"events": [event()]}}])
        self.assertEqual(result["status"], "partial")
        self.assertFalse(calendar.cached_search("Fixture", 20)["cacheComplete"])

    def test_changing_calendar_total_cannot_claim_complete(self):
        result, _ = self.build([page([event()], total=3), page([event("another")], offset=1, total=2)])
        self.assertFalse(result["ok"])
        self.assertEqual(result["failures"][0]["error"], "calendar_changed_during_index")

    def test_repeated_page_occurrence_cannot_claim_complete(self):
        result, _ = self.build([page([event()], total=2), page([event()], offset=1, total=2)])
        self.assertFalse(result["ok"])
        self.assertEqual(result["rows"], 1)

    def test_missing_backend_reports_without_calling_any_app(self):
        with patch.object(common, "which", return_value=None), patch.object(calendar, "_run", side_effect=AssertionError("no backend")):
            result = calendar.build()
        self.assertEqual(result["error"], "missing_cli")
        self.assertFalse(result["calledApp"])


class ReminderDryRunTests(unittest.TestCase):
    def test_mutating_dry_runs_never_select_or_execute_external_backend(self):
        for command, field in [("add", "title"), ("done", "id"), ("delete", "id")]:
            output = io.StringIO()
            with patch.object(sys, "argv", ["grok-reminders", command, "--" + field, "fixture", "--dry-run", "--json"]), patch.object(reminders, "binary", side_effect=AssertionError("no backend lookup")), patch.object(reminders.subprocess, "run", side_effect=AssertionError("no mutation")), contextlib.redirect_stdout(output):
                with self.assertRaises(SystemExit) as caught:
                    reminders.main()
            self.assertEqual(caught.exception.code, 0)
            payload = json.loads(output.getvalue())
            self.assertTrue(payload["dryRun"])
            self.assertFalse(payload["backendCalled"])
            self.assertIsNone(reminders.mapped(command, [], {"dry-run": [True], field: ["fixture"]}))

    def test_malformed_dry_run_flag_cannot_be_silently_dropped(self):
        with patch.object(sys, "argv", ["grok-reminders", "done", "--id", "fixture", "--dry-run=false"]), patch.object(reminders, "binary", side_effect=AssertionError("no backend")), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                reminders.main()
        self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
