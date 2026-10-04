import Foundation

public enum CalendarVerification {
  public static func mismatches(
    _ intended: [String: Any], _ observed: [String: Any], fields: Set<String>
  ) -> [String] {
    fields.sorted().filter { field in
      switch field {
      case "title", "notes", "location", "url":
        return text(intended[field]) != text(observed[field])
      case "calendarId", "availability":
        return intended[field] as? String != observed[field] as? String
      case "allDay": return intended[field] as? Bool != observed[field] as? Bool
      case "start", "end":
        return intended["allDay"] as? Bool == true
          ? intended[field] as? String != observed[field] as? String
          : !sameInstant(intended[field], observed[field])
      case "timeZone":
        if intended[field] as? String == observed[field] as? String { return false }
        guard let a = intended[field] as? String, let b = observed[field] as? String,
          let x = TimeZone(identifier: a), let y = TimeZone(identifier: b)
        else { return true }
        return x != y && (x as NSTimeZone).data != (y as NSTimeZone).data
      case "alarms": return !sameAlarms(intended, observed)
      case "recurrence": return !sameRules(intended, observed)
      default: return false
      }
    }
  }
  private static func text(_ value: Any?) -> String {
    (value as? String ?? "").replacingOccurrences(of: "\r\n", with: "\n").replacingOccurrences(
      of: "\r", with: "\n")
  }
  private static func instant(_ value: Any?, zone: TimeZone? = nil) -> Date? {
    guard let value = value as? String else { return nil }
    return try? CalendarLogic.parse(value, zone: zone)
  }
  private static func sameInstant(_ a: Any?, _ b: Any?) -> Bool {
    guard let x = instant(a), let y = instant(b) else { return false }
    return abs(x.timeIntervalSince(y)) < 1
  }
  private static func sameAlarms(_ expected: [String: Any], _ actual: [String: Any]) -> Bool {
    let recurring = expected["recurring"] as? Bool == true || actual["recurring"] as? Bool == true
    func normalize(_ event: [String: Any]) -> [(String, Double)]? {
      guard let alarms = event["alarms"] as? [[String: Any]] else { return nil }
      let zone = (event["timeZone"] as? String).flatMap(TimeZone.init(identifier:)) ?? .current
      let start = instant(
        event["start"],
        zone: (event["timeZone"] as? String).flatMap(TimeZone.init(identifier:)) ?? .current)
      var values: [(String, Double)] = []
      for alarm in alarms {
        if let at = instant(alarm["at"], zone: zone) {
          values.append(("absolute", at.timeIntervalSince1970))
        } else if let minutes = alarm["minutesBefore"] as? NSNumber {
          if recurring {
            values.append(("relative", -minutes.doubleValue * 60))
          } else if let start {
            values.append(("absolute", start.timeIntervalSince1970 - minutes.doubleValue * 60))
          } else {
            return nil
          }
        } else {
          return nil
        }
      }
      values.sort { $0.0 == $1.0 ? $0.1 < $1.1 : $0.0 < $1.0 }
      var unique: [(String, Double)] = []
      for v in values {
        if let last = unique.last, last.0 == v.0 && abs(last.1 - v.1) < 1 { continue }
        unique.append(v)
      }
      return unique
    }
    guard let a = normalize(expected), let b = normalize(actual), a.count == b.count else {
      return false
    }
    return zip(a, b).allSatisfy { $0.0.0 == $0.1.0 && abs($0.0.1 - $0.1.1) < 1 }
  }
  private static func sameRules(_ expected: [String: Any], _ actual: [String: Any]) -> Bool {
    guard let a = expected["recurrenceRules"] as? [[String: Any]],
      let b = actual["recurrenceRules"] as? [[String: Any]], a.count == b.count
    else { return false }
    if a.isEmpty { return true }
    guard a.count == 1 else { return false }
    var x = normalizeRule(a[0], expected)
    var y = normalizeRule(b[0], actual)
    let untilX = x.removeValue(forKey: "until")
    let untilY = y.removeValue(forKey: "until")
    if untilX != nil || untilY != nil, !sameInstant(untilX, untilY) { return false }
    guard let first = try? JSONSerialization.data(withJSONObject: x, options: [.sortedKeys]),
      let second = try? JSONSerialization.data(withJSONObject: y, options: [.sortedKeys])
    else { return false }
    return first == second
  }
  private static func normalizeRule(_ rule: [String: Any], _ event: [String: Any]) -> [String: Any]
  {
    var result = rule
    for key in ["monthDays", "months", "yearDays", "yearWeeks", "setPositions"] {
      if let a = rule[key] as? [NSNumber], !a.isEmpty {
        result[key] = Set(a.map(\.intValue)).sorted()
      } else {
        result.removeValue(forKey: key)
      }
    }
    if let days = rule["weekdays"] as? [[String: Int]], !days.isEmpty {
      result["weekdays"] = Array(Set(days.map { "\($0["day"] ?? 0):\($0["weekNumber"] ?? 0)" }))
        .sorted()
    } else {
      result.removeValue(forKey: "weekdays")
    }
    let zone = (event["timeZone"] as? String).flatMap(TimeZone.init(identifier:)) ?? .current
    guard let start = instant(event["start"], zone: zone) else { return result }
    var c = Calendar(identifier: .gregorian)
    c.timeZone = zone
    let d = c.dateComponents([.month, .day, .weekday], from: start)
    switch rule["frequency"] as? String {
    case "weekly": if result["weekdays"] == nil { result["weekdays"] = ["\(d.weekday!):0"] }
    case "monthly":
      if result["monthDays"] == nil && result["weekdays"] == nil { result["monthDays"] = [d.day!] }
    case "yearly":
      if result["weekdays"] == nil && result["yearDays"] == nil && result["yearWeeks"] == nil {
        if result["months"] == nil { result["months"] = [d.month!] }
        if result["monthDays"] == nil { result["monthDays"] = [d.day!] }
      }
    default: break
    }
    return result
  }
}
