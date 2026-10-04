import Foundation
import Testing

@testable import CalendarCore

struct CalendarTests {
  @Test func offsetDatesMatchUTC() throws {
    #expect(
      try CalendarLogic.parse("2026-10-03T09:00:00-04:00", zone: nil)
        == CalendarLogic.parse("2026-10-03T13:00:00Z", zone: nil))
  }
  @Test func invalidDatesCannotNormalize() {
    #expect(throws: CalendarError.self) {
      try CalendarLogic.parse("2026-02-30T09:00:00Z", zone: nil)
    }
    #expect(throws: CalendarError.self) {
      try CalendarLogic.parse("2026-02-30", zone: .current, dateOnly: true)
    }
    #expect(throws: CalendarError.self) {
      try CalendarLogic.parse("2026-09-28T09:00:00+04:99", zone: nil)
    }
  }
  @Test func localTimesNeedZone() {
    #expect(throws: CalendarError.self) { try CalendarLogic.parse("2026-10-03T09:00", zone: nil) }
  }
  @Test func dstGapAndRepeatedWallTimeRejected() {
    let zone = TimeZone(identifier: "America/New_York")!
    #expect(throws: CalendarError.self) {
      try CalendarLogic.parse("2026-03-08T02:30:00", zone: zone)
    }
    #expect(throws: CalendarError.self) {
      try CalendarLogic.parse("2026-11-01T01:30:00", zone: zone)
    }
  }
  @Test func repeatedExplicitOffsetIsAccepted() throws {
    let a = try CalendarLogic.parse("2026-11-01T01:30:00-04:00", zone: nil)
    let b = try CalendarLogic.parse("2026-11-01T01:30:00-05:00", zone: nil)
    #expect(b.timeIntervalSince(a) == 3600)
  }
  @Test func allDayUsesCalendarDaysAcrossDST() throws {
    let zone = TimeZone(identifier: "America/New_York")!
    let a = try CalendarLogic.parse("2026-03-08", zone: zone, dateOnly: true)
    let b = try CalendarLogic.parse("2026-03-09", zone: zone, dateOnly: true)
    #expect(b.timeIntervalSince(a) == 23 * 3600)
  }
  @Test func integersRejectBooleansFractionsAndOverflow() {
    for value: Any in [true, 1.5, -1, Double.infinity, Double(Int.max)] {
      #expect(throws: CalendarError.self) {
        try CalendarLogic.integer(value, name: "count", minimum: 1)
      }
    }
  }
  @Test func availabilityMergesAndClipsBusyIntervals() {
    let start = Date(timeIntervalSince1970: 0)
    let end = Date(timeIntervalSince1970: 600)
    let busy = [
      DateInterval(start: start.addingTimeInterval(-30), end: start.addingTimeInterval(60)),
      DateInterval(start: start.addingTimeInterval(120), end: start.addingTimeInterval(240)),
      DateInterval(start: start.addingTimeInterval(180), end: start.addingTimeInterval(300)),
    ]
    #expect(
      CalendarLogic.free(start: start, end: end, busy: busy, minimum: 100) == [
        DateInterval(start: start.addingTimeInterval(300), end: end)
      ])
  }
  @Test func referenceRetainsCalendarAndOccurrence() throws {
    let ref = EventReference(
      id: "id+/", calendarId: "work", itemId: "item", occurrence: "2026-10-03T09:00:00Z",
      start: "2026-10-03T09:30:00Z")
    let decoded = try EventReference.decode(ref.encode())
    #expect(decoded.id == ref.id)
    #expect(decoded.calendarId == ref.calendarId)
    #expect(decoded.occurrence == ref.occurrence)
    #expect(decoded.start == ref.start)
    #expect(throws: CalendarError.self) { try EventReference.decode("event:garbage!") }
  }
  private var snapshot: [String: Any] {
    [
      "title": "Focus", "start": "2026-09-28T09:00:00Z", "end": "2026-09-28T10:00:00Z",
      "allDay": false, "calendarId": "work", "timeZone": "Etc/UTC", "notes": "a\nb",
      "location": NSNull(), "availability": "busy", "recurring": false,
      "alarms": [["minutesBefore": 15]], "recurrenceRules": [],
    ]
  }
  @Test func readbackDetectsLostChanges() {
    let expected = snapshot
    var actual = expected
    actual["title"] = "Wrong"
    actual["calendarId"] = "personal"
    actual["end"] = "2026-09-28T11:00:00Z"
    #expect(
      CalendarVerification.mismatches(
        expected, actual, fields: ["title", "calendarId", "start", "end"]) == [
          "calendarId", "end", "title",
        ])
  }
  @Test func readbackNormalizesTextAndEquivalentDates() {
    let expected = snapshot
    var actual = expected
    actual["notes"] = "a\r\nb"
    actual["location"] = ""
    actual["start"] = "2026-09-28T05:00:00.125-04:00"
    #expect(
      CalendarVerification.mismatches(expected, actual, fields: ["start", "notes", "location"])
        .isEmpty)
  }
  @Test func alarmsCompareMeaningWithoutOrdering() {
    var expected = snapshot
    expected["alarms"] = [["minutesBefore": 5], ["minutesBefore": 15]]
    var actual = expected
    actual["alarms"] = [["at": "2026-09-28T08:45:00Z"], ["at": "2026-09-28T08:55:00Z"]]
    #expect(CalendarVerification.mismatches(expected, actual, fields: ["alarms"]).isEmpty)
    expected["recurring"] = true
    actual["recurring"] = true
    #expect(CalendarVerification.mismatches(expected, actual, fields: ["alarms"]) == ["alarms"])
  }
  @Test func recurrenceDefaultsNormalizeAndCountStillMatters() {
    var expected = snapshot
    expected["recurrenceRules"] = [["frequency": "weekly", "interval": 1, "count": 5]]
    var actual = expected
    actual["recurrenceRules"] = [
      [
        "frequency": "weekly", "interval": 1, "count": 5,
        "weekdays": [["day": 2, "weekNumber": 0]],
      ]
    ]
    #expect(CalendarVerification.mismatches(expected, actual, fields: ["recurrence"]).isEmpty)
    actual["recurrenceRules"] = [["frequency": "weekly", "interval": 1, "count": 4]]
    #expect(
      CalendarVerification.mismatches(expected, actual, fields: ["recurrence"]) == ["recurrence"])
  }
  @Test func differentTimeZonesRemainDistinct() {
    var expected = snapshot
    expected["timeZone"] = "America/New_York"
    var actual = expected
    actual["timeZone"] = "America/Chicago"
    #expect(CalendarVerification.mismatches(expected, actual, fields: ["timeZone"]) == ["timeZone"])
  }
}
