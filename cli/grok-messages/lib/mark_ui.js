// Messages UI only. Never sends, never types, never presses Return.
// Success is a click on an enabled Conversation menu item. Activate alone is not success.
function run(argv) {
  var raw = "";
  for (var i = 0; i < argv.length; i++) {
    if (argv[i] && argv[i] !== "--") {
      raw = argv[i];
      break;
    }
  }
  var payload;
  try { payload = JSON.parse(raw || "{}"); }
  catch (e) {
    return JSON.stringify({ok: false, error: "bad_request", message: "invalid JSON argv", sent: false, clicked: false});
  }
  var op = payload.op;
  var itemName = null;
  if (op === "mark_all") itemName = "Mark All as Read";
  else if (op === "mark_front") itemName = "Mark as Read";
  else {
    return JSON.stringify({ok: false, error: "bad_request", message: "unsupported ui op", sent: false, clicked: false});
  }

  ObjC.import("AppKit");
  ObjC.import("CoreGraphics");
  var se = Application("System Events");

  function frontName() {
    try {
      var procs = se.processes.whose({frontmost: true});
      if (procs.length > 0) return String(procs[0].name());
    } catch (e) {}
    return "";
  }

  function objcCount(obj) {
    if (!obj) return 0;
    try {
      if (typeof obj.count === "function") return Number(obj.count());
    } catch (e) {}
    var c = obj.count;
    var n = Number(c);
    return isNaN(n) ? 0 : n;
  }

  function lockState() {
    var front = frontName();
    var frontLower = String(front || "").toLowerCase();
    var loginWindowFront = frontLower === "loginwindow" || frontLower === "login window";
    var sessionLocked = false;
    try {
      var session = ObjC.deepUnwrap($.CGSessionCopyCurrentDictionary());
      sessionLocked = !!(session && (session.CGSSessionScreenIsLocked === true || session.CGSSessionScreenIsLocked === 1));
    } catch (e0) {}
    var screenSaverRunning = false;
    try {
      var processes = se.processes();
      var n = processes.length;
      for (var i = 0; i < n; i++) {
        var name = "";
        try { name = String(processes[i].name()); } catch (e) { name = ""; }
        if (/screensaver|screen saver/i.test(name)) {
          screenSaverRunning = true;
          break;
        }
      }
    } catch (e2) {}
    return {
      locked: loginWindowFront || sessionLocked || screenSaverRunning,
      frontApp: front || "unknown",
      reason: loginWindowFront ? "loginwindow" : (sessionLocked ? "locked_session" : (screenSaverRunning ? "screensaver" : ""))
    };
  }

  // Do this before any activation/open call. loginwindow is a normal background
  // process on macOS, so only a frontmost loginwindow means the session is locked.
  var state = lockState();
  if (state.locked) {
    return JSON.stringify({
      ok: false,
      error: "screen_locked",
      message: "This UI action needs Messages in front, but the screen is locked or the screensaver is running (frontmost: " + state.frontApp + "). Unread, doctors, and other non-UI Apple Desk commands are not blocked. Unlock/sign in and retry when Messages can be in front.",
      sent: false,
      wroteDatabase: false,
      activated: false,
      frontmost: false,
      frontApp: state.frontApp,
      lockReason: state.reason,
      menu: "Conversation",
      item: itemName,
      menuFound: false,
      menuEnabled: false,
      clicked: false,
      attempts: 0
    });
  }

  function bringFront() {
    var bundle = "com.apple.MobileSMS";
    var running = $.NSRunningApplication.runningApplicationsWithBundleIdentifier(bundle);
    if (objcCount(running) === 0) {
      var cfg = $.NSWorkspaceOpenConfiguration.configuration;
      cfg.setActivates(true);
      $.NSWorkspace.sharedWorkspace.openApplicationAtURL_configuration_completionHandler(
        $.NSURL.fileURLWithPath("/System/Applications/Messages.app"),
        cfg,
        null
      );
      delay(0.4);
      running = $.NSRunningApplication.runningApplicationsWithBundleIdentifier(bundle);
    }
    if (objcCount(running) > 0) {
      var app = running.objectAtIndex(0);
      try { app.unhide(); } catch (e1) {}
      // All windows, and do not let another app keep focus.
      app.activateWithOptions(3);
    }
    try { Application("Messages").activate(); } catch (e2) {}
    try { se.processes.byName("Messages").frontmost = true; } catch (e3) {}
  }

  var front = "";
  var becameFront = false;
  for (var i = 0; i < 12; i++) {
    bringFront();
    delay(0.35);
    front = frontName();
    if (front === "Messages") {
      becameFront = true;
      break;
    }
  }

  var result = {
    ok: false,
    sent: false,
    wroteDatabase: false,
    activated: true,
    frontmost: becameFront,
    frontApp: front,
    menu: "Conversation",
    item: itemName,
    menuFound: false,
    menuEnabled: false,
    clicked: false,
    attempts: 0
  };

  if (!becameFront) {
    result.error = "not_frontmost";
    result.message = "Messages did not become the frontmost app (frontmost was " + (front || "unknown") + "). The menu was not clicked.";
    return JSON.stringify(result);
  }

  function findItem() {
    var proc = se.processes.byName("Messages");
    var barItem = proc.menuBars[0].menuBarItems.byName("Conversation");
    try { barItem.click(); } catch (e) {}
    delay(0.2);
    var items = barItem.menus[0].menuItems;
    var n = items.length;
    for (var j = 0; j < n; j++) {
      var nm = "";
      try { nm = String(items[j].name()); } catch (e2) { nm = ""; }
      if (nm === itemName) return items[j];
    }
    return null;
  }

  var found = null;
  var enabled = false;
  for (var k = 0; k < 8; k++) {
    result.attempts = k + 1;
    if (frontName() !== "Messages") bringFront();
    try {
      found = findItem();
    } catch (e3) {
      result.menuError = String(e3);
      found = null;
    }
    if (found) {
      result.menuFound = true;
      try { enabled = !!found.enabled(); } catch (e4) { enabled = false; }
      result.menuEnabled = enabled;
      if (enabled) break;
    }
    delay(0.45);
  }

  if (!found) {
    result.error = "menu_missing";
    result.message = "Messages was frontmost, but Conversation > " + itemName + " was not found. Nothing was clicked.";
    return JSON.stringify(result);
  }
  if (!enabled) {
    result.error = "menu_disabled";
    result.message = "Messages was frontmost, but " + itemName + " stayed disabled. It was not clicked.";
    return JSON.stringify(result);
  }

  found.click();
  result.clicked = true;
  result.menuEnabled = true;
  result.ok = true;
  result.action = "Conversation > " + itemName;
  result.frontApp = frontName();
  result.message = "Clicked enabled Conversation > " + itemName + ". Nothing was sent.";
  return JSON.stringify(result);
}
