import CoreFoundation
import EventKit
import Foundation

public final class CalendarService {
  private lazy var store = EKEventStore()
  public init() {}
  public static func authorization() -> [String: Any] {
    let status = EKEventStore.authorizationStatus(for: .event)
    let name: String
    switch status {
    case .notDetermined: name = "notDetermined"
    case .restricted: name = "restricted"
    case .denied: name = "denied"
    case .fullAccess: name = "fullAccess"
    case .writeOnly: name = "writeOnly"
    @unknown default: name = "unknown"
    }
    return [
      "backend": "eventkit", "authorization": name, "fullAccess": status == .fullAccess,
      "prompts": false, "timeZone": TimeZone.current.identifier,
      "permissionCommand": "grok-calendar permissions request",
      "settings": "System Settings > Privacy & Security > Calendars",
    ]
  }
  public func run(_ request: [String: Any]) throws -> [String: Any] {
    guard let action = request["action"] as? String else {
      throw CalendarError("INVALID_INPUT", "A request action is required.")
    }
    if request["options"] != nil && !(request["options"] is [String: Any]) {
      throw CalendarError("INVALID_INPUT", "options must be an object.")
    }
    let options = request["options"] as? [String: Any] ?? [:]
    if action == "mail-permission-status" { return try MailPermission.check(request: false) }
    if action == "mail-permission-request" { return try MailPermission.check(request: true) }
    if action == "doctor" || action == "auth-status" { return Self.authorization() }
    if action == "permissions" { return try permission() }
    guard
      ["calendars", "events", "free", "read", "create", "validate-create", "update", "delete"]
        .contains(action)
    else { throw CalendarError("INVALID_INPUT", "Unknown native calendar action.") }
    guard EKEventStore.authorizationStatus(for: .event) == .fullAccess else {
      throw CalendarError(
        "PERMISSION_REQUIRED",
        "Calendar full access is required. Run grok-calendar permissions request explicitly.",
        details: Self.authorization())
    }
    switch action {
    case "calendars":
      let calendars = store.calendars(for: .event).map(calendarJSON).sorted {
        ($0["id"] as! String) < ($1["id"] as! String)
      }
      return ["calendars": calendars, "count": calendars.count, "source": "eventkit"]
    case "events", "free": return try query(action, options)
    case "read":
      return [
        "event": eventJSON(
          try resolve(request["target"] as? String, options: options, writing: false))
      ]
    case "create", "validate-create", "update":
      return try save(action, request: request, options: options)
    case "delete": return try delete(request["target"] as? String, options: options)
    default: throw CalendarError("INVALID_INPUT", "Unknown native calendar action.")
    }
  }
  private func permission() throws -> [String: Any] {
    if EKEventStore.authorizationStatus(for: .event) == .fullAccess { return Self.authorization() }
    let lock = NSLock()
    var result: (Bool, Error?)?
    store.requestFullAccessToEvents { granted, error in
      lock.lock()
      result = (granted, error)
      lock.unlock()
    }
    let deadline = Date().addingTimeInterval(90)
    while Date() < deadline {
      lock.lock()
      let response = result
      lock.unlock()
      if let response {
        guard response.0 else {
          throw CalendarError(
            "PERMISSION_REQUIRED",
            response.1?.localizedDescription ?? "Calendar access was not granted.",
            details: Self.authorization())
        }
        return Self.authorization()
      }
      RunLoop.current.run(until: Date().addingTimeInterval(0.05))
    }
    throw CalendarError(
      "TIMEOUT",
      "Calendar permission request timed out. Check the macOS permission dialog or System Settings."
    )
  }
  private func calendarJSON(_ c: EKCalendar) -> [String: Any] {
    [
      "id": c.calendarIdentifier, "title": c.title, "name": c.title,
      "writable": c.allowsContentModifications, "sourceId": c.source?.sourceIdentifier ?? "",
      "sourceTitle": c.source?.title ?? "", "subscribed": c.isSubscribed,
    ]
  }
  private func calendar(id: String?, name: String?, writable: Bool = false) throws -> EKCalendar {
    let matches: [EKCalendar]
    if let id {
      matches = store.calendar(withIdentifier: id).map { [$0] } ?? []
    } else if let name {
      matches = store.calendars(for: .event).filter { $0.title == name }
    } else {
      throw CalendarError("INVALID_INPUT", "Specify an exact calendar ID or unique calendar name.")
    }
    guard matches.count == 1, let result = matches.first, result.allowedEntityTypes.contains(.event)
    else {
      throw CalendarError(
        matches.count > 1 ? "AMBIGUOUS_CALENDAR" : "NOT_FOUND",
        "Calendar did not resolve uniquely. Run calendars and use --calendar-id.")
    }
    if writable && !result.allowsContentModifications {
      throw CalendarError("READ_ONLY_CALENDAR", "This calendar does not permit event changes.")
    }
    return result
  }
  private func query(_ action: String, _ options: [String: Any]) throws -> [String: Any] {
    guard let from = options["from"] as? String, let to = options["to"] as? String else {
      throw CalendarError("INVALID_INPUT", "Calendar queries require from and to.")
    }
    let zone = try CalendarLogic.zone(options["timeZone"] as? String)
    let start = try CalendarLogic.parse(from, zone: zone)
    let end = try CalendarLogic.parse(to, zone: zone)
    guard end > start, end.timeIntervalSince(start) <= 366 * 86400 + 3600 else {
      throw CalendarError("INVALID_INPUT", "Query range must be positive and at most 366 days.")
    }
    let limit = try CalendarLogic.integer(
      options["limit"] ?? 100, name: "limit", minimum: 1, maximum: 1000)
    let offset = try CalendarLogic.integer(
      options["offset"] ?? 0, name: "offset", maximum: 10_000_000)
    let selected =
      options["calendarId"] != nil || options["calendar"] != nil
      ? [try calendar(id: options["calendarId"] as? String, name: options["calendar"] as? String)]
      : store.calendars(for: .event)
    var events =
      selected.isEmpty
      ? []
      : store.events(
        matching: store.predicateForEvents(withStart: start, end: end, calendars: selected))
    events = events.filter {
      $0.startDate != nil && $0.endDate != nil && $0.startDate < end && $0.endDate > start
        && $0.endDate >= $0.startDate
    }
    if let query = options["query"] as? String, !query.isEmpty {
      events = events.filter { ($0.title ?? "").localizedCaseInsensitiveContains(query) }
    }
    if let title = options["exactTitle"] as? String { events = events.filter { $0.title == title } }
    events.sort {
      $0.startDate == $1.startDate
        ? ($0.eventIdentifier ?? "") < ($1.eventIdentifier ?? "") : $0.startDate < $1.startDate
    }
    var data: [String: Any] = [
      "from": CalendarLogic.iso(start), "to": CalendarLogic.iso(end), "source": "eventkit",
      "offset": offset, "limit": limit, "calendarIds": selected.map(\.calendarIdentifier),
    ]
    if action == "free" {
      guard let minutes = options["durationMinutes"] as? NSNumber,
        CFGetTypeID(minutes) != CFBooleanGetTypeID(), minutes.doubleValue.isFinite,
        minutes.doubleValue > 0
      else { throw CalendarError("INVALID_INPUT", "durationMinutes must be positive.") }
      let busy = events.filter { $0.availability != .free && $0.status != .canceled }.map {
        DateInterval(start: $0.startDate, end: $0.endDate)
      }
      let free = CalendarLogic.free(
        start: start, end: end, busy: busy, minimum: minutes.doubleValue * 60)
      let page = Array(free.dropFirst(offset).prefix(limit))
      data["intervals"] = page.map {
        [
          "start": CalendarLogic.iso($0.start), "end": CalendarLogic.iso($0.end),
          "minutes": $0.duration / 60,
        ] as [String: Any]
      }
      data["total"] = free.count
      data["count"] = page.count
      data["truncated"] = free.count > offset + page.count
      data["basis"] =
        "Visible local calendar events; free and canceled events do not block time. No working-hours or other people's availability is inferred."
    } else {
      let page = Array(events.dropFirst(offset).prefix(limit))
      data["events"] = page.map { eventJSON($0, light: options["light"] as? Bool == true) }
      data["total"] = events.count
      data["count"] = page.count
      data["truncated"] = events.count > offset + page.count
    }
    return data
  }
  private func recurring(_ event: EKEvent) -> Bool { event.hasRecurrenceRules || event.isDetached }
  private func resolve(_ target: String?, options: [String: Any], writing: Bool) throws -> EKEvent {
    guard let target else {
      throw CalendarError("INVALID_INPUT", "An event ID or reference is required.")
    }
    let ref = try EventReference.decode(target)
    guard let base = store.event(withIdentifier: ref.id) else {
      throw CalendarError("STALE_REFERENCE", "Event ID no longer resolves. Query events again.")
    }
    var expectedCalendar = ref.calendarId
    if options["calendarId"] != nil || options["calendar"] != nil {
      let supplied = try calendar(
        id: options["calendarId"] as? String, name: options["calendar"] as? String
      ).calendarIdentifier
      if let expectedCalendar, supplied != expectedCalendar {
        throw CalendarError(
          "STALE_REFERENCE", "Calendar option conflicts with the event reference.")
      }
      expectedCalendar = supplied
    }
    if let expectedCalendar, base.calendar.calendarIdentifier != expectedCalendar {
      throw CalendarError("STALE_REFERENCE", "The event's calendar changed.")
    }
    let savedOccurrence = try ref.occurrence.map { try CalendarLogic.parse($0, zone: nil) }
    let suppliedOccurrence = try (options["occurrence"] as? String).map {
      try CalendarLogic.parse($0, zone: try CalendarLogic.zone(options["timeZone"] as? String))
    }
    if let a = savedOccurrence, let b = suppliedOccurrence, abs(a.timeIntervalSince(b)) >= 0.5 {
      throw CalendarError(
        "STALE_REFERENCE", "Occurrence option conflicts with the event reference.")
    }
    let occurrence = suppliedOccurrence ?? savedOccurrence
    if writing && recurring(base) && (occurrence == nil || options["scope"] == nil) {
      throw CalendarError(
        "INVALID_INPUT",
        "Recurring edits require occurrence context and explicit --scope this|future.")
    }
    var event = base
    if let occurrence,
      abs((base.occurrenceDate ?? base.startDate!).timeIntervalSince(occurrence)) >= 0.5
    {
      var windows = [
        DateInterval(
          start: occurrence.addingTimeInterval(-86400),
          end: occurrence.addingTimeInterval(2 * 86400))
      ]
      if let s = ref.start {
        let d = try CalendarLogic.parse(s, zone: nil)
        windows.append(DateInterval(start: d.addingTimeInterval(-1), end: d.addingTimeInterval(1)))
      }
      var matches: [EKEvent] = []
      for window in windows {
        for candidate in store.events(
          matching: store.predicateForEvents(
            withStart: window.start, end: window.end, calendars: [base.calendar]))
        where candidate.eventIdentifier == ref.id
          || candidate.calendarItemIdentifier == base.calendarItemIdentifier
        {
          if abs((candidate.occurrenceDate ?? candidate.startDate!).timeIntervalSince(occurrence))
            < 0.5
            && !matches.contains(where: {
              $0.eventIdentifier == candidate.eventIdentifier && $0.startDate == candidate.startDate
            })
          {
            matches.append(candidate)
          }
        }
      }
      guard matches.count == 1 else {
        throw CalendarError(
          matches.isEmpty ? "STALE_REFERENCE" : "AMBIGUOUS_REFERENCE",
          "The occurrence did not resolve uniquely. Query events again.")
      }
      event = matches[0]
    }
    if let item = ref.itemId, event.calendarItemIdentifier != item {
      throw CalendarError("STALE_REFERENCE", "The calendar item identity changed.")
    }
    if writing, let original = ref.start,
      abs(event.startDate.timeIntervalSince(try CalendarLogic.parse(original, zone: nil))) >= 0.5
    {
      throw CalendarError(
        "STALE_REFERENCE", "The event start changed. Read it again before editing.")
    }
    if writing {
      _ = try calendar(id: event.calendar.calendarIdentifier, name: nil, writable: true)
    }
    return event
  }
  private func span(_ options: [String: Any], _ event: EKEvent) throws -> EKSpan {
    let scope = options["scope"] as? String
    if let scope, !["this", "future"].contains(scope) {
      throw CalendarError("INVALID_INPUT", "scope must be this or future.")
    }
    if recurring(event) && scope == nil {
      throw CalendarError("INVALID_INPUT", "Recurring writes require --scope this|future.")
    }
    return scope == "future" ? .futureEvents : .thisEvent
  }
  private func save(_ action: String, request: [String: Any], options: [String: Any]) throws
    -> [String: Any]
  {
    guard let input = request["input"] as? [String: Any], !input.isEmpty else {
      throw CalendarError("INVALID_INPUT", "An event input object is required.")
    }
    let creating = action != "update"
    let event =
      try creating
      ? EKEvent(eventStore: store)
      : resolve(request["target"] as? String, options: options, writing: true)
    let scope = creating ? EKSpan.thisEvent : try span(options, event)
    try apply(input, event: event, creating: creating, options: options)
    let intended = eventJSON(event)
    if action == "validate-create" {
      return ["validated": true, "event": intended, "calendarVerified": true]
    }
    do { try store.save(event, span: scope, commit: true) } catch {
      throw CalendarError(
        "WRITE_STATUS_UNKNOWN",
        "Calendar save failed or is uncertain: \(error.localizedDescription). Re-query before retrying.",
        details: ["writeMayHaveTakenEffect": true, "readOnly": false]
      )
    }
    let id = event.eventIdentifier ?? ""
    let item = event.calendarItemIdentifier
    let calendarId = event.calendar.calendarIdentifier
    let start = event.startDate!
    store.reset()
    let candidates = try reread(id: id, item: item, calendarId: calendarId, start: start)
    guard candidates.count == 1 else {
      throw CalendarError(
        "WRITE_STATUS_UNKNOWN",
        "Save was accepted but event readback was ambiguous or unavailable.",
        details: ["eventId": id, "writeMayHaveTakenEffect": true, "readOnly": false])
    }
    let observed = eventJSON(candidates[0])
    var fields = Set(input.keys).union(["start", "end", "allDay", "calendarId"])
    if creating { fields.insert("recurrence") }
    if intended["allDay"] as? Bool == true { fields.remove("timeZone") }
    let differences = CalendarVerification.mismatches(intended, observed, fields: fields)
    guard differences.isEmpty else {
      throw CalendarError(
        "VERIFICATION_FAILED",
        "Saved event differs from requested fields. Inspect it before retrying.",
        details: [
          "mismatchedFields": differences, "event": observed, "writeMayHaveTakenEffect": true,
          "readOnly": false,
        ])
    }
    return [
      "event": observed, "created": creating, "updated": !creating,
      "scope": options["scope"] ?? "this",
      "verification":
        "Requested fields matched independent local EventKit readback; remote synchronization is not verified.",
    ]
  }
  private func reread(id: String, item: String, calendarId: String, start: Date) throws -> [EKEvent]
  {
    guard let c = store.calendar(withIdentifier: calendarId) else {
      throw CalendarError(
        "WRITE_STATUS_UNKNOWN", "Calendar became unavailable during verification.",
        details: ["writeMayHaveTakenEffect": true, "readOnly": false])
    }
    return store.events(
      matching: store.predicateForEvents(
        withStart: start.addingTimeInterval(-1), end: start.addingTimeInterval(1), calendars: [c])
    ).filter {
      ($0.eventIdentifier == id || $0.calendarItemIdentifier == item)
        && abs($0.startDate.timeIntervalSince(start)) < 1
    }
  }
  private func delete(_ target: String?, options: [String: Any]) throws -> [String: Any] {
    let event = try resolve(target, options: options, writing: true)
    let scope = try span(options, event)
    let before = eventJSON(event)
    let id = event.eventIdentifier ?? ""
    let item = event.calendarItemIdentifier
    let cal = event.calendar.calendarIdentifier
    let start = event.startDate!
    let repeating = recurring(event)
    do { try store.remove(event, span: scope, commit: true) } catch {
      throw CalendarError(
        "WRITE_STATUS_UNKNOWN",
        "Deletion failed or is uncertain: \(error.localizedDescription). Re-query before retrying.",
        details: ["writeMayHaveTakenEffect": true, "readOnly": false])
    }
    store.reset()
    guard try reread(id: id, item: item, calendarId: cal, start: start).isEmpty,
      repeating || store.event(withIdentifier: id) == nil
    else {
      throw CalendarError(
        "VERIFICATION_FAILED", "The event remains visible after deletion.",
        details: ["writeMayHaveTakenEffect": true, "readOnly": false])
    }
    return [
      "deleted": true, "event": before, "scope": options["scope"] ?? "this",
      "verification":
        "Targeted occurrence absent from local store; remote synchronization not verified.",
    ]
  }
  private func apply(_ input: [String: Any], event: EKEvent, creating: Bool, options: [String: Any])
    throws
  {
    let allowed: Set<String> = [
      "calendarId", "title", "start", "end", "allDay", "timeZone", "location", "notes", "url",
      "availability", "alarms", "recurrence",
    ]
    guard Set(input.keys).isSubset(of: allowed) else {
      throw CalendarError(
        "INVALID_INPUT", "Unsupported event fields. Attendee and RSVP writes are unsupported.")
    }
    if input["calendarId"] != nil && !(input["calendarId"] is String) {
      throw CalendarError("INVALID_INPUT", "calendarId must be a string.")
    }
    if creating {
      for key in ["title", "start", "end"] where input[key] == nil {
        throw CalendarError("INVALID_INPUT", "Creation requires \(key).")
      }
      event.calendar = try calendar(
        id: input["calendarId"] as? String ?? options["calendarId"] as? String,
        name: options["calendar"] as? String, writable: true)
    } else if let value = input["calendarId"] {
      guard let id = value as? String else {
        throw CalendarError("INVALID_INPUT", "calendarId must be a string.")
      }
      event.calendar = try calendar(id: id, name: nil, writable: true)
    }
    if let value = input["title"] {
      guard let title = value as? String,
        !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
      else { throw CalendarError("INVALID_INPUT", "title must be nonempty.") }
      event.title = title
    }
    let previousAllDay = event.isAllDay
    if let value = input["allDay"] {
      guard let n = value as? NSNumber, CFGetTypeID(n) == CFBooleanGetTypeID() else {
        throw CalendarError("INVALID_INPUT", "allDay must be boolean.")
      }
      event.isAllDay = n.boolValue
    }
    if !creating && previousAllDay != event.isAllDay
      && (input["start"] == nil || input["end"] == nil)
    {
      throw CalendarError("INVALID_INPUT", "Changing allDay requires start and end.")
    }
    if input["timeZone"] != nil && !(input["timeZone"] is String) {
      throw CalendarError("INVALID_INPUT", "timeZone must be an IANA name.")
    }
    let requestedZone =
      try CalendarLogic.zone(input["timeZone"] as? String ?? options["timeZone"] as? String)
      ?? (creating ? nil : event.timeZone)
      ?? (input["start"] as? String).flatMap(CalendarLogic.offsetZone)
    let zone = event.isAllDay ? TimeZone.current : requestedZone
    event.timeZone = event.isAllDay ? nil : zone
    for key in ["start", "end"] where input[key] != nil {
      guard let text = input[key] as? String else {
        throw CalendarError("INVALID_INPUT", "\(key) must be a string.")
      }
      let date = try CalendarLogic.parse(
        text, zone: event.isAllDay ? .current : zone, dateOnly: event.isAllDay)
      if key == "start" { event.startDate = date } else { event.endDate = date }
    }
    guard let start = event.startDate, let end = event.endDate, end > start else {
      throw CalendarError("INVALID_INPUT", "end must follow start; all-day end is exclusive.")
    }
    for key in ["notes", "location", "url"] where input[key] != nil {
      guard input[key] is String || input[key] is NSNull else {
        throw CalendarError("INVALID_INPUT", "\(key) must be a string or null.")
      }
      let value = input[key] as? String
      if key == "notes" {
        event.notes = value
      } else if key == "location" {
        event.location = value
      } else if let value {
        guard let url = URL(string: value), url.scheme != nil else {
          throw CalendarError("INVALID_INPUT", "url must be absolute.")
        }
        event.url = url
      } else {
        event.url = nil
      }
    }
    if let value = input["availability"] {
      guard let value = value as? String,
        let availability = [
          "busy": EKEventAvailability.busy, "free": .free, "tentative": .tentative,
          "unavailable": .unavailable,
        ][value]
      else { throw CalendarError("INVALID_INPUT", "Invalid availability.") }
      let mask: EKCalendarEventAvailabilityMask = [.busy, .free, .tentative, .unavailable][
        availability.rawValue]
      guard event.calendar.supportedEventAvailabilities.contains(mask) else {
        throw CalendarError("INVALID_INPUT", "Calendar does not support requested availability.")
      }
      event.availability = availability
    }
    if let value = input["alarms"] {
      guard let alarms = value as? [[String: Any]], alarms.count <= 20 else {
        throw CalendarError("INVALID_INPUT", "alarms must be an array of at most 20 objects.")
      }
      event.alarms = try alarms.map { alarm in
        guard alarm.count == 1 else {
          throw CalendarError("INVALID_INPUT", "Alarm requires exactly minutesBefore or at.")
        }
        if let minutes = alarm["minutesBefore"] {
          return EKAlarm(
            relativeOffset: -Double(
              try CalendarLogic.integer(minutes, name: "minutesBefore", maximum: 525600)) * 60)
        }
        if let at = alarm["at"] as? String {
          return EKAlarm(absoluteDate: try CalendarLogic.parse(at, zone: zone))
        }
        throw CalendarError("INVALID_INPUT", "Invalid alarm.")
      }
    }
    if let value = input["recurrence"] {
      if value is NSNull {
        event.recurrenceRules = nil
      } else {
        guard let value = value as? [String: Any] else {
          throw CalendarError("INVALID_INPUT", "recurrence must be an object or null.")
        }
        event.recurrenceRules = [
          try rule(value, zone: zone ?? (event.isAllDay ? .current : nil), start: start)
        ]
      }
    }
  }
  private func rule(_ value: [String: Any], zone: TimeZone?, start: Date) throws -> EKRecurrenceRule
  {
    guard Set(value.keys).isSubset(of: ["frequency", "interval", "count", "until", "weekdays"]),
      let name = value["frequency"] as? String,
      let frequency = [
        "daily": EKRecurrenceFrequency.daily, "weekly": .weekly, "monthly": .monthly,
        "yearly": .yearly,
      ][name]
    else { throw CalendarError("INVALID_INPUT", "Invalid recurrence frequency or fields.") }
    let interval = try CalendarLogic.integer(
      value["interval"] ?? 1, name: "interval", minimum: 1, maximum: 1000)
    guard !(value["count"] != nil && value["until"] != nil) else {
      throw CalendarError("INVALID_INPUT", "Use recurrence count or until, not both.")
    }
    var end: EKRecurrenceEnd?
    if let count = value["count"] {
      end = EKRecurrenceEnd(
        occurrenceCount: try CalendarLogic.integer(count, name: "count", minimum: 1))
    }
    if let until = value["until"] {
      guard let until = until as? String else {
        throw CalendarError("INVALID_INPUT", "until must be a date.")
      }
      let date = try CalendarLogic.parse(until, zone: zone)
      guard date >= start else {
        throw CalendarError("INVALID_INPUT", "Recurrence end precedes event start.")
      }
      end = EKRecurrenceEnd(end: date)
    }
    var weekdays: [EKRecurrenceDayOfWeek]?
    if let values = value["weekdays"] {
      guard frequency != .daily, let list = values as? [Any], !list.isEmpty, list.count <= 7 else {
        throw CalendarError(
          "INVALID_INPUT", "weekdays must be 1...7 (Sunday=1), except for daily recurrence.")
      }
      let days = try list.map {
        try CalendarLogic.integer($0, name: "weekday", minimum: 1, maximum: 7)
      }
      guard Set(days).count == days.count else {
        throw CalendarError("INVALID_INPUT", "Duplicate recurrence weekdays.")
      }
      weekdays = days.map { EKRecurrenceDayOfWeek(EKWeekday(rawValue: $0)!) }
    }
    return EKRecurrenceRule(
      recurrenceWith: frequency, interval: interval, daysOfTheWeek: weekdays, daysOfTheMonth: nil,
      monthsOfTheYear: nil, weeksOfTheYear: nil, daysOfTheYear: nil, setPositions: nil, end: end)
  }
  private func eventJSON(_ e: EKEvent, light: Bool = false) -> [String: Any] {
    let repeating = recurring(e)
    let occurrence = repeating ? e.occurrenceDate.map(CalendarLogic.iso) : nil
    let ref = EventReference(
      id: e.eventIdentifier ?? "", calendarId: e.calendar?.calendarIdentifier,
      itemId: e.calendarItemIdentifier, occurrence: occurrence,
      start: e.startDate.map(CalendarLogic.iso))
    let zone = e.isAllDay ? TimeZone.current : e.timeZone ?? .current
    var result: [String: Any] = [
      "id": ref.id, "uid": ref.id, "calendarItemId": e.calendarItemIdentifier,
      "calendarId": e.calendar?.calendarIdentifier ?? "", "calendar": e.calendar?.title ?? "",
      "writable": e.calendar?.allowsContentModifications ?? false, "title": e.title ?? "",
      "allDay": e.isAllDay, "recurring": repeating, "detached": e.isDetached,
      "occurrence": occurrence as Any? ?? NSNull(), "timeZone": zone.identifier,
      "floatingTime": e.timeZone == nil,
      "availability": [
        EKEventAvailability.busy: "busy", .free: "free", .tentative: "tentative",
        .unavailable: "unavailable",
      ][e.availability] ?? "notSupported",
      "status": e.status == .canceled
        ? "canceled"
        : (e.status == .confirmed ? "confirmed" : e.status == .tentative ? "tentative" : "none"),
    ]
    if !ref.id.isEmpty { result["reference"] = ref.encode() }
    if let start = e.startDate {
      result["start"] =
        e.isAllDay ? CalendarLogic.day(start, zone: .current) : CalendarLogic.iso(start)
    }
    if let end = e.endDate {
      result["end"] = e.isAllDay ? CalendarLogic.day(end, zone: .current) : CalendarLogic.iso(end)
    }
    if e.isAllDay { result["allDayEndExclusive"] = true }
    if light { return result }
    result["notes"] = e.notes as Any? ?? NSNull()
    result["location"] = e.location as Any? ?? NSNull()
    result["url"] = e.url?.absoluteString as Any? ?? NSNull()
    result["alarms"] = (e.alarms ?? []).map { alarm -> [String: Any] in
      if let at = alarm.absoluteDate { return ["at": CalendarLogic.iso(at)] }
      return ["minutesBefore": -alarm.relativeOffset / 60]
    }
    result["recurrenceRules"] = (e.recurrenceRules ?? []).map { r -> [String: Any] in
      var value: [String: Any] = [
        "frequency": [
          EKRecurrenceFrequency.daily: "daily", .weekly: "weekly", .monthly: "monthly",
          .yearly: "yearly",
        ][r.frequency] ?? "unknown", "interval": r.interval,
      ]
      if let end = r.recurrenceEnd {
        if let date = end.endDate {
          value["until"] = CalendarLogic.iso(date)
        } else {
          value["count"] = end.occurrenceCount
        }
      }
      if let days = r.daysOfTheWeek {
        value["weekdays"] = days.map {
          ["day": $0.dayOfTheWeek.rawValue, "weekNumber": $0.weekNumber]
        }
      }
      for (key, numbers) in [
        ("monthDays", r.daysOfTheMonth), ("months", r.monthsOfTheYear),
        ("yearDays", r.daysOfTheYear), ("yearWeeks", r.weeksOfTheYear),
        ("setPositions", r.setPositions),
      ] { if let numbers { value[key] = numbers } }
      return value
    }
    result["attendees"] = (e.attendees ?? []).map {
      [
        "name": $0.name as Any? ?? NSNull(), "url": $0.url.absoluteString,
        "isCurrentUser": $0.isCurrentUser, "status": $0.participantStatus.rawValue,
        "readOnly": true,
      ] as [String: Any]
    }
    return result
  }
}
