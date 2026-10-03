// Messages UI only. Never sends, never types, never presses Return.
// Clicks only Conversation > "Mark All as Read" or "Mark as Read", and only if enabled.
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
    return JSON.stringify({ok: false, error: "bad_request", message: "invalid JSON argv", sent: false});
  }
  var op = payload.op;
  var itemName = null;
  if (op === "mark_all") itemName = "Mark All as Read";
  else if (op === "mark_front") itemName = "Mark as Read";
  else {
    return JSON.stringify({ok: false, error: "bad_request", message: "unsupported ui op", sent: false});
  }

  var Messages = Application("Messages");
  Messages.activate();
  delay(0.7);

  var result = {
    ok: true,
    sent: false,
    activated: true,
    menu: "Conversation",
    item: itemName,
    menuFound: false,
    menuEnabled: false,
    clicked: false,
    action: "activate"
  };

  var se = Application("System Events");
  var proc = se.processes.byName("Messages");
  var found = null;
  try {
    var barItem = proc.menuBars[0].menuBarItems.byName("Conversation");
    var items = barItem.menus[0].menuItems;
    var n = items.length;
    for (var j = 0; j < n; j++) {
      var nm = "";
      try { nm = String(items[j].name()); } catch (e2) { nm = ""; }
      if (nm === itemName) {
        found = items[j];
        break;
      }
    }
  } catch (e3) {
    result.menuError = String(e3);
  }

  if (!found) {
    result.message = "Activated Messages so the open conversation is seen. Menu item " + itemName + " was not found, so it was not clicked.";
    return JSON.stringify(result);
  }
  result.menuFound = true;
  try { result.menuEnabled = !!found.enabled(); }
  catch (e4) { result.menuEnabled = false; }

  if (!result.menuEnabled) {
    result.message = "Activated Messages so the open conversation is seen. " + itemName + " was disabled, so it was not clicked.";
    return JSON.stringify(result);
  }
  found.click();
  result.clicked = true;
  result.action = "Conversation > " + itemName;
  result.message = "Clicked Conversation > " + itemName + ". Nothing was sent.";
  return JSON.stringify(result);
}
