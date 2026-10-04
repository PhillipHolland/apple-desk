/*
 * grok-notes JXA backend (Notes.app).
 * Interim until MacStories / Viticci NotesCTL is public OSS.
 * Not Club NotesCTL. Not jwmoss/notesctl (NoteStore.sqlite).
 * User text arrives only as argv JSON. Do not interpolate it into this file.
 * Reads use bulk property fetches. Writes use make / delete / move.
 */
var VERSION = "0.2.2";
var BODY_CAP = 200000;

function run(argv) {
  var raw = "";
  for (var i = 0; i < argv.length; i++) {
    if (argv[i] && argv[i] !== "--") { raw = argv[i]; break; }
  }
  var req;
  try { req = JSON.parse(raw || "{}"); }
  catch (e) { return JSON.stringify({ ok: false, error: "bad_request", message: "invalid JSON argv" }); }
  try {
    var out = dispatch(req);
    return JSON.stringify(out);
  } catch (e) {
    return JSON.stringify({
      ok: false,
      error: "notes_error",
      message: String(e && e.message ? e.message : e)
    });
  }
}

function dispatch(req) {
  var cmd = req.cmd;
  if (cmd === "doctor") return doctor();
  if (cmd === "folders") return foldersCmd();
  if (cmd === "list") return listNotes(req);
  if (cmd === "show") return showNote(req);
  if (cmd === "search") return searchLive(req);
  if (cmd === "export") return exportIndex(req);
  if (cmd === "create-note") return createNote(req);
  if (cmd === "import-md") return importMarkdown(req);
  if (cmd === "create-folder") return createFolder(req);
  if (cmd === "rename-folder") return renameFolder(req);
  if (cmd === "delete-folder") return deleteFolder(req);
  if (cmd === "edit") return editNote(req);
  if (cmd === "move") return moveNote(req);
  if (cmd === "duplicate") return duplicateNote(req);
  if (cmd === "delete-note") return deleteNote(req);
  if (cmd === "empty-trash") return emptyTrash(req);
  if (cmd === "attachments") return attachmentsCmd(req);
  if (cmd === "checklist-add") return checklistAdd(req);
  if (cmd === "share") return shareStatus(req);
  if (cmd === "open") return openNote(req);
  if (cmd === "pin" || cmd === "unpin" || cmd === "lock" || cmd === "unlock") return unsupported(cmd);
  return { ok: false, error: "unknown_command", message: String(cmd) };
}

function app() { return Application("Notes"); }

function unsupported(cmd) {
  var why = {
    pin: "Notes.app does not expose pin in its scripting dictionary (tested Notes 4.13 on macOS 27). No pinned property.",
    unpin: "Notes.app does not expose pin in its scripting dictionary (tested Notes 4.13 on macOS 27).",
    lock: "password protected is read-only. This CLI will not set a Notes password or try to lock a note.",
    unlock: "password protected is read-only. This CLI will not ask for or send the Notes password."
  };
  return { ok: false, error: "unsupported", message: why[cmd] || "not scriptable", command: cmd };
}

function iso(d) {
  try {
    if (!d) return null;
    var dt = (typeof d.getTime === "function") ? d : new Date(d);
    if (!dt || isNaN(dt.getTime())) return null;
    var t = Math.floor(dt.getTime() / 1000) * 1000;
    return new Date(t).toISOString();
  } catch (e) { return null; }
}

function asArray(value) {
  if (value === null || value === undefined) return [];
  var t = typeof value;
  if (t === "string" || t === "number" || t === "boolean") return [value];
  if (typeof value.getTime === "function") return [value];
  if (Object.prototype.toString.call(value) === "[object Array]") return value;
  if (typeof value.length === "number") {
    var out = [];
    for (var i = 0; i < value.length; i++) out.push(value[i]);
    return out;
  }
  return [value];
}

function escapeHtml(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function plainToHtml(text) {
  var lines = String(text == null ? "" : text).split(/\r?\n/);
  var html = [];
  for (var i = 0; i < lines.length; i++) html.push("<div>" + escapeHtml(lines[i]) + "</div>");
  return html.join("\n");
}

function clampLimit(value, fallback, max) {
  var n = parseInt(value, 10);
  if (!isFinite(n) || n <= 0) n = fallback;
  if (n > max) n = max;
  return n;
}

function fail(error, message) {
  return { ok: false, error: error, message: message };
}

function accountsOf(Notes) { return Notes.accounts(); }

function preferredAccount(Notes, name) {
  var accounts = accountsOf(Notes);
  if (!accounts.length) throw new Error("no Notes accounts");
  if (name) {
    for (var i = 0; i < accounts.length; i++) if (accounts[i].name() === name) return accounts[i];
    throw new Error("no account named " + name);
  }
  for (var j = 0; j < accounts.length; j++) if (accounts[j].name() === "iCloud") return accounts[j];
  try {
    var d = Notes.defaultAccount();
    if (d) return d;
  } catch (e) {}
  return accounts[0];
}

function folderParent(folder, accountId) {
  try {
    var c = folder.container();
    if (!c || c.id() === accountId) return { parent: null, parentId: null };
    return { parent: c.name(), parentId: c.id() };
  } catch (e) {
    return { parent: null, parentId: null };
  }
}

function isTrashName(name) { return name === "Recently Deleted"; }

function placeOf(Notes, note) {
  var chain = [];
  var cursor = note.container();
  var account = null;
  for (var i = 0; i < 16 && cursor; i++) {
    var id = null;
    try { id = cursor.id(); } catch (e) { break; }
    var accts = [];
    try { accts = asArray(Notes.accounts.whose({ id: { _equals: id } })()); } catch (e2) { accts = []; }
    if (accts.length && accts[0] && typeof accts[0].name === "function") {
      account = accts[0].name();
      break;
    }
    try { chain.push(cursor.name()); } catch (e3) { break; }
    try { cursor = cursor.container(); } catch (e4) { break; }
  }
  var pathNames = chain.slice().reverse();
  return {
    account: account,
    folder: chain.length ? chain[0] : null,
    parent: chain.length > 1 ? chain[1] : null,
    path: pathNames.join(" / "),
    trash: chain.length ? isTrashName(chain[0]) : false
  };
}

function findFolderObjs(Notes, name, accountName, parentName) {
  var accounts = accountsOf(Notes);
  var hits = [];
  for (var i = 0; i < accounts.length; i++) {
    var a = accounts[i];
    if (accountName && a.name() !== accountName) continue;
    var found = [];
    try { found = asArray(a.folders.whose({ name: { _equals: name } })()); } catch (e) { found = []; }
    for (var j = 0; j < found.length; j++) {
      var f = found[j];
      if (!f || typeof f.name !== "function") continue;
      var par = folderParent(f, a.id());
      if (parentName && par.parent !== parentName) continue;
      hits.push({
        folder: f,
        name: f.name(),
        id: f.id(),
        account: a.name(),
        accountObj: a,
        parent: par.parent,
        parentId: par.parentId,
        shared: safeFlag(function () { return f.shared(); }),
        trash: isTrashName(f.name())
      });
    }
  }
  return hits;
}

function safeFlag(fn) {
  try { return !!fn(); } catch (e) { return false; }
}

function requireOneFolder(hits, what) {
  if (!hits.length) return { error: fail("not_found", "no folder named " + what) };
  if (hits.length > 1) {
    var opts = [];
    for (var i = 0; i < hits.length; i++) {
      opts.push((hits[i].account || "?") + (hits[i].parent ? " / " + hits[i].parent + " / " : " / ") + hits[i].name);
    }
    return { error: fail("ambiguous", "folder name matches " + hits.length + ": " + opts.join("; ") + ". Pass --account and --parent.") };
  }
  return { hit: hits[0] };
}

function resolveNotes(Notes, req) {
  if (!req.id && !req.title) return { error: fail("missing_target", "pass --id or a title") };
  var raw = [];
  if (req.id) raw = asArray(Notes.notes.whose({ id: { _equals: req.id } })());
  else raw = asArray(Notes.notes.whose({ name: { _equals: req.title } })());
  var hits = [];
  for (var i = 0; i < raw.length; i++) {
    var n = raw[i];
    if (!n || typeof n.id !== "function") continue;
    var place = placeOf(Notes, n);
    if (req.folder && place.folder !== req.folder) continue;
    if (req.account && place.account !== req.account) continue;
    hits.push({ note: n, place: place, id: n.id(), title: n.name() });
  }
  if (!hits.length) return { error: fail("not_found", req.id ? "no note with that id" : "no note with that exact title") };
  if (hits.length > 1) {
    var opts = [];
    for (var j = 0; j < hits.length; j++) opts.push((hits[j].place.account || "?") + " / " + (hits[j].place.path || hits[j].place.folder || "?"));
    return { error: fail("ambiguous", hits.length + " notes match. Pass --id, or --folder and --account. Places: " + opts.join("; ")) };
  }
  return { hit: hits[0] };
}

function noteSummary(hit, extra) {
  var s = {
    ok: true,
    id: hit.id || hit.note.id(),
    title: hit.title || hit.note.name(),
    account: hit.place ? hit.place.account : null,
    folder: hit.place ? hit.place.folder : null,
    parent: hit.place ? hit.place.parent : null,
    path: hit.place ? hit.place.path : null
  };
  if (extra) {
    for (var k in extra) if (Object.prototype.hasOwnProperty.call(extra, k)) s[k] = extra[k];
  }
  return s;
}

function doctor() {
  var Notes = app();
  var accounts = accountsOf(Notes);
  var folderCount = 0;
  for (var i = 0; i < accounts.length; i++) folderCount += accounts[i].folders().length;
  return {
    ok: true,
    tool: "grok-notes",
    version: VERSION,
    interim: true,
    credit: "Interim local CLI until MacStories NotesCTL is public OSS. Not Club NotesCTL.",
    backend: "notes-app-jxa",
    readOnly: false,
    automation: "authorized",
    notesApp: { name: Notes.name(), id: Notes.id(), version: Notes.version() },
    accounts: accounts.length,
    folders: folderCount
  };
}

function foldersCmd() {
  var Notes = app();
  var tree = collectFolders(Notes);
  return { ok: true, accounts: tree.accounts, folders: tree.folders };
}

function collectFolders(Notes) {
  var accounts = accountsOf(Notes);
  var flat = [];
  var grouped = [];
  for (var i = 0; i < accounts.length; i++) {
    var a = accounts[i];
    var aid = a.id();
    var fl = a.folders();
    var recs = [];
    for (var j = 0; j < fl.length; j++) {
      var f = fl[j];
      var par = folderParent(f, aid);
      recs.push({
        name: f.name(),
        id: f.id(),
        parent: par.parent,
        parentId: par.parentId,
        shared: safeFlag(function () { return f.shared(); }),
        account: a.name(),
        trash: isTrashName(f.name())
      });
    }
    var byId = {};
    for (var k = 0; k < recs.length; k++) byId[recs[k].id] = recs[k];
    for (var n = 0; n < recs.length; n++) {
      recs[n].path = folderPath(recs[n], byId, 0);
      recs[n].depth = recs[n].path.split(" / ").length - 1;
      flat.push(recs[n]);
    }
    grouped.push({ account: a.name(), id: aid, folders: recs });
  }
  return { accounts: grouped, folders: flat };
}

function folderPath(rec, byId, guard) {
  if (rec._path) return rec._path;
  if (guard > 20 || !rec.parentId || !byId[rec.parentId]) {
    rec._path = rec.name;
    return rec._path;
  }
  rec._path = folderPath(byId[rec.parentId], byId, guard + 1) + " / " + rec.name;
  return rec._path;
}

function listNotes(req) {
  var folderName = req.folder || "Notes";
  var limit = clampLimit(req.limit, 50, 500);
  var Notes = app();
  var hits = findFolderObjs(Notes, folderName, req.account || null, req.parent || null);
  var groups = [];
  var total = 0;
  for (var i = 0; i < hits.length; i++) {
    var h = hits[i];
    var f = h.folder;
    var ids = [];
    var names = [];
    var mods = [];
    try { ids = asArray(f.notes.id()); } catch (e) { ids = []; }
    try { names = asArray(f.notes.name()); } catch (e2) { names = []; }
    try { mods = asArray(f.notes.modificationDate()); } catch (e3) { mods = []; }
    var count = ids.length;
    total += count;
    var take = Math.min(limit, count);
    var items = [];
    for (var n = 0; n < take; n++) {
      items.push({ title: names[n] || "", id: ids[n] || null, modified: iso(mods[n]) });
    }
    groups.push({
      account: h.account,
      folder: h.name,
      parent: h.parent,
      folderId: h.id,
      count: count,
      truncated: count > take,
      notes: items
    });
  }
  return { ok: true, folder: folderName, matches: groups.length, total: total, limit: limit, groups: groups };
}

function showNote(req) {
  var Notes = app();
  var resolved = resolveNotes(Notes, req);
  if (resolved.error) {
    if (resolved.error.error === "not_found") return { ok: true, title: req.title || null, id: req.id || null, matches: 0, notes: [] };
    return resolved.error;
  }
  var limitBody = req.full ? 0 : clampLimit(req.bodyLimit, 4000, BODY_CAP);
  var note = readNote(resolved.hit.note, resolved.hit.place, limitBody);
  return { ok: true, title: req.title || note.title, matches: 1, notes: [note] };
}

function readNote(n, place, limitBody) {
  var body = "";
  var html = "";
  var locked = false;
  var readError = null;
  try { locked = !!n.passwordProtected(); } catch (e0) { locked = false; }
  if (!locked) {
    try { body = n.plaintext() || ""; }
    catch (e) {
      var msg = String(e && e.message ? e.message : e);
      if (/lock|password|protected/i.test(msg)) locked = true;
      else readError = msg;
      body = "";
    }
    try { html = n.body() || ""; } catch (e2) { html = ""; }
  }
  var truncated = false;
  if (!locked && limitBody > 0 && body.length > limitBody) {
    body = body.slice(0, limitBody);
    truncated = true;
  }
  var atts = [];
  if (!locked) {
    try {
      var raw = asArray(n.attachments());
      for (var i = 0; i < raw.length; i++) atts.push(attachmentInfo(raw[i]));
    } catch (e3) {}
  }
  return {
    id: n.id(),
    title: n.name(),
    account: place.account,
    folder: place.folder,
    parent: place.parent,
    path: place.path,
    created: iso(safeDate(function () { return n.creationDate(); })),
    modified: iso(safeDate(function () { return n.modificationDate(); })),
    locked: locked,
    shared: safeFlag(function () { return n.shared(); }),
    readError: readError,
    truncated: truncated,
    body: locked ? null : body,
    html: locked ? null : html,
    attachments: atts
  };
}

function safeDate(fn) {
  try { return fn(); } catch (e) { return null; }
}

function attachmentInfo(a) {
  var url = null;
  try { url = a.url(); } catch (e) {
    try { url = a.URL(); } catch (e2) { url = null; }
  }
  var cid = null;
  try { cid = a.contentIdentifier(); } catch (e3) { cid = null; }
  var name = null;
  try { name = a.name(); } catch (e4) { name = null; }
  var id = null;
  try { id = a.id(); } catch (e5) { id = null; }
  return { name: name, id: id, url: url, contentId: cid };
}

function searchLive(req) {
  if (!req.query) return fail("missing_query", "search needs a query");
  var limit = clampLimit(req.limit, 20, 200);
  var Notes = app();
  var byId = {};
  function add(notes, via) {
    notes = asArray(notes);
    for (var i = 0; i < notes.length; i++) {
      var n = notes[i];
      if (!n || typeof n.id !== "function") continue;
      var id = n.id();
      var place = { folder: null, account: null, path: null };
      try { place = placeOf(Notes, n); } catch (e) {}
      if (req.folder && place.folder !== req.folder) continue;
      if (req.account && place.account !== req.account) continue;
      if (!req.includeTrash && place.folder === "Recently Deleted") continue;
      if (!byId[id]) {
        byId[id] = {
          id: id,
          title: n.name(),
          folder: place.folder,
          account: place.account,
          path: place.path,
          modified: iso(safeDate(function () { return n.modificationDate(); })),
          match: via
        };
      } else if (byId[id].match !== via) byId[id].match = "title+body";
    }
  }
  var titleHits = [];
  try { titleHits = Notes.notes.whose({ name: { _contains: req.query } })(); } catch (e) { titleHits = []; }
  add(titleHits, "title");
  var bodySearch = false;
  var bodyError = null;
  try {
    var bodyHits = Notes.notes.whose({ plaintext: { _contains: req.query } })();
    add(bodyHits, "body");
    bodySearch = true;
  } catch (e2) {
    bodyError = String(e2 && e2.message ? e2.message : e2);
  }
  var all = [];
  for (var k in byId) if (Object.prototype.hasOwnProperty.call(byId, k)) all.push(byId[k]);
  all.sort(function (a, b) {
    var am = a.modified || "";
    var bm = b.modified || "";
    if (am < bm) return 1;
    if (am > bm) return -1;
    return 0;
  });
  return {
    ok: true,
    query: req.query,
    source: "live",
    bodySearch: bodySearch,
    bodyError: bodyError,
    total: all.length,
    truncated: all.length > limit,
    limit: limit,
    notes: all.slice(0, limit)
  };
}


function exportStamp(req) {
  var t0 = Date.now();
  var Notes = app();
  var accounts = accountsOf(Notes);
  var notes = [];
  var folders = [];
  var warnings = [];
  for (var a = 0; a < accounts.length; a++) {
    var account = accounts[a];
    var accountName = account.name();
    var fl = account.folders();
    for (var j = 0; j < fl.length; j++) {
      var folder = fl[j];
      var name = folder.name();
      var fid = folder.id();
      var trash = isTrashName(name);
      folders.push({ id: fid, name: name, account: accountName, trash: trash });
      if (trash && !req.includeTrash) continue;
      var ids = [];
      var mods = [];
      var names = [];
      try { ids = asArray(folder.notes.id()); } catch (e) { warnings.push(name + ": id " + e); continue; }
      try { mods = asArray(folder.notes.modificationDate()); } catch (e2) { mods = []; }
      try { names = asArray(folder.notes.name()); } catch (e3) { names = []; }
      for (var n = 0; n < ids.length; n++) {
        notes.push({
          id: ids[n],
          title: names[n] || "",
          modified: iso(mods[n]),
          folderId: fid,
          folder: name,
          account: accountName,
          trash: trash
        });
      }
    }
  }
  return { ok: true, mode: "stamp", ms: Date.now() - t0, noteCount: notes.length, folderCount: folders.length, warnings: warnings, notes: notes, folders: folders };
}

function exportBodies(req) {
  var t0 = Date.now();
  var Notes = app();
  var ids = req.folderIds || [];
  var notes = [];
  var warnings = [];
  for (var i = 0; i < ids.length; i++) {
    var found = [];
    try { found = asArray(Notes.folders.whose({ id: { _equals: ids[i] } })()); } catch (e) { found = []; }
    if (!found.length) { warnings.push("missing folder " + ids[i]); continue; }
    var folder = found[0];
    var name = folder.name();
    if (isTrashName(name) && !req.includeTrash) continue;
    var noteIds = [];
    var names = [];
    var mods = [];
    var created = [];
    var locked = [];
    var shared = [];
    var texts = null;
    try { noteIds = asArray(folder.notes.id()); } catch (e2) { warnings.push(name + ": " + e2); continue; }
    try { names = asArray(folder.notes.name()); } catch (e3) { names = []; }
    try { mods = asArray(folder.notes.modificationDate()); } catch (e4) { mods = []; }
    try { created = asArray(folder.notes.creationDate()); } catch (e5) { created = []; }
    try { locked = asArray(folder.notes.passwordProtected()); } catch (e6) { locked = []; }
    try { shared = asArray(folder.notes.shared()); } catch (e7) { shared = []; }
    try { texts = asArray(folder.notes.plaintext()); }
    catch (e8) {
      warnings.push(name + ": plaintext bulk failed");
      texts = fetchPlainOneByOne(folder, noteIds.length, warnings, name);
    }
    for (var n = 0; n < noteIds.length; n++) {
      var isLocked = !!locked[n];
      var text = "";
      var truncated = false;
      if (!isLocked && texts) {
        text = texts[n] || "";
        if (text.length > BODY_CAP) { text = text.slice(0, BODY_CAP); truncated = true; }
      }
      var snippet = text ? String(text).replace(/\s+/g, " ").slice(0, 400) : "";
      notes.push({
        id: noteIds[n],
        title: names[n] || "",
        folder: name,
        folderId: ids[i],
        modified: iso(mods[n]),
        created: iso(created[n]),
        locked: isLocked,
        shared: !!shared[n],
        trash: isTrashName(name),
        snippet: isLocked ? "" : snippet,
        body: isLocked ? "" : text,
        bodyChars: text ? text.length : 0,
        truncated: truncated
      });
    }
  }
  return { ok: true, mode: "bodies", ms: Date.now() - t0, noteCount: notes.length, warnings: warnings, notes: notes, folders: [] };
}

function exportIndex(req) {
  var mode = req.mode || "full";
  if (mode === "stamp") return exportStamp(req);
  if (mode === "bodies") return exportBodies(req);
  var t0 = Date.now();
  var withBody = mode === "full" || mode === "bodies";
  var useFilter = mode === "bodies" && req.folderIds && req.folderIds.length;
  var idFilter = {};
  if (useFilter) for (var i = 0; i < req.folderIds.length; i++) idFilter[req.folderIds[i]] = true;
  var Notes = app();
  var packed = collectFolders(Notes);
  var folderById = {};
  for (var f = 0; f < packed.folders.length; f++) folderById[packed.folders[f].id] = packed.folders[f];
  var accounts = accountsOf(Notes);
  var notes = [];
  var warnings = [];
  for (var a = 0; a < accounts.length; a++) {
    var account = accounts[a];
    var fl = account.folders();
    for (var j = 0; j < fl.length; j++) {
      var folder = fl[j];
      var fid = folder.id();
      var meta = folderById[fid];
      if (!meta) continue;
      if (meta.trash && !req.includeTrash) continue;
      if (useFilter && !idFilter[fid]) continue;
      var ids = [];
      var names = [];
      var mods = [];
      var created = [];
      var locked = [];
      var shared = [];
      try { ids = asArray(folder.notes.id()); } catch (e) { warnings.push(meta.path + ": id " + e); continue; }
      try { names = asArray(folder.notes.name()); } catch (e2) { names = []; }
      try { mods = asArray(folder.notes.modificationDate()); } catch (e3) { mods = []; }
      try { created = asArray(folder.notes.creationDate()); } catch (e4) { created = []; }
      try { locked = asArray(folder.notes.passwordProtected()); } catch (e5) { locked = []; }
      try { shared = asArray(folder.notes.shared()); } catch (e6) { shared = []; }
      var texts = null;
      if (withBody) {
        try { texts = asArray(folder.notes.plaintext()); }
        catch (e7) {
          warnings.push(meta.account + " / " + meta.path + ": plaintext bulk failed (" + String(e7).slice(0, 160) + ")");
          texts = fetchPlainOneByOne(folder, ids.length, warnings, meta.path);
        }
      }
      var nlen = ids.length;
      for (var n = 0; n < nlen; n++) {
        var isLocked = !!locked[n];
        var text = "";
        var truncated = false;
        if (withBody && !isLocked && texts) {
          text = texts[n] || "";
          if (text.length > BODY_CAP) {
            text = text.slice(0, BODY_CAP);
            truncated = true;
          }
        }
        var snippet = "";
        if (text) snippet = String(text).replace(/\s+/g, " ").slice(0, 400);
        notes.push({
          id: ids[n],
          title: names[n] || "",
          folder: meta.name,
          folderId: fid,
          folderPath: meta.path,
          account: meta.account,
          parent: meta.parent,
          modified: iso(mods[n]),
          created: iso(created[n]),
          locked: isLocked,
          shared: !!shared[n],
          trash: !!meta.trash,
          snippet: isLocked ? "" : snippet,
          body: (withBody && !isLocked) ? text : (withBody ? "" : null),
          bodyChars: text ? text.length : 0,
          truncated: truncated
        });
      }
    }
  }
  return {
    ok: true,
    mode: mode,
    ms: Date.now() - t0,
    noteCount: notes.length,
    folderCount: packed.folders.length,
    warnings: warnings,
    notes: notes,
    folders: mode === "bodies" ? [] : packed.folders
  };
}

function fetchPlainOneByOne(folder, count, warnings, path) {
  if (count > 40) {
    warnings.push(path + ": skipped per-note plaintext (" + count + " notes)");
    return null;
  }
  var notes = [];
  try { notes = folder.notes(); } catch (e) { return null; }
  var texts = [];
  for (var i = 0; i < notes.length; i++) {
    try { texts.push(notes[i].plaintext() || ""); }
    catch (e2) { texts.push(""); }
  }
  return texts;
}

function htmlForCreate(req) {
  var title = req.title || "Untitled";
  if (req.html) return req.html;
  if (req.body) {
    var first = String(req.body).split(/\r?\n/)[0];
    if (first === title) return plainToHtml(req.body);
    return plainToHtml(title + "\n\n" + req.body);
  }
  return plainToHtml(title);
}

function importMarkdown(req) {
  if (!req.force) return fail("needs_force", "import-md requires --force");
  if (!req.title) return fail("missing_title", "import-md needs a title");
  if (!req.html) return fail("missing_body", "import-md needs note html");
  var Notes = app();
  var resolved = resolveNotes(Notes, {
    title: req.title,
    folder: req.folder || null,
    account: req.account || null,
    parent: req.parent || null
  });
  if (resolved.hit) {
    var place = resolved.hit.place || {};
    var where = (place.account || "?") + " / " + (place.path || place.folder || "?");
    return fail("already_exists", "A note titled \"" + req.title + "\" already exists (" + where + "). import-md will not change it.");
  }
  if (resolved.error && resolved.error.error !== "not_found") return resolved.error;
  var created = createNote({
    title: req.title,
    html: req.html,
    folder: req.folder || null,
    account: req.account || null,
    parent: req.parent || null,
    force: true
  });
  if (created && created.ok) created.imported = true;
  return created;
}

function createNote(req) {
  if (req.force !== true) return fail("needs_force", "create-note refuses unless force is true. Notes was not changed.");
  if (!req.title && !req.html && !req.body) return fail("missing_title", "create-note needs --title");
  var Notes = app();
  var account = preferredAccount(Notes, req.account || null);
  var dest = null;
  if (req.folder) {
    var found = requireOneFolder(findFolderObjs(Notes, req.folder, account.name(), req.parent || null), req.folder);
    if (found.error) return found.error;
    if (found.hit.trash) return fail("refused", "refusing to create a note in Recently Deleted");
    dest = found.hit;
  } else {
    var df = null;
    try { df = account.defaultFolder(); } catch (e) { df = null; }
    if (!df) return fail("not_found", "account has no default folder; pass --folder");
    dest = { folder: df, name: df.name(), account: account.name(), parent: folderParent(df, account.id()).parent };
  }
  var title = req.title || "Untitled";
  var note = Notes.make({ new: "note", at: dest.folder, withProperties: { body: htmlForCreate(req) } });
  var place = placeOf(Notes, note);
  return noteSummary({ note: note, id: note.id(), title: note.name(), place: place }, { created: true });
}

function createFolder(req) {
  if (!req.name) return fail("missing_name", "create-folder needs a name");
  if (isTrashName(req.name)) return fail("refused", "cannot create Recently Deleted");
  var Notes = app();
  var account = preferredAccount(Notes, req.account || null);
  var parentHit = null;
  if (req.parent) {
    var found = requireOneFolder(findFolderObjs(Notes, req.parent, account.name(), req.parentParent || null), req.parent);
    if (found.error) return found.error;
    parentHit = found.hit;
  }
  var parentName = parentHit ? parentHit.name : null;
  var existing = findFolderObjs(Notes, req.name, account.name(), parentName);
  var same = [];
  for (var i = 0; i < existing.length; i++) {
    if ((existing[i].parent || null) === (parentName || null)) same.push(existing[i]);
  }
  if (same.length) return fail("already_exists", "folder already exists: " + (parentName ? parentName + " / " : "") + req.name);
  var folder;
  if (parentHit) folder = Notes.make({ new: "folder", at: parentHit.folder, withProperties: { name: req.name } });
  else folder = Notes.make({ new: "folder", at: account, withProperties: { name: req.name } });
  return {
    ok: true,
    created: true,
    id: folder.id(),
    name: folder.name(),
    account: account.name(),
    parent: parentName
  };
}

function renameFolder(req) {
  if (!req.name || !req.newName) return fail("missing_name", "rename-folder needs the current name and a new name");
  if (isTrashName(req.name) || isTrashName(req.newName)) return fail("refused", "cannot rename Recently Deleted");
  var Notes = app();
  var found = requireOneFolder(findFolderObjs(Notes, req.name, req.account || null, req.parent || null), req.name);
  if (found.error) return found.error;
  found.hit.folder.name = req.newName;
  return { ok: true, id: found.hit.id, name: found.hit.folder.name(), account: found.hit.account, parent: found.hit.parent };
}

function deleteFolder(req) {
  if (!req.force) return fail("needs_force", "delete-folder requires --force");
  if (!req.name) return fail("missing_name", "delete-folder needs a name");
  if (isTrashName(req.name)) return fail("refused", "refusing to delete Recently Deleted. Use empty-trash --force to purge notes in it.");
  var Notes = app();
  var found = requireOneFolder(findFolderObjs(Notes, req.name, req.account || null, req.parent || null), req.name);
  if (found.error) return found.error;
  var f = found.hit.folder;
  var noteCount = 0;
  var subCount = 0;
  try { noteCount = f.notes().length; } catch (e) { noteCount = -1; }
  try { subCount = f.folders().length; } catch (e2) { subCount = -1; }
  var dangerous = found.hit.name === "Notes" || noteCount > 30 || subCount > 0;
  if (dangerous && !req.allowLarge) {
    return fail("needs_allow_large", "refusing to delete " + found.hit.account + " / " + (found.hit.parent ? found.hit.parent + " / " : "") + found.hit.name + " (notes=" + noteCount + ", subfolders=" + subCount + "). Re-run with --force --allow-large if you really want that folder gone.");
  }
  Notes.delete(f);
  return { ok: true, deleted: true, id: found.hit.id, name: found.hit.name, account: found.hit.account, parent: found.hit.parent, notes: noteCount, subfolders: subCount };
}

function editNote(req) {
  if (req.force !== true) return fail("needs_force", "edit refuses unless force is true. Notes was not changed.");
  var Notes = app();
  var resolved = resolveNotes(Notes, req);
  if (resolved.error) return resolved.error;
  var note = resolved.hit.note;
  if (safeFlag(function () { return note.passwordProtected(); })) return fail("locked", "note is password protected; not editing");
  if (!req.body && !req.html && !req.append && !req.rename) return fail("missing_change", "edit needs --body, --html, --append, or --rename");
  if (req.html) note.body = req.html;
  else if (req.body != null) {
    var title = req.rename || note.name() || "Untitled";
    var first = String(req.body).split(/\r?\n/)[0];
    var text = first === title ? String(req.body) : (title + "\n\n" + req.body);
    note.body = plainToHtml(text);
  }
  if (req.append) {
    var extra = plainToHtml(String(req.append));
    var cur = "";
    try { cur = note.body() || ""; } catch (e) { cur = ""; }
    note.body = cur + "\n" + extra;
  }
  if (req.rename) {
    var html = "";
    try { html = note.body() || ""; } catch (e2) { html = ""; }
    var replaced = false;
    var next = html.replace(/^(<div>)([\s\S]*?)(<\/div>)/, function (_m, a, _inner, c) {
      replaced = true;
      return a + escapeHtml(req.rename) + c;
    });
    if (replaced) note.body = next;
    else note.name = req.rename;
  }
  var place = placeOf(Notes, note);
  return noteSummary({ note: note, id: note.id(), title: note.name(), place: place }, { updated: true });
}

function moveNote(req) {
  if (!req.toFolder) return fail("missing_folder", "move needs --to-folder");
  var Notes = app();
  var resolved = resolveNotes(Notes, req);
  if (resolved.error) return resolved.error;
  var destHits = findFolderObjs(Notes, req.toFolder, req.toAccount || req.account || null, req.toParent || null);
  var dest = requireOneFolder(destHits, req.toFolder);
  if (dest.error) return dest.error;
  if (dest.hit.trash) return fail("refused", "refusing to move into Recently Deleted; delete-note instead");
  Notes.move(resolved.hit.note, { to: dest.hit.folder });
  var place = placeOf(Notes, resolved.hit.note);
  return noteSummary({ note: resolved.hit.note, id: resolved.hit.note.id(), title: resolved.hit.note.name(), place: place }, { moved: true });
}

function duplicateNote(req) {
  var Notes = app();
  var resolved = resolveNotes(Notes, req);
  if (resolved.error) return resolved.error;
  var dest = resolved.hit.note.container();
  if (req.toFolder) {
    var destHits = findFolderObjs(Notes, req.toFolder, req.toAccount || null, req.toParent || null);
    var found = requireOneFolder(destHits, req.toFolder);
    if (found.error) return found.error;
    dest = found.hit.folder;
  }
  try {
    var copy = Notes.duplicate(resolved.hit.note, { to: dest });
    var place = placeOf(Notes, copy);
    return noteSummary({ note: copy, id: copy.id(), title: copy.name(), place: place }, { duplicatedFrom: resolved.hit.id });
  } catch (e) {
    return fail("unsupported", "Notes would not duplicate this note (" + String(e && e.message ? e.message : e) + "). Duplicate is a Standard Suite command and is not reliable here.");
  }
}

function deleteNote(req) {
  if (!req.force) return fail("needs_force", "delete-note requires --force");
  var Notes = app();
  var resolved = resolveNotes(Notes, req);
  if (resolved.error) return resolved.error;
  var id = resolved.hit.id;
  var title = resolved.hit.title;
  Notes.delete(resolved.hit.note);
  var left = asArray(Notes.notes.whose({ id: { _equals: id } })());
  var inTrash = false;
  if (left.length) {
    var place = placeOf(Notes, left[0]);
    inTrash = place.folder === "Recently Deleted";
    if (req.permanent) {
      Notes.delete(left[0]);
      left = asArray(Notes.notes.whose({ id: { _equals: id } })());
    }
  }
  if (req.permanent && left.length) return fail("not_fully_deleted", "note still exists after a second delete: " + id);
  return {
    ok: true,
    deleted: left.length === 0,
    inRecentlyDeleted: left.length > 0 && inTrash,
    permanent: !!req.permanent,
    id: id,
    title: title
  };
}

function emptyTrash(req) {
  if (!req.force) return fail("needs_force", "empty-trash requires --force and permanently deletes every note in Recently Deleted");
  var Notes = app();
  var accounts = accountsOf(Notes);
  var deleted = 0;
  var folders = 0;
  for (var i = 0; i < accounts.length; i++) {
    if (req.account && accounts[i].name() !== req.account) continue;
    var found = [];
    try { found = asArray(accounts[i].folders.whose({ name: { _equals: "Recently Deleted" } })()); } catch (e) { found = []; }
    for (var j = 0; j < found.length; j++) {
      folders++;
      var notes = [];
      try { notes = found[j].notes(); } catch (e2) { notes = []; }
      for (var n = notes.length - 1; n >= 0; n--) {
        try { Notes.delete(notes[n]); deleted++; } catch (e3) {}
      }
    }
  }
  return { ok: true, deleted: deleted, folders: folders, permanent: true };
}

function attachmentsCmd(req) {
  var Notes = app();
  var resolved = resolveNotes(Notes, req);
  if (resolved.error) return resolved.error;
  var note = readNote(resolved.hit.note, resolved.hit.place, 0);
  return { ok: true, id: note.id, title: note.title, account: note.account, folder: note.folder, attachments: note.attachments || [] };
}

function checklistAdd(req) {
  if (!req.text) return fail("missing_text", "checklist add needs --text");
  var Notes = app();
  var resolved = resolveNotes(Notes, req);
  if (resolved.error) return resolved.error;
  var note = resolved.hit.note;
  if (safeFlag(function () { return note.passwordProtected(); })) return fail("locked", "note is password protected");
  var html = "";
  try { html = note.body() || ""; } catch (e) { html = ""; }
  var item = "<li>" + escapeHtml(req.text) + "</li>";
  var idx = html.lastIndexOf("</ul>");
  if (idx >= 0) html = html.slice(0, idx) + item + "\n" + html.slice(idx);
  else html = html + "\n<ul>\n" + item + "\n</ul>\n";
  note.body = html;
  var place = placeOf(Notes, note);
  var fresh = "";
  try { fresh = note.body() || ""; } catch (e2) { fresh = ""; }
  return noteSummary({ note: note, id: note.id(), title: note.name(), place: place }, { checklistAdded: req.text, html: fresh });
}

function shareStatus(req) {
  var Notes = app();
  var resolved = resolveNotes(Notes, req);
  if (resolved.error) return resolved.error;
  var note = resolved.hit.note;
  var shared = safeFlag(function () { return note.shared(); });
  var folderShared = false;
  try { folderShared = !!note.container().shared(); } catch (e) { folderShared = false; }
  return noteSummary(resolved.hit, {
    shared: shared,
    folderShared: folderShared,
    gap: "The scripting dictionary exposes shared as read-only. Starting a share, copying a collaboration link, and co-editing are not scriptable."
  });
}

function openNote(req) {
  var Notes = app();
  var resolved = resolveNotes(Notes, req);
  if (resolved.error) return resolved.error;
  try { Notes.show(resolved.hit.note); }
  catch (e) { return fail("notes_error", "could not show note: " + String(e && e.message ? e.message : e)); }
  return noteSummary(resolved.hit, { opened: true });
}
