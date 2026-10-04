// Reminders.app JXA. Local lists and reminders only. Not RemCTL.
function run(argv) {
  var raw = "";
  for (var i = 0; i < argv.length; i++) {
    if (argv[i] && argv[i] !== "--") { raw = argv[i]; break; }
  }
  var payload;
  try { payload = JSON.parse(raw || "{}"); }
  catch (e) {
    return JSON.stringify({ok: false, error: "bad_request", message: "invalid JSON argv"});
  }
  var Reminders = Application("Reminders");
  var op = payload.op;

  function fail(error, message) {
    return JSON.stringify({ok: false, error: error, message: message});
  }

  function z(n) { return (n < 10 ? "0" : "") + n; }

  function asArray(v) {
    if (v === null || v === undefined) return [];
    var tag = Object.prototype.toString.call(v);
    if (tag === "[object Array]") return v;
    if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") return [v];
    if (tag === "[object Date]") return [v];
    try {
      if (typeof v.length === "number") {
        var out = [];
        for (var i = 0; i < v.length; i++) out.push(v[i]);
        return out;
      }
    } catch (e) {}
    return [v];
  }

  function isoLocal(d) {
    if (!d) return null;
    var dt = (d instanceof Date) ? d : new Date(d);
    if (isNaN(dt.getTime())) return null;
    return dt.getFullYear() + "-" + z(dt.getMonth() + 1) + "-" + z(dt.getDate())
      + "T" + z(dt.getHours()) + ":" + z(dt.getMinutes()) + ":" + z(dt.getSeconds());
  }

  function dayKey(d) {
    if (!d) return null;
    var dt = (d instanceof Date) ? d : new Date(d);
    if (isNaN(dt.getTime())) return null;
    return dt.getFullYear() + "-" + z(dt.getMonth() + 1) + "-" + z(dt.getDate());
  }

  function addDays(key, n) {
    var m = String(key).match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!m) return null;
    var dt = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
    dt.setDate(dt.getDate() + n);
    return dayKey(dt);
  }

  function priorityName(n) {
    n = Number(n || 0);
    if (n === 1) return "high";
    if (n === 5) return "medium";
    if (n === 9) return "low";
    return "none";
  }

  function priorityValue(name) {
    var key = String(name || "none").toLowerCase();
    if (key === "high") return 1;
    if (key === "medium") return 5;
    if (key === "low") return 9;
    if (key === "none") return 0;
    return null;
  }

  function parseDue(s) {
    var m = String(s || "").match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?$/);
    if (!m) return null;
    return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), m[4] ? Number(m[4]) : 9, m[5] ? Number(m[5]) : 0, 0);
  }

  function lists() {
    var spec = Reminders.lists;
    var n = spec.length;
    var out = [];
    for (var i = 0; i < n; i++) out.push(spec[i]);
    return out;
  }

  function findList(nameOrId) {
    var all = lists();
    var folded = String(nameOrId || "").toLowerCase();
    var hits = [];
    for (var i = 0; i < all.length; i++) {
      var list = all[i];
      var name = "";
      var id = "";
      try { name = String(list.name()); } catch (e) { name = ""; }
      try { id = String(list.id()); } catch (e2) { id = ""; }
      if (id === nameOrId || name.toLowerCase() === folded) hits.push(list);
    }
    return hits;
  }

  function defaultList() {
    try {
      var d = Reminders.defaultList();
      if (d) return d;
    } catch (e) {}
    try {
      var d2 = Reminders.defaultList;
      if (d2 && d2.name) return d2;
    } catch (e2) {}
    var named = findList("Reminders");
    if (named.length === 1) return named[0];
    var all = lists();
    return all.length ? all[0] : null;
  }

  function bulk(list, withBody, incompleteOnly) {
    var rem = incompleteOnly ? list.reminders.whose({completed: false}) : list.reminders;
    var ids = [];
    try { ids = asArray(rem.id()); } catch (e) { return []; }
    if (!ids.length) return [];
    var names = [], completed = [], due = [], priority = [], flagged = [], body = [];
    try { names = asArray(rem.name()); } catch (e2) { names = []; }
    try { completed = incompleteOnly ? [] : asArray(rem.completed()); } catch (e3) { completed = []; }
    try { due = asArray(rem.dueDate()); } catch (e4) { due = []; }
    try { priority = asArray(rem.priority()); } catch (e5) { priority = []; }
    try { flagged = asArray(rem.flagged()); } catch (e6) { flagged = []; }
    if (withBody) {
      try { body = asArray(rem.body()); } catch (e7) { body = []; }
    }
    var listName = "";
    var listId = "";
    try { listName = String(list.name()); } catch (e8) { listName = ""; }
    try { listId = String(list.id()); } catch (e9) { listId = ""; }
    var rows = [];
    for (var i = 0; i < ids.length; i++) {
      rows.push({
        id: ids[i] == null ? null : String(ids[i]),
        title: names[i] == null ? "" : String(names[i]),
        completed: incompleteOnly ? false : Boolean(completed[i]),
        due: isoLocal(due[i]),
        dueDay: dayKey(due[i]),
        priority: priorityName(priority[i]),
        flagged: Boolean(flagged[i]),
        body: withBody ? (body[i] == null ? "" : String(body[i])) : undefined,
        list: listName,
        listId: listId,
        index: i
      });
    }
    return rows;
  }

  function clipBody(text, n) {
    text = String(text || "");
    if (text.length <= n) return text;
    return text.slice(0, n);
  }

  function publicRow(row, withBody) {
    var out = {
      id: row.id,
      title: row.title,
      list: row.list,
      listId: row.listId,
      completed: row.completed,
      due: row.due,
      priority: row.priority,
      flagged: row.flagged
    };
    if (withBody) out.body = clipBody(row.body, 2000);
    return out;
  }

  if (op === "doctor") {
    // Lightweight: do not walk every reminder (that times out on large libraries).
    var all = lists();
    var names = [];
    for (var i = 0; i < all.length; i++) {
      try { names.push(String(all[i].name())); } catch (e) { names.push("(unnamed)"); }
    }
    var defName = null;
    var def = defaultList();
    if (def) {
      try { defName = String(def.name()); } catch (e) { defName = null; }
    }
    return JSON.stringify({
      ok: true,
      automation: "authorized",
      backend: "reminders-app-jxa",
      name: Reminders.name(),
      version: Reminders.version(),
      lists: all.length,
      listNames: names,
      defaultList: defName,
      note: "Doctor does not count reminders; use lists/today for counts."
    });
  }

  if (op === "lists") {
    var allLists = lists();
    var withCounts = !!payload.counts;
    var outLists = [];
    for (var li = 0; li < allLists.length; li++) {
      var lname = "";
      var lid = "";
      try { lname = String(allLists[li].name()); } catch (e) { lname = ""; }
      try { lid = String(allLists[li].id()); } catch (e) { lid = ""; }
      var entry = { name: lname, id: lid };
      if (withCounts) {
        var rows = bulk(allLists[li], false, false);
        var inc = 0;
        for (var rj = 0; rj < rows.length; rj++) if (!rows[rj].completed) inc++;
        entry.reminders = rows.length;
        entry.incomplete = inc;
      }
      outLists.push(entry);
    }
    return JSON.stringify({ok: true, count: outLists.length, lists: outLists, counts: withCounts});
  }

  if (op === "collect") {
    var wanted = payload.list || null;
    var chosen = lists();
    if (wanted) {
      chosen = findList(wanted);
      if (chosen.length === 0) return fail("not_found", "No list named " + wanted + ".");
      if (chosen.length > 1) return fail("ambiguous", "More than one list matches " + wanted + ".");
    }
    var withBody = Boolean(payload.withBody);
    var incompleteOnly = payload.incompleteOnly !== false; // default lean: open items only
    if (payload.includeCompleted) incompleteOnly = false;
    var items = [];
    var cap = Number(payload.cap || 4000);
    var truncated = false;
    for (var c = 0; c < chosen.length; c++) {
      var got = bulk(chosen[c], withBody, incompleteOnly);
      for (var g = 0; g < got.length; g++) {
        if (items.length >= cap) { truncated = true; break; }
        items.push(publicRow(got[g], withBody));
      }
      if (truncated) break;
    }
    return JSON.stringify({ok: true, count: items.length, truncated: truncated, incompleteOnly: incompleteOnly, reminders: items});
  }

  if (op === "show") {
    var id = String(payload.id || "");
    if (!id) return fail("missing_id", "Pass an id.");
    var allShow = lists();
    for (var s = 0; s < allShow.length; s++) {
      var srows = bulk(allShow[s], true, false);
      for (var k = 0; k < srows.length; k++) {
        if (srows[k].id === id) {
          var shown = publicRow(srows[k], true);
          var target = allShow[s].reminders[k];
          try { shown.remindMeDate = isoLocal(target.remindMeDate()); } catch (eR) { shown.remindMeDate = null; }
          try { shown.allDay = Boolean(target.alldayDueDate()); } catch (eA) { shown.allDay = null; }
          return JSON.stringify({ok: true, reminder: shown});
        }
      }
    }
    return fail("not_found", "No reminder with that id.");
  }

  if (op === "add") {
    var title = String(payload.title || "").trim();
    if (!title) return fail("missing_title", "Pass a title. Nothing was added.");
    var list;
    if (payload.list) {
      var hits = findList(payload.list);
      if (hits.length === 0) return fail("not_found", "No list named " + payload.list + ". Nothing was added.");
      if (hits.length > 1) return fail("ambiguous", "More than one list matches. Nothing was added.");
      list = hits[0];
    } else {
      list = defaultList();
      if (!list) return fail("not_found", "No Reminders list to add to. Nothing was added.");
    }
    var props = {name: title};
    if (payload.notes) props.body = String(payload.notes);
    if (payload.due) {
      var due = parseDue(payload.due);
      if (!due) return fail("bad_request", "Due must be YYYY-MM-DD or YYYY-MM-DD HH:MM in this Mac's local time. Nothing was added.");
      props.dueDate = due;
    }
    if (payload.priority) {
      var pv = priorityValue(payload.priority);
      if (pv === null) return fail("bad_request", "Priority must be high, medium, low, or none. Nothing was added.");
      props.priority = pv;
    }
    var created = Reminders.Reminder(props);
    list.reminders.push(created);
    var newId = "";
    var listName = "";
    try { newId = String(created.id()); } catch (e) { newId = ""; }
    try { listName = String(list.name()); } catch (e2) { listName = ""; }
    return JSON.stringify({ok: true, added: true, id: newId, title: title, list: listName, due: payload.due || null});
  }

  if (op === "done" || op === "delete") {
    var rid = String(payload.id || "");
    if (!rid) return fail("missing_id", "Pass an id. Nothing was changed.");
    var pool = lists();
    for (var p = 0; p < pool.length; p++) {
      var ids;
      try { ids = asArray(pool[p].reminders.id()); } catch (e) { continue; }
      for (var q = 0; q < ids.length; q++) {
        if (String(ids[q]) !== rid) continue;
        var target = pool[p].reminders[q];
        if (op === "done") {
          target.completed = true;
          return JSON.stringify({ok: true, completed: true, id: rid});
        }
        target.delete();
        return JSON.stringify({ok: true, deleted: true, id: rid});
      }
    }
    return fail("not_found", "No reminder with that id. Nothing was changed.");
  }


  if (op === "flag" || op === "move") {
    if (payload.force !== true) {
      return fail("needs_force", op + " refuses unless force is true. Reminders was not called.");
    }
    var rid = String(payload.id || "");
    if (!rid) return fail("missing_id", "Pass an id. Nothing was changed.");
    var pool = lists();
    var target = null;
    var sourceList = null;
    for (var p = 0; p < pool.length; p++) {
      var ids;
      try { ids = asArray(pool[p].reminders.id()); } catch (e) { continue; }
      for (var q = 0; q < ids.length; q++) {
        if (String(ids[q]) !== rid) continue;
        target = pool[p].reminders[q];
        sourceList = pool[p];
        break;
      }
      if (target) break;
    }
    if (!target) return fail("not_found", "No reminder with that id. Nothing was changed.");

    if (op === "flag") {
      var state = String(payload.state || "");
      if (state !== "flagged" && state !== "unflagged") {
        return fail("bad_request", "flag state must be flagged or unflagged. Nothing was changed.");
      }
      try {
        target.flagged = (state === "flagged");
      } catch (eFlag) {
        return fail("reminders_error", "Reminders did not update flagged: " + eFlag);
      }
      return JSON.stringify({ok: true, applied: true, dryRun: false, op: "flag", id: rid, state: state});
    }

    var destName = String(payload.to || "").trim();
    if (!destName) return fail("bad_request", "move needs a destination list. Nothing was changed.");
    var destHits = findList(destName);
    if (destHits.length === 0) return fail("not_found", "No list named " + destName + ". Nothing was changed.");
    if (destHits.length > 1) return fail("ambiguous", "More than one list matches " + destName + ". Nothing was changed.");
    var dest = destHits[0];
    var srcName = "";
    var dstName = "";
    try { srcName = String(sourceList.name()); } catch (eS) { srcName = ""; }
    try { dstName = String(dest.name()); } catch (eD) { dstName = destName; }
    try {
      if (String(sourceList.id()) === String(dest.id())) {
        return JSON.stringify({ok: true, applied: true, dryRun: false, op: "move", id: rid, to: dstName, list: dstName, sameList: true});
      }
    } catch (eSame) {}

    var moved = false;
    try {
      Reminders.move(target, {to: dest});
      moved = true;
    } catch (eMove) {
      moved = false;
    }
    if (!moved) {
      // Fallback: copy properties into destination, then delete source.
      var title = "";
      var body = "";
      var dueDate = null;
      var pri = 0;
      var wasFlagged = false;
      var wasCompleted = false;
      try { title = String(target.name()); } catch (e1) { title = ""; }
      try { body = String(target.body()); } catch (e2) { body = ""; }
      try { dueDate = target.dueDate(); } catch (e3) { dueDate = null; }
      try { pri = Number(target.priority()); } catch (e4) { pri = 0; }
      try { wasFlagged = Boolean(target.flagged()); } catch (e5) { wasFlagged = false; }
      try { wasCompleted = Boolean(target.completed()); } catch (e6) { wasCompleted = false; }
      var props = {name: title};
      if (body) props.body = body;
      if (dueDate) props.dueDate = dueDate;
      if (pri) props.priority = pri;
      if (wasFlagged) props.flagged = true;
      if (wasCompleted) props.completed = true;
      var created = Reminders.Reminder(props);
      dest.reminders.push(created);
      try { target.delete(); } catch (eDel) {
        return fail("reminders_error", "Copied to " + dstName + " but could not delete source: " + eDel);
      }
      try { rid = String(created.id()); } catch (eId) {}
    }
    return JSON.stringify({ok: true, applied: true, dryRun: false, op: "move", id: rid, to: dstName, list: dstName, from: srcName});
  }

  return fail("bad_request", "unknown op");
}
