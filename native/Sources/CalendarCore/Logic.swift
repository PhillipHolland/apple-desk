import CoreFoundation
import Foundation

public struct CalendarError: Error {
  public let code: String, message: String
  public let details: [String: Any]?
  public init(_ code: String, _ message: String, details: [String: Any]? = nil) {
    self.code = code
    self.message = message
    self.details = details
  }
}
public enum CalendarLogic {
  public static func zone(_ name: String?) throws -> TimeZone? {
    guard let name else { return nil }
    guard let zone = TimeZone(identifier: name) else {
      throw CalendarError("INVALID_INPUT", "Unknown IANA time zone: \(name).")
    }
    return zone
  }
  public static func iso(_ date: Date) -> String {
    let f = ISO8601DateFormatter()
    f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    return f.string(from: date)
  }
  public static func day(_ date: Date, zone: TimeZone) -> String {
    let f = DateFormatter()
    f.locale = Locale(identifier: "en_US_POSIX")
    f.calendar = Calendar(identifier: .gregorian)
    f.timeZone = zone
    f.dateFormat = "yyyy-MM-dd"
    return f.string(from: date)
  }
  public static func offsetZone(_ value: String) -> TimeZone? {
    if value.hasSuffix("Z") { return TimeZone(secondsFromGMT: 0) }
    guard value.range(of: #"[+-]\d{2}:\d{2}$"#, options: .regularExpression) != nil else {
      return nil
    }
    let s = String(value.suffix(6))
    guard let h = Int(s.dropFirst().prefix(2)), let m = Int(s.suffix(2)), h <= 23, m <= 59 else {
      return nil
    }
    return TimeZone(secondsFromGMT: (h * 3600 + m * 60) * (s.hasPrefix("-") ? -1 : 1))
  }
  public static func parse(_ value: String, zone: TimeZone?, dateOnly: Bool = false) throws -> Date
  {
    if !dateOnly, let fixed = offsetZone(value),
      value.range(
        of: #"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?(Z|[+-]\d{2}:\d{2})$"#,
        options: .regularExpression) != nil
    {
      let f = ISO8601DateFormatter()
      f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
      var date = f.date(from: value)
      f.formatOptions = [.withInternetDateTime]
      date = date ?? f.date(from: value)
      if let date {
        let round = DateFormatter()
        round.locale = Locale(identifier: "en_US_POSIX")
        round.calendar = Calendar(identifier: .gregorian)
        round.timeZone = fixed
        round.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        if round.string(from: date) == String(value.prefix(19)) { return date }
      }
      throw CalendarError("INVALID_INPUT", "Invalid ISO 8601 date: \(value).")
    }
    let pattern =
      dateOnly
      ? #"^(\d{4})-(\d{2})-(\d{2})$"#
      : #"^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2})(?::(\d{2}))?)?$"#
    let regex = try NSRegularExpression(pattern: pattern)
    guard let match = regex.firstMatch(in: value, range: NSRange(value.startIndex..., in: value)),
      let zone
    else {
      throw CalendarError(
        "INVALID_INPUT",
        "Use an ISO timestamp with offset, or an explicit timeZone for local times. All-day dates must be YYYY-MM-DD."
      )
    }
    func p(_ n: Int) -> Int {
      guard n < match.numberOfRanges, let range = Range(match.range(at: n), in: value) else {
        return 0
      }
      return Int(value[range]) ?? 0
    }
    var calendar = Calendar(identifier: .gregorian)
    calendar.timeZone = zone
    let c = DateComponents(
      year: p(1), month: p(2), day: p(3), hour: p(4), minute: p(5), second: p(6))
    guard let date = calendar.date(from: c),
      calendar.dateComponents([.year, .month, .day, .hour, .minute, .second], from: date) == c
    else { throw CalendarError("INVALID_INPUT", "Invalid or nonexistent local time: \(value).") }
    if !dateOnly && match.numberOfRanges > 4 && match.range(at: 4).location != NSNotFound {
      let start = calendar.startOfDay(for: date).addingTimeInterval(-1)
      let time = DateComponents(hour: p(4), minute: p(5), second: p(6))
      if calendar.nextDate(
        after: start, matching: time, matchingPolicy: .strict, repeatedTimePolicy: .first)
        != calendar.nextDate(
          after: start, matching: time, matchingPolicy: .strict, repeatedTimePolicy: .last)
      {
        throw CalendarError(
          "AMBIGUOUS_TIME", "This local time occurs twice; supply an explicit UTC offset.")
      }
    }
    return date
  }
  public static func integer(_ value: Any?, name: String, minimum: Int = 0, maximum: Int = 100000)
    throws -> Int
  {
    guard let n = value as? NSNumber, CFGetTypeID(n) != CFBooleanGetTypeID(),
      n.doubleValue.isFinite, n.doubleValue.rounded() == n.doubleValue,
      n.doubleValue >= Double(minimum), n.doubleValue <= Double(maximum)
    else {
      throw CalendarError(
        "INVALID_INPUT", "\(name) must be an integer from \(minimum) through \(maximum).")
    }
    return n.intValue
  }
  public static func free(start: Date, end: Date, busy: [DateInterval], minimum: Double)
    -> [DateInterval]
  {
    let clipped = busy.compactMap { item -> DateInterval? in
      let a = max(start, item.start)
      let b = min(end, item.end)
      return b > a ? DateInterval(start: a, end: b) : nil
    }.sorted { $0.start < $1.start }
    var cursor = start
    var result: [DateInterval] = []
    for item in clipped {
      if item.start.timeIntervalSince(cursor) >= minimum {
        result.append(DateInterval(start: cursor, end: item.start))
      }
      cursor = max(cursor, item.end)
    }
    if end.timeIntervalSince(cursor) >= minimum {
      result.append(DateInterval(start: cursor, end: end))
    }
    return result
  }
}
struct EventReference: Codable {
  let id: String
  let calendarId: String?
  let itemId: String?
  let occurrence: String?
  let start: String?
  func encode() -> String {
    "event:"
      + (try! JSONEncoder().encode(self)).base64EncodedString().replacingOccurrences(
        of: "+", with: "-"
      ).replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
  }
  static func decode(_ text: String) throws -> Self {
    guard !text.isEmpty else {
      throw CalendarError("INVALID_INPUT", "An event ID or reference is required.")
    }
    guard text.hasPrefix("event:") else {
      return Self(id: text, calendarId: nil, itemId: nil, occurrence: nil, start: nil)
    }
    var b = String(text.dropFirst(6)).replacingOccurrences(of: "-", with: "+").replacingOccurrences(
      of: "_", with: "/")
    b += String(repeating: "=", count: (4 - b.count % 4) % 4)
    guard let data = Data(base64Encoded: b),
      let ref = try? JSONDecoder().decode(Self.self, from: data), !ref.id.isEmpty
    else { throw CalendarError("INVALID_INPUT", "Malformed event reference.") }
    return ref
  }
}
