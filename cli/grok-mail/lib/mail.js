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
  if (payload.op === "send" || payload.send) {
    return JSON.stringify({ ok: false, error: "unsupported", message: "grok-mail 0.1.0 does not send mail." });
  }
  var Mail = Application("Mail");
  try {
    return JSON.stringify(dispatch(Mail, payload));
  } catch (e) {
    var msg = String(e && e.message ? e.message : e);
    var err = "mail_error";
    if (msg.indexOf("-1743") !== -1 || msg.indexOf("Not authorized") !== -1) err = "automation_denied";
    if (msg.indexOf("-1712") !== -1 || msg.toLowerCase().indexOf("timed out") !== -1) err = "automation_timeout";
    return JSON.stringify({ ok: false, error: err, message: msg });
  }
}

function dispatch(app, payload) {
  var op = payload.op;
  if (op === "doctor") return doctor(app);
  if (op === "accounts") return accounts(app);
  if (op === "mailboxes") return mailboxes(app, payload);
  if (op === "list") return listMessages(app, payload);
  if (op === "show") return showMessage(app, payload);
  if (op === "search") return searchMessages(app, payload);
  if (op === "draft") return draftMessage(app, payload);
  return { ok: false, error: "bad_request", message: "Unknown op " + op };
}

function doctor(app) {
  var accs = asList(app.accounts());
  var names = [];
  for (var i = 0; i < accs.length; i++) names.push(empty(safe(function () { return accs[i].name(); }, null)));
  return {
    ok: true,
    automation: "authorized",
    backend: "mail-app-jxa",
    readOnlyDefault: true,
    sends: false,
    mailApp: {
      version: String(app.version()),
      id: safe(function () { return app.id(); }, "com.apple.mail")
    },
    accounts: accs.length,
    accountNames: names,
    inboxUnread: safe(function () { return app.inbox().unreadCount(); }, null)
  };
}

function accounts(app) {
  var accs = asList(app.accounts());
  var rows = [];
  for (var i = 0; i < accs.length; i++) {
    var acc = accs[i];
    rows.push({
      id: empty(safe(function () { return acc.id(); }, null)),
      name: empty(safe(function () { return acc.name(); }, null)),
      accountType: empty(safe(function () { return String(acc.accountType()); }, null)),
      enabled: !!safe(function () { return acc.enabled(); }, false),
      fullName: empty(safe(function () { return acc.fullName(); }, null)),
      emails: emailsOf(acc)
    });
  }
  rows.sort(function (a, b) { return String(a.name || "").localeCompare(String(b.name || "")); });
  return { ok: true, count: rows.length, accounts: rows };
}

function emailsOf(acc) {
  var raw = safe(function () { return acc.emailAddresses(); }, []);
  var list = asList(raw);
  var out = [];
  for (var i = 0; i < list.length; i++) {
    var value = empty(list[i]);
    if (value) out.push(value);
  }
  return out;
}

function mailboxes(app, payload) {
  var accs = selectedAccounts(app, payload.account);
  if (!accs.ok) return accs;
  var rows = [];
  var cap = 300;
  for (var i = 0; i < accs.accounts.length; i++) {
    var acc = accs.accounts[i];
    var accountName = empty(safe(function () { return acc.name(); }, null));
    walkMailboxes(safe(function () { return acc.mailboxes(); }, []), accountName, 0, rows, cap);
  }
  return { ok: true, count: rows.length, truncated: rows.length >= cap, mailboxes: rows };
}

function walkMailboxes(nodes, accountName, depth, out, cap) {
  if (out.length >= cap || depth > 8) return;
  var list = asList(nodes);
  for (var i = 0; i < list.length; i++) {
    if (out.length >= cap) return;
    var mb = list[i];
    var name = empty(safe(function () { return mb.name(); }, null));
    out.push({
      name: name,
      account: accountName,
      unread: safe(function () { return mb.unreadCount(); }, null),
      depth: depth
    });
    var kids = safe(function () { return mb.mailboxes(); }, []);
    walkMailboxes(kids, accountName, depth + 1, out, cap);
  }
}

function listMessages(app, payload) {
  var found = resolveMailbox(app, payload.mailbox || "INBOX", payload.account);
  if (!found.ok) return found;
  var limit = clamp(payload.limit, 20);
  var spec = found.mailbox.messages;
  var n = 0;
  try { n = spec.length; }
  catch (e) { return { ok: false, error: "mail_error", message: "Could not count " + found.name + ": " + e }; }
  var take = Math.min(n, limit);
  var rows = [];
  for (var k = 0; k < take; k++) {
    var msg = spec[n - 1 - k];
    rows.push(summaryOf(msg, found));
  }
  return {
    ok: true,
    mailbox: found.name,
    account: found.account,
    mailboxCount: n,
    count: rows.length,
    returned: rows.length,
    truncated: n > limit,
    messages: rows
  };
}

function searchMessages(app, payload) {
  var q = String(payload.query || "").trim();
  if (q.length < 2) return { ok: false, error: "missing_query", message: "Search needs at least 2 characters." };
  var found = resolveMailbox(app, payload.mailbox || "INBOX", payload.account);
  if (!found.ok) return found;
  var limit = clamp(payload.limit, 20);
  var spec = whoseSubjectOrSender(found.mailbox, q);
  if (!spec.ok) return spec;
  var n = spec.count;
  if (n > 300) {
    return {
      ok: false,
      error: "query_too_broad",
      count: n,
      mailbox: found.name,
      message: "That query matches " + n + " messages in " + found.name + ". Narrow the query or the mailbox. Bodies were not read."
    };
  }
  var take = Math.min(n, limit);
  var rows = [];
  for (var i = 0; i < take; i++) rows.push(summaryOf(spec.messages[i], found));
  return {
    ok: true,
    query: q,
    mailbox: found.name,
    account: found.account,
    count: n,
    returned: rows.length,
    truncated: n > limit,
    messages: rows
  };
}

function whoseSubjectOrSender(mailbox, q) {
  var spec = null;
  try {
    spec = mailbox.messages.whose({
      _or: [
        { subject: { _contains: q } },
        { sender: { _contains: q } }
      ]
    });
    return { ok: true, count: spec.length, messages: spec };
  } catch (e) {
    spec = null;
  }
  var merged = [];
  var seen = {};
  var pieces = [];
  try { pieces.push(mailbox.messages.whose({ subject: { _contains: q } })); } catch (e1) {}
  try { pieces.push(mailbox.messages.whose({ sender: { _contains: q } })); } catch (e2) {}
  if (!pieces.length) {
    return { ok: false, error: "mail_error", message: "Mail refused a subject/sender search in this mailbox." };
  }
  for (var p = 0; p < pieces.length; p++) {
    var one = pieces[p];
    var n = 0;
    try { n = one.length; } catch (e3) { continue; }
    if (n > 300) return { ok: true, count: n, messages: one };
    for (var i = 0; i < n; i++) {
      var id = safe(function () { return one[i].id(); }, null);
      var key = String(id);
      if (seen[key]) continue;
      seen[key] = true;
      merged.push(one[i]);
    }
  }
  return { ok: true, count: merged.length, messages: merged };
}

function showMessage(app, payload) {
  var id = Number(payload.id);
  if (!id && id !== 0) return { ok: false, error: "missing_target", message: "show needs --id." };
  var places = [];
  if (payload.mailbox) {
    var found = resolveMailbox(app, payload.mailbox, payload.account);
    if (!found.ok) return found;
    places.push(found);
  } else {
    places = candidateMailboxes(app);
  }
  var checked = 0;
  for (var i = 0; i < places.length; i++) {
    if (checked >= 40) break;
    checked++;
    var hit = messageById(places[i], id);
    if (hit) return { ok: true, message: detailOf(hit, places[i]) };
  }
  return {
    ok: false,
    error: "not_found",
    message: "No message with id " + id + (payload.mailbox ? " in " + payload.mailbox : " in the mailboxes checked") + ". Pass --mailbox if it lives elsewhere. Checked " + checked + "."
  };
}

function candidateMailboxes(app) {
  var out = [];
  function add(mb, name) {
    if (!mb) return;
    out.push({ mailbox: mb, name: name, account: null });
  }
  add(safe(function () { return app.inbox(); }, null), "INBOX");
  add(safe(function () { return app.draftsMailbox(); }, null), "Drafts");
  add(safe(function () { return app.sentMailbox(); }, null), "Sent");
  add(safe(function () { return app.junkMailbox(); }, null), "Junk");
  add(safe(function () { return app.trashMailbox(); }, null), "Trash");
  var accs = asList(safe(function () { return app.accounts(); }, []));
  for (var i = 0; i < accs.length && out.length < 40; i++) {
    var boxes = asList(safe(function () { return accs[i].mailboxes(); }, []));
    var accountName = empty(safe(function () { return accs[i].name(); }, null));
    for (var j = 0; j < boxes.length && out.length < 40; j++) {
      out.push({
        mailbox: boxes[j],
        name: empty(safe(function () { return boxes[j].name(); }, null)),
        account: accountName
      });
    }
  }
  return out;
}

function messageById(place, id) {
  try {
    var spec = place.mailbox.messages.whose({ id: id });
    if (spec.length < 1) {
      spec = place.mailbox.messages.whose({ id: { _equals: id } });
    }
    if (!spec || spec.length < 1) return null;
    return spec[0];
  } catch (e) {
    return null;
  }
}

function draftMessage(app, payload) {
  if (!payload.force) {
    return { ok: false, error: "needs_force", message: "draft refuses without --force. Nothing was created." };
  }
  var to = String(payload.to || "").trim();
  var subject = payload.subject == null ? "" : String(payload.subject);
  if (!to) return { ok: false, error: "missing_to", message: "draft needs --to." };
  if (!subject) return { ok: false, error: "missing_subject", message: "draft needs --subject." };
  var msg = app.OutgoingMessage({
    subject: subject,
    content: payload.body == null ? "" : String(payload.body),
    visible: false
  });
  app.outgoingMessages.push(msg);
  msg.toRecipients.push(app.ToRecipient({ address: to }));
  try { msg.save(); }
  catch (e) {
    return { ok: false, error: "mail_error", message: "Draft was not saved: " + e };
  }
  return {
    ok: true,
    created: true,
    sent: false,
    id: safe(function () { return msg.id(); }, null),
    to: to,
    subject: subject
  };
}

function resolveMailbox(app, name, account) {
  var wanted = String(name || "INBOX").trim();
  var key = wanted.toLowerCase();
  var specials = {
    "inbox": "inbox",
    "in": "inbox",
    "drafts": "draftsMailbox",
    "draft": "draftsMailbox",
    "sent": "sentMailbox",
    "sent messages": "sentMailbox",
    "junk": "junkMailbox",
    "junk mail": "junkMailbox",
    "trash": "trashMailbox",
    "outbox": "outbox"
  };
  if (!account && specials[key]) {
    var mb = specialMailbox(app, specials[key]);
    if (!mb) return { ok: false, error: "not_found", message: "Mail has no " + wanted + " mailbox." };
    return { ok: true, mailbox: mb, name: wanted, account: null };
  }
  var accs = selectedAccounts(app, account);
  if (!accs.ok) return accs;
  var hits = [];
  for (var i = 0; i < accs.accounts.length; i++) {
    var acc = accs.accounts[i];
    var accountName = empty(safe(function () { return acc.name(); }, null));
    collectBoxes(safe(function () { return acc.mailboxes(); }, []), accountName, "", hits, 400);
  }
  var folded = key;
  var exact = [];
  for (var j = 0; j < hits.length; j++) {
    if (hits[j].name.toLowerCase() === folded || hits[j].path.toLowerCase() === folded) exact.push(hits[j]);
  }
  if (exact.length === 1) {
    return { ok: true, mailbox: exact[0].mailbox, name: exact[0].path || exact[0].name, account: exact[0].account };
  }
  if (exact.length > 1) {
    return {
      ok: false,
      error: "ambiguous",
      message: "More than one mailbox is named " + wanted + ". Pass --account.",
      matches: exact.map(function (h) { return { name: h.path || h.name, account: h.account }; })
    };
  }
  return { ok: false, error: "not_found", message: "No mailbox named " + wanted + "." };
}

function specialMailbox(app, method) {
  return safe(function () { return app[method](); }, null);
}

function collectBoxes(nodes, accountName, parent, out, cap) {
  if (out.length >= cap) return;
  var list = asList(nodes);
  for (var i = 0; i < list.length; i++) {
    if (out.length >= cap) return;
    var mb = list[i];
    var name = empty(safe(function () { return mb.name(); }, "")) || "";
    var path = parent ? parent + "/" + name : name;
    out.push({ mailbox: mb, name: name, path: path, account: accountName });
    collectBoxes(safe(function () { return mb.mailboxes(); }, []), accountName, path, out, cap);
  }
}

function selectedAccounts(app, name) {
  var accs = asList(app.accounts());
  if (!name) return { ok: true, accounts: accs };
  var q = String(name).trim().toLowerCase();
  var exact = [];
  for (var i = 0; i < accs.length; i++) {
    var n = empty(safe(function () { return accs[i].name(); }, "")) || "";
    if (n.toLowerCase() === q) exact.push(accs[i]);
  }
  if (exact.length === 1) return { ok: true, accounts: exact };
  if (!exact.length) return { ok: false, error: "not_found", message: "No account named " + name + "." };
  return { ok: false, error: "ambiguous", message: "More than one account is named " + name + "." };
}

function summaryOf(msg, found) {
  return {
    id: safe(function () { return msg.id(); }, null),
    subject: clip(empty(safe(function () { return msg.subject(); }, null)) || "(no subject)", 180),
    sender: clip(empty(safe(function () { return msg.sender(); }, null)), 180),
    dateReceived: formatLocal(safe(function () { return msg.dateReceived(); }, null)),
    dateSent: formatLocal(safe(function () { return msg.dateSent(); }, null)),
    read: !!safe(function () { return msg.readStatus(); }, false),
    flagged: !!safe(function () { return msg.flaggedStatus(); }, false),
    mailbox: found.name || null
  };
}

function detailOf(msg, found) {
  var row = summaryOf(msg, found);
  row.account = found.account || null;
  var body = empty(safe(function () { return String(msg.content()); }, null)) || "";
  row.bodyTruncated = body.length > 1200;
  row.body = body.length > 1200 ? body.slice(0, 1200) : body;
  row.to = recipientBrief(msg, "toRecipients");
  row.cc = recipientBrief(msg, "ccRecipients");
  return row;
}

function recipientBrief(msg, key) {
  try {
    var spec = msg[key];
    var n = spec.length;
    var take = Math.min(n, 8);
    var rows = [];
    for (var i = 0; i < take; i++) {
      rows.push({
        name: empty(safe(function () { return spec[i].name(); }, null)),
        address: empty(safe(function () { return spec[i].address(); }, null))
      });
    }
    return { count: n, truncated: n > 8, recipients: rows };
  } catch (e) {
    return { count: 0, truncated: false, recipients: [] };
  }
}

function clamp(n, fallback) {
  n = Number(n || fallback || 20);
  if (!n || n < 1) return 1;
  if (n > 50) return 50;
  return n;
}

function asList(v) {
  if (v === null || v === undefined) return [];
  var tag = Object.prototype.toString.call(v);
  if (tag === "[object Array]") return v;
  if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") return [v];
  try {
    if (typeof v.length === "number") {
      var out = [];
      for (var i = 0; i < v.length; i++) out.push(v[i]);
      return out;
    }
  } catch (e) {}
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
  return s.slice(0, n);
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
