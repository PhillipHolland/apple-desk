function run(argv) {
  var raw = "";
  for (var i = 0; i < argv.length; i++) {
    if (argv[i] && argv[i] !== "--") { raw = argv[i]; break; }
  }
  var payload;
  try { payload = JSON.parse(raw || "{}"); }
  catch (e) {
    return JSON.stringify({ ok: false, error: "bad_request", message: "invalid JSON argv" });
  }
  var Calendar = Application("Calendar");
  try {
    return JSON.stringify(dispatch(Calendar, payload));
  } catch (e) {
    var msg = String(e && e.message ? e.message : e);
    var err = "calendar_error";
    if (msg.indexOf("-1743") !== -1 || msg.indexOf("Not authorized") !== -1) err = "automation_denied";
    if (msg.indexOf("kTCCServiceCalendar") !== -1 || msg.indexOf("Calendar access") !== -1) err = "calendar_tcc";
    return JSON.stringify({ ok: false, error: err, message: msg });
  }
}

function dispatch(app, payload) {
  var op = payload.op;
  if (op === "doctor") return doctor(app);
  if (op === "calendars") return calendars(app);
  if (op === "list") return listEvents(app, payload, false);
  if (op === "search") return listEvents(app, payload, true);
  if (op === "show") return showEvent(app, payload);
  if (op === "create") return createEvent(app, payload);
  if (op === "update") return updateEvent(app, payload);
  if (op === "delete") return deleteEvent(app, payload);
  return { ok: false, error: "bad_request", message: "Unknown op " + op };
}

function doctor(app) {
  var rows = calendarRows(app);
  var writable = 0;
  for (var i = 0; i < rows.length; i++) if (rows[i].writable) writable++;
  return {
    ok: true,
    automation: "authorized",
    backend: "calendar-app-jxa",
    readOnlyDefault: true,
    calendarApp: { version: String(app.version()), id: safe(function () { return app.id(); }, "com.apple.iCal") },
    calendars: rows.length,
    writableCalendars: writable,
    names: rows.map(function (r) { return r.name; })
  };
}

function calendars(app) {
  var rows = calendarRows(app);
  rows.sort(function (a, b) { return String(a.name || "").localeCompare(String(b.name || "")); });
  return { ok: true, count: rows.length, calendars: rows };
}

function calendarRows(app) {
  var n = app.calendars.length;
  if (!n) return [];
  var cals = asList(app.calendars());
  var rows = [];
  for (var i = 0; i < cals.length; i++) {
    var c = cals[i];
    var writable = false;
    try { writable = !!c.writable(); } catch (e) { writable = false; }
    rows.push({
      id: safe(function () { return c.uid(); }, safe(function () { return c.id(); }, null)),
      name: empty(c.name()),
      writable: writable,
      description: clip(empty(safe(function () { return c.description(); }, null)), 200)
    });
  }
  return rows;
}

function listEvents(app, payload, isSearch) {
  var q = String(payload.query || "").trim();
  if (isSearch && q.length < 2) {
    return { ok: false, error: "missing_query", message: "Search needs at least 2 characters." };
  }
  var range = rangeFrom(payload);
  if (!range.ok) return range;
  var selected = selectCalendars(app, payload.calendar);
  if (!selected.ok) return selected;
  var limit = payload.limit || 25;
  var rows = [];
  var scanned = 0;
  for (var i = 0; i < selected.calendars.length; i++) {
    var cal = selected.calendars[i];
    var spec = cal.events.whose({
      _and: [
        { startDate: { _lessThan: range.end } },
        { endDate: { _greaterThan: range.start } }
      ]
    });
    var n = 0;
    try { n = spec.length; } catch (e) {
      return { ok: false, error: "calendar_error", message: "Could not query " + cal.name() + ": " + e };
    }
    scanned += n;
    if (n > 800) {
      return {
        ok: false,
        error: "query_too_broad",
        count: n,
        calendar: cal.name(),
        message: "Calendar " + cal.name() + " has " + n + " events in that window. Narrow --from/--to or pass --calendar."
      };
    }
    if (!n) continue;
    var titles = asList(spec.summary());
    var starts = asList(spec.startDate());
    var ends = asList(spec.endDate());
    var uids = asList(spec.uid());
    var allday = asList(spec.alldayEvent());
    var locs = [];
    try { locs = asList(spec.location()); } catch (e2) { locs = []; }
    for (var j = 0; j < n; j++) {
      var title = empty(titles[j]) || "(no title)";
      var loc = empty(locs[j]);
      if (isSearch && !matchesQuery(q, title, loc)) continue;
      rows.push({
        uid: empty(uids[j]),
        title: title,
        start: formatLocal(starts[j]),
        end: formatLocal(ends[j]),
        allDay: !!allday[j],
        calendar: empty(cal.name()),
        calendarId: safe(function () { return cal.uid(); }, null),
        location: loc
      });
    }
  }
  rows.sort(function (a, b) { return String(a.start || "").localeCompare(String(b.start || "")); });
  return {
    ok: true,
    query: isSearch ? q : null,
    from: formatLocal(range.start),
    to: formatLocal(range.end),
    scanned: scanned,
    count: rows.length,
    truncated: rows.length > limit,
    events: rows.slice(0, limit)
  };
}

function showEvent(app, payload) {
  var found = findEvent(app, payload);
  if (!found.ok) return found;
  var ev = found.event;
  var card = {
    uid: empty(ev.uid()),
    title: empty(ev.summary()) || "(no title)",
    start: formatLocal(ev.startDate()),
    end: formatLocal(ev.endDate()),
    allDay: !!safe(function () { return ev.alldayEvent(); }, false),
    location: empty(safe(function () { return ev.location(); }, null)),
    notes: clip(empty(safe(function () { return ev.description(); }, null)), 2000),
    url: empty(safe(function () { return String(ev.url()); }, null)),
    status: empty(safe(function () { return String(ev.status()); }, null)),
    recurrence: empty(safe(function () { return ev.recurrence(); }, null)),
    calendar: empty(found.calendar.name()),
    calendarId: safe(function () { return found.calendar.uid(); }, null),
    writable: !!safe(function () { return found.calendar.writable(); }, false)
  };
  return { ok: true, event: card };
}

function createEvent(app, payload) {
  if (!payload.title) return { ok: false, error: "missing_title", message: "create needs --title." };
  var selected = selectCalendars(app, payload.calendar);
  if (!selected.ok) return selected;
  if (!payload.calendar) {
    return { ok: false, error: "missing_calendar", message: "create needs --calendar (exact calendar name)." };
  }
  if (selected.calendars.length !== 1) {
    return { ok: false, error: "ambiguous", message: "Pass one exact --calendar name.", matches: namesOf(selected.calendars) };
  }
  var cal = selected.calendars[0];
  if (!safe(function () { return cal.writable(); }, false)) {
    return { ok: false, error: "read_only_calendar", message: cal.name() + " is not writable." };
  }
  var when = eventTimes(payload);
  if (!when.ok) return when;
  var props = { summary: payload.title, startDate: when.start, endDate: when.end };
  if (payload.allDay) props.alldayEvent = true;
  if (payload.location) props.location = payload.location;
  if (payload.notes) props.description = payload.notes;
  var ev = app.Event(props);
  cal.events.push(ev);
  return {
    ok: true,
    created: true,
    uid: empty(ev.uid()),
    title: empty(ev.summary()),
    start: formatLocal(ev.startDate()),
    end: formatLocal(ev.endDate()),
    calendar: empty(cal.name())
  };
}

function updateEvent(app, payload) {
  if (!payload.uid) return { ok: false, error: "missing_target", message: "update needs --uid." };
  var found = findEvent(app, payload);
  if (!found.ok) return found;
  if (!safe(function () { return found.calendar.writable(); }, false)) {
    return { ok: false, error: "read_only_calendar", message: found.calendar.name() + " is not writable." };
  }
  var ev = found.event;
  var changed = false;
  if (payload.title) { ev.summary = payload.title; changed = true; }
  if (payload.location !== undefined && payload.location !== null) { ev.location = payload.location; changed = true; }
  if (payload.notes !== undefined && payload.notes !== null) { ev.description = payload.notes; changed = true; }
  if (payload.allDay === true || payload.allDay === false) { ev.alldayEvent = !!payload.allDay; changed = true; }
  if (payload.start || payload.end) {
    var when = eventTimes({
      start: payload.start || formatLocal(ev.startDate()),
      end: payload.end || formatLocal(ev.endDate()),
      allDay: payload.allDay === true || (payload.allDay !== false && ev.alldayEvent())
    });
    if (!when.ok) return when;
    ev.startDate = when.start;
    ev.endDate = when.end;
    changed = true;
  }
  if (!changed) return { ok: false, error: "missing_change", message: "update needs at least one of --title, --start, --end, --location, --notes, --all-day." };
  return {
    ok: true,
    updated: true,
    uid: empty(ev.uid()),
    title: empty(ev.summary()),
    start: formatLocal(ev.startDate()),
    end: formatLocal(ev.endDate()),
    calendar: empty(found.calendar.name())
  };
}

function deleteEvent(app, payload) {
  if (!payload.force) {
    return { ok: false, error: "needs_force", message: "delete refuses without --force. This removes one event from Calendar." };
  }
  if (!payload.uid) return { ok: false, error: "missing_target", message: "delete needs --uid (not a title) and --force." };
  var found = findEvent(app, payload);
  if (!found.ok) return found;
  if (!safe(function () { return found.calendar.writable(); }, false)) {
    return { ok: false, error: "read_only_calendar", message: found.calendar.name() + " is not writable." };
  }
  var title = empty(found.event.summary());
  var uid = empty(found.event.uid());
  app.delete(found.event);
  return { ok: true, deleted: true, uid: uid, title: title, calendar: empty(found.calendar.name()) };
}

function findEvent(app, payload) {
  if (payload.uid) {
    var cals = asList(app.calendars());
    for (var i = 0; i < cals.length; i++) {
      var hits = cals[i].events.whose({ uid: payload.uid });
      var n = 0;
      try { n = hits.length; } catch (e) { n = 0; }
      if (n > 0) return { ok: true, calendar: cals[i], event: asList(hits())[0] };
    }
    return { ok: false, error: "not_found", message: "No event with that uid." };
  }
  var q = String(payload.query || "").trim();
  if (!q) return { ok: false, error: "missing_target", message: "Pass --uid or a title to search in the default window." };
  var listed = listEvents(app, {
    query: q,
    from: payload.from,
    to: payload.to,
    calendar: payload.calendar,
    limit: 20
  }, true);
  if (!listed.ok) return listed;
  if (listed.count === 0) return { ok: false, error: "not_found", message: "No event matched." };
  if (listed.count > 1) {
    return {
      ok: false,
      error: "ambiguous",
      count: listed.count,
      message: "More than one event matched. Run show --uid with one uid.",
      matches: (listed.events || []).map(function (e) {
        return { uid: e.uid, title: e.title, start: e.start, calendar: e.calendar };
      })
    };
  }
  return findEvent(app, { uid: listed.events[0].uid });
}

function selectCalendars(app, name) {
  var cals = asList(app.calendars());
  if (!name) return { ok: true, calendars: cals };
  var q = String(name).trim();
  var exact = [];
  for (var i = 0; i < cals.length; i++) {
    if (empty(cals[i].name()) === q) exact.push(cals[i]);
  }
  if (exact.length === 1) return { ok: true, calendars: exact };
  if (exact.length > 1) {
    return { ok: false, error: "ambiguous", message: "More than one calendar is named " + q + ".", matches: namesOf(exact) };
  }
  return { ok: false, error: "not_found", message: "No calendar named " + q + ".", matches: namesOf(cals) };
}

function namesOf(cals) {
  return cals.map(function (c) { return { name: empty(c.name()), id: safe(function () { return c.uid(); }, null) }; });
}

function eventTimes(payload) {
  var start = parseWhen(payload.start, false);
  var end = parseWhen(payload.end, false);
  if (!start) return { ok: false, error: "bad_request", message: "Need --start as YYYY-MM-DD or YYYY-MM-DD HH:MM." };
  if (payload.allDay) {
    start = new Date(start.getFullYear(), start.getMonth(), start.getDate(), 0, 0, 0);
    if (!end) end = new Date(start.getFullYear(), start.getMonth(), start.getDate() + 1, 0, 0, 0);
    else end = new Date(end.getFullYear(), end.getMonth(), end.getDate(), 0, 0, 0);
    if (end.getTime() <= start.getTime()) end = new Date(start.getFullYear(), start.getMonth(), start.getDate() + 1, 0, 0, 0);
  } else if (!end) {
    end = new Date(start.getTime() + 60 * 60 * 1000);
  }
  if (end.getTime() <= start.getTime()) {
    return { ok: false, error: "bad_request", message: "--end must be after --start." };
  }
  return { ok: true, start: start, end: end };
}

function rangeFrom(payload) {
  var start = parseWhen(payload.from, false);
  var end = parseWhen(payload.to, true);
  if (!start || !end) return { ok: false, error: "bad_request", message: "Need a date range." };
  if (end.getTime() <= start.getTime()) return { ok: false, error: "bad_request", message: "--to must be after --from." };
  return { ok: true, start: start, end: end };
}

function parseWhen(s, endOfDay) {
  if (!s) return null;
  var m = String(s).trim();
  var dOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(m);
  if (dOnly) {
    return new Date(+dOnly[1], +dOnly[2] - 1, +dOnly[3], endOfDay ? 23 : 0, endOfDay ? 59 : 0, endOfDay ? 59 : 0);
  }
  var dt = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?/.exec(m);
  if (dt) return new Date(+dt[1], +dt[2] - 1, +dt[3], +dt[4], +dt[5], +(dt[6] || 0));
  var parsed = new Date(m);
  if (isNaN(parsed.getTime())) return null;
  return parsed;
}

function matchesQuery(q, title, loc) {
  var hay = (String(title || "") + " " + String(loc || "")).toLowerCase();
  return hay.indexOf(String(q).toLowerCase()) !== -1;
}

function asList(v) {
  if (v === null || v === undefined) return [];
  if (Object.prototype.toString.call(v) === "[object Array]") return v;
  return [v];
}

function empty(v) {
  if (v === null || v === undefined) return null;
  var s = String(v);
  if (!s || s === "missing value" || s === "undefined" || s === "null") return null;
  return s;
}

function clip(s, n) {
  if (!s) return null;
  if (s.length <= n) return s;
  return s.slice(0, n) + "…";
}

function safe(fn, fallback) {
  try { return fn(); } catch (e) { return fallback; }
}

function pad(n) { return (n < 10 ? "0" : "") + n; }

function formatLocal(d) {
  try {
    if (!d || isNaN(d.getTime())) return null;
    var off = -d.getTimezoneOffset();
    var sign = off >= 0 ? "+" : "-";
    var abs = Math.abs(off);
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate())
      + "T" + pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds())
      + sign + pad(Math.floor(abs / 60)) + ":" + pad(abs % 60);
  } catch (e) {
    return null;
  }
}
