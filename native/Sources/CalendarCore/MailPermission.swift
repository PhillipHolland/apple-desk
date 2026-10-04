import AppKit
import Carbon
import Foundation

public enum MailPermission {
  public static func check(request: Bool) throws -> [String: Any] {
    var running = !NSRunningApplication.runningApplications(withBundleIdentifier: "com.apple.mail")
      .isEmpty
    if request && !running {
      guard let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.apple.mail")
      else { throw CalendarError("NOT_FOUND", "Apple Mail is not installed.") }
      let lock = NSLock()
      var finished = false
      var launchError: Error?
      let configuration = NSWorkspace.OpenConfiguration()
      configuration.activates = false
      NSWorkspace.shared.openApplication(at: url, configuration: configuration) { _, error in
        lock.lock()
        launchError = error
        finished = true
        lock.unlock()
      }
      let deadline = Date().addingTimeInterval(15)
      while Date() < deadline {
        lock.lock()
        let done = finished
        lock.unlock()
        if done { break }
        RunLoop.current.run(until: Date().addingTimeInterval(0.05))
      }
      if let launchError {
        throw CalendarError("MAIL_UNAVAILABLE", launchError.localizedDescription)
      }
      running = !NSRunningApplication.runningApplications(withBundleIdentifier: "com.apple.mail")
        .isEmpty
    }
    var result: [String: Any] = [
      "backend": "apple-events", "running": running, "authorization": "notRunning",
      "allowed": false, "prompts": request, "status": NSNull(),
      "permissionCommand": "grok-mail permissions request",
    ]
    guard running else {
      if request {
        throw CalendarError(
          "MAIL_UNAVAILABLE",
          "Mail did not start. Open Mail and try the explicit permission request again.")
      }
      return result
    }
    var descriptor = AEAddressDesc()
    let bytes = Array("com.apple.mail".utf8)
    let creation = bytes.withUnsafeBytes {
      AECreateDesc(DescType(typeApplicationBundleID), $0.baseAddress, $0.count, &descriptor)
    }
    guard creation == noErr else {
      throw CalendarError("AUTOMATION_ERROR", "Could not create Mail target descriptor.")
    }
    defer { AEDisposeDesc(&descriptor) }
    let status = AEDeterminePermissionToAutomateTarget(
      &descriptor, AEEventClass(typeWildCard), AEEventID(typeWildCard), request)
    let name =
      status == noErr
      ? "authorized"
      : (status == -1744 ? "notDetermined" : status == -1743 ? "denied" : "unavailable")
    result["authorization"] = name
    result["allowed"] = status == noErr
    result["status"] = Int(status)
    if request && status != noErr {
      throw CalendarError(
        "PERMISSION_REQUIRED",
        "Mail Automation access was not granted. Check System Settings > Privacy & Security > Automation.",
        details: result)
    }
    return result
  }
}
