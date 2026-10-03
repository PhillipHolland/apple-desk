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
  var Contacts = Application("Contacts");
  try {
    var result = dispatch(Contacts, payload);
    return JSON.stringify(result);
  } catch (e) {
    return JSON.stringify({
      ok: false,
      error: "contacts_error",
      message: String(e && e.message ? e.message : e)
    });
  }
}

function dispatch(app, payload) {
  var op = payload.op;
  if (op === "doctor") return doctor(app);
  if (op === "groups") return groups(app, payload.limit || 200);
  if (op === "search") return search(app, payload);
  if (op === "show") return show(app, payload);
  if (op === "create") return createPerson(app, payload);
  if (op === "update") return updatePerson(app, payload);
  if (op === "delete") return deletePerson(app, payload);
  if (op === "create-group") return createGroup(app, payload);
  if (op === "delete-group") return deleteGroup(app, payload);
  if (op === "add-to-group") return addToGroup(app, payload);
  if (op === "remove-from-group") return removeFromGroup(app, payload);
  return { ok: false, error: "bad_request", message: "Unknown op " + op };
}

function doctor(app) {
  var hasMe = false;
  try {
    var me = app.myCard();
    hasMe = !!(me && me.id && me.id());
  } catch (e) {
    hasMe = false;
  }
  var appId = null;
  try { appId = app.id(); } catch (e2) { appId = "com.apple.AddressBook"; }
  return {
    ok: true,
    automation: "authorized",
    backend: "contacts-app-jxa",
    readOnly: false,
    contactsApp: { version: String(app.version()), id: appId },
    people: app.people.length,
    groups: app.groups.length,
    hasMeCard: hasMe
  };
}

function groups(app, limit) {
  var n = app.groups.length;
  if (n === 0) return { ok: true, count: 0, groups: [] };
  var names = asList(app.groups.name());
  var ids = asList(app.groups.id());
  var rows = [];
  var cap = Math.min(n, limit);
  for (var i = 0; i < cap; i++) {
    rows.push({ id: ids[i], name: names[i] });
  }
  rows.sort(function (a, b) {
    return String(a.name || "").localeCompare(String(b.name || ""));
  });
  return { ok: true, count: n, truncated: n > cap, groups: rows };
}

function search(app, payload) {
  var q = String(payload.query || "").trim();
  if (q.length < 2) {
    return { ok: false, error: "missing_query", message: "Search needs at least 2 characters." };
  }
  var spec = app.people.whose({ _or: orClauses(q) });
  var n = spec.length;
  if (n > 200) {
    return {
      ok: false,
      error: "query_too_broad",
      count: n,
      message: "That matches " + n + " contacts. Narrow the query (names and organizations only)."
    };
  }
  if (n === 0) return { ok: true, query: q, count: 0, matches: [] };
  var names = asList(spec.name());
  var ids = asList(spec.id());
  var firsts = asList(spec.firstName());
  var lasts = asList(spec.lastName());
  var orgs = asList(spec.organization());
  var nicks = asList(spec.nickname());
  var companies = asList(spec.company());
  var rows = [];
  for (var i = 0; i < n; i++) {
    rows.push({
      id: ids[i],
      name: empty(names[i]),
      firstName: empty(firsts[i]),
      lastName: empty(lasts[i]),
      organization: empty(orgs[i]),
      nickname: empty(nicks[i]),
      company: !!companies[i]
    });
  }
  rows.sort(function (a, b) { return String(a.name || "").localeCompare(String(b.name || "")); });
  var limit = payload.limit || 20;
  return {
    ok: true,
    query: q,
    count: n,
    truncated: n > limit,
    matches: rows.slice(0, limit)
  };
}

function show(app, payload) {
  var matches;
  if (payload.id) {
    matches = asList(app.people.whose({ id: payload.id })());
    if (matches.length === 0) {
      return { ok: false, error: "not_found", message: "No contact with that id." };
    }
  } else {
    var q = String(payload.query || "").trim();
    if (!q) return { ok: false, error: "missing_target", message: "Pass a name or --id." };
    var spec = app.people.whose({ _or: orClauses(q) });
    var n = spec.length;
    if (n === 0) return { ok: false, error: "not_found", message: "No contact matched." };
    if (n > 1) {
      var preview = search(app, { query: q, limit: 20 });
      return {
        ok: false,
        error: "ambiguous",
        count: n,
        message: "More than one contact matched. Run show --id with one id.",
        matches: preview.matches || []
      };
    }
    matches = asList(spec());
  }
  var p = matches[0];
  var card = {
    id: p.id(),
    name: empty(p.name()),
    firstName: empty(p.firstName()),
    lastName: empty(p.lastName()),
    middleName: empty(p.middleName()),
    nickname: empty(p.nickname()),
    organization: empty(p.organization()),
    jobTitle: empty(p.jobTitle()),
    department: empty(p.department()),
    company: !!p.company(),
    note: clip(empty(p.note()), 2000),
    birthDate: dateOut(p.birthDate()),
    phones: labeled(p.phones),
    emails: labeled(p.emails),
    urls: labeled(p.urls),
    addresses: addressList(p),
    groups: groupsFor(app, p.id())
  };
  return { ok: true, contact: card };
}

function createPerson(app, payload) {
  if (!payload.first && !payload.last && !payload.org) {
    return { ok: false, error: "missing_name", message: "create needs --first, --last, or --org." };
  }
  var person = app.Person({
    firstName: payload.first || "",
    lastName: payload.last || "",
    organization: payload.org || ""
  });
  if (payload.middle) person.middleName = payload.middle;
  if (payload.nickname) person.nickname = payload.nickname;
  if (payload.job) person.jobTitle = payload.job;
  if (payload.department) person.department = payload.department;
  if (payload.note) person.note = payload.note;
  if (payload.company) person.company = true;
  app.people.push(person);
  pushLabeled(app, person, "phones", "Phone", payload.phones || []);
  pushLabeled(app, person, "emails", "Email", payload.emails || []);
  pushLabeled(app, person, "urls", "Url", payload.urls || []);
  var groupNames = payload.groups || [];
  for (var i = 0; i < groupNames.length; i++) {
    var g = findGroup(app, groupNames[i]);
    if (!g.ok) return g;
    app.add(person, { to: g.group });
  }
  app.save();
  return { ok: true, id: person.id(), name: empty(person.name()) };
}

function updatePerson(app, payload) {
  if (!payload.id) return { ok: false, error: "missing_target", message: "update needs --id." };
  var found = asList(app.people.whose({ id: payload.id })());
  if (found.length === 0) return { ok: false, error: "not_found", message: "No contact with that id." };
  var person = found[0];
  var changed = false;
  function setText(field, value) {
    if (value === undefined || value === null) return;
    person[field] = value;
    changed = true;
  }
  setText("firstName", payload.first);
  setText("lastName", payload.last);
  setText("middleName", payload.middle);
  setText("organization", payload.org);
  setText("nickname", payload.nickname);
  setText("jobTitle", payload.job);
  setText("department", payload.department);
  setText("note", payload.note);
  if (payload.company === true || payload.company === false) {
    person.company = payload.company;
    changed = true;
  }
  if ((payload.phones || []).length || (payload.emails || []).length || (payload.urls || []).length || (payload.removeIds || []).length) {
    changed = true;
  }
  if (!changed) return { ok: false, error: "missing_change", message: "update needs at least one field to change." };
  pushLabeled(app, person, "phones", "Phone", payload.phones || []);
  pushLabeled(app, person, "emails", "Email", payload.emails || []);
  pushLabeled(app, person, "urls", "Url", payload.urls || []);
  removeIds(app, person, payload.removeIds || []);
  var groupNames = payload.groups || [];
  for (var i = 0; i < groupNames.length; i++) {
    var g = findGroup(app, groupNames[i]);
    if (!g.ok) return g;
    app.add(person, { to: g.group });
  }
  app.save();
  return { ok: true, id: person.id(), name: empty(person.name()) };
}

function deletePerson(app, payload) {
  if (!payload.force) {
    return { ok: false, error: "needs_force", message: "delete refuses without --force. This removes the contact from Contacts." };
  }
  if (!payload.id) return { ok: false, error: "missing_target", message: "delete needs --id (not a name)." };
  var found = asList(app.people.whose({ id: payload.id })());
  if (found.length === 0) return { ok: false, error: "not_found", message: "No contact with that id." };
  var name = empty(found[0].name());
  app.delete(found[0]);
  app.save();
  return { ok: true, deleted: true, id: payload.id, name: name };
}

function createGroup(app, payload) {
  var name = String(payload.name || "").trim();
  if (!name) return { ok: false, error: "missing_name", message: "create-group needs a name." };
  var existing = app.groups.whose({ name: name });
  if (existing.length > 0) {
    return { ok: false, error: "already_exists", message: "A group named " + name + " already exists.", id: asList(existing.id())[0] };
  }
  var group = app.Group({ name: name });
  app.groups.push(group);
  app.save();
  return { ok: true, id: group.id(), name: group.name() };
}

function deleteGroup(app, payload) {
  if (!payload.force) {
    return { ok: false, error: "needs_force", message: "delete-group refuses without --force. People in the group are not deleted." };
  }
  var g = findGroup(app, payload.name, payload.id);
  if (!g.ok) return g;
  var members = g.group.people.length;
  if (members > 30 && !payload.allowLarge) {
    return {
      ok: false,
      error: "needs_allow_large",
      count: members,
      message: "That group has " + members + " people. Pass --allow-large only if you mean to delete this group. People stay in Contacts."
    };
  }
  var name = g.group.name();
  var id = g.group.id();
  app.delete(g.group);
  app.save();
  return { ok: true, deleted: true, id: id, name: name, membersKept: members };
}

function addToGroup(app, payload) {
  return membership(app, payload, true);
}

function removeFromGroup(app, payload) {
  return membership(app, payload, false);
}

function membership(app, payload, add) {
  if (!payload.id || !payload.group) {
    return { ok: false, error: "missing_target", message: "Needs --id and --group." };
  }
  var found = asList(app.people.whose({ id: payload.id })());
  if (found.length === 0) return { ok: false, error: "not_found", message: "No contact with that id." };
  var g = findGroup(app, payload.group);
  if (!g.ok) return g;
  if (add) app.add(found[0], { to: g.group });
  else app.remove(found[0], { from: g.group });
  app.save();
  return { ok: true, id: payload.id, group: g.group.name(), added: add };
}

function findGroup(app, name, id) {
  if (id) {
    var byId = asList(app.groups.whose({ id: id })());
    if (byId.length === 0) return { ok: false, error: "not_found", message: "No group with that id." };
    return { ok: true, group: byId[0] };
  }
  var q = String(name || "").trim();
  if (!q) return { ok: false, error: "missing_name", message: "Name a group." };
  var exact = asList(app.groups.whose({ name: q })());
  if (exact.length === 1) return { ok: true, group: exact[0] };
  if (exact.length > 1) {
    return { ok: false, error: "ambiguous", message: "More than one group is named " + q + ". Pass --id." };
  }
  return { ok: false, error: "not_found", message: "No group named " + q + "." };
}

function groupsFor(app, personId) {
  var n = app.groups.length;
  if (n === 0 || n > 80) return [];
  var found = [];
  var groups = asList(app.groups());
  for (var i = 0; i < groups.length; i++) {
    try {
      var hit = groups[i].people.whose({ id: personId });
      if (hit.length > 0) found.push({ id: groups[i].id(), name: groups[i].name() });
    } catch (e) {}
  }
  return found;
}

function pushLabeled(app, person, collection, ctor, rows) {
  for (var i = 0; i < rows.length; i++) {
    var row = rows[i];
    var obj = app[ctor]({ label: labelIn(row.label), value: row.value });
    person[collection].push(obj);
  }
}

function removeIds(app, person, ids) {
  if (!ids.length) return;
  var want = {};
  for (var i = 0; i < ids.length; i++) want[ids[i]] = true;
  ["phones", "emails", "urls", "addresses"].forEach(function (collection) {
    var items = [];
    try { items = asList(person[collection]()); } catch (e) { items = []; }
    for (var j = 0; j < items.length; j++) {
      try {
        if (want[items[j].id()]) app.delete(items[j]);
      } catch (e2) {}
    }
  });
}

function labeled(collection) {
  var items = [];
  try { items = asList(collection()); } catch (e) { return []; }
  var out = [];
  for (var i = 0; i < items.length; i++) {
    out.push({
      id: items[i].id(),
      label: labelOut(empty(items[i].label())),
      value: empty(items[i].value())
    });
  }
  return out;
}

function addressList(person) {
  var items = [];
  try { items = asList(person.addresses()); } catch (e) { return []; }
  var out = [];
  for (var i = 0; i < items.length; i++) {
    var a = items[i];
    out.push({
      id: a.id(),
      label: labelOut(empty(a.label())),
      street: empty(a.street()),
      city: empty(a.city()),
      state: empty(a.state()),
      zip: empty(a.zip()),
      country: empty(a.country()),
      countryCode: empty(a.countryCode()),
      formatted: empty(a.formattedAddress())
    });
  }
  return out;
}

var LABEL_OUT = {
  "_$!<Mobile>!$_": "mobile",
  "_$!<Home>!$_": "home",
  "_$!<Work>!$_": "work",
  "_$!<Main>!$_": "main",
  "_$!<Other>!$_": "other",
  "_$!<HomePage>!$_": "homepage",
  "_$!<School>!$_": "school",
  "_$!<iPhone>!$_": "iPhone",
  "_$!<AppleWatch>!$_": "Apple Watch",
  "_$!<HomeFAX>!$_": "home fax",
  "_$!<WorkFAX>!$_": "work fax",
  "_$!<Pager>!$_": "pager",
  "_$!<Parent>!$_": "parent",
  "_$!<Brother>!$_": "brother",
  "_$!<Sister>!$_": "sister",
  "_$!<Child>!$_": "child",
  "_$!<Friend>!$_": "friend",
  "_$!<Spouse>!$_": "spouse",
  "_$!<Partner>!$_": "partner",
  "_$!<Assistant>!$_": "assistant",
  "_$!<Manager>!$_": "manager",
  "_$!<Anniversary>!$_": "anniversary"
};

var LABEL_IN = {
  mobile: "_$!<Mobile>!$_",
  home: "_$!<Home>!$_",
  work: "_$!<Work>!$_",
  main: "_$!<Main>!$_",
  other: "_$!<Other>!$_",
  homepage: "_$!<HomePage>!$_",
  school: "_$!<School>!$_",
  iphone: "_$!<iPhone>!$_",
  pager: "_$!<Pager>!$_"
};

function labelOut(s) {
  if (!s) return null;
  return LABEL_OUT[s] || s;
}

function labelIn(s) {
  var key = String(s || "other").toLowerCase();
  return LABEL_IN[key] || s || "_$!<Other>!$_";
}

function orClauses(q) {
  var values = variants(q);
  var props = ["name", "firstName", "lastName", "organization", "nickname"];
  var ors = [];
  for (var p = 0; p < props.length; p++) {
    for (var v = 0; v < values.length; v++) {
      var clause = {};
      clause[props[p]] = { _contains: values[v] };
      ors.push(clause);
    }
  }
  return ors;
}

function variants(q) {
  var set = {};
  var titled = q.charAt(0).toUpperCase() + q.slice(1).toLowerCase();
  [q, q.toLowerCase(), q.toUpperCase(), titled].forEach(function (v) {
    if (v) set[v] = 1;
  });
  return Object.keys(set);
}

function asList(v) {
  if (v === null || v === undefined) return [];
  if (Object.prototype.toString.call(v) === "[object Array]") return v;
  return [v];
}

function empty(v) {
  if (v === null || v === undefined) return null;
  var s = String(v);
  if (!s || s === "missing value" || s === "undefined") return null;
  return s;
}

function clip(s, n) {
  if (!s) return null;
  if (s.length <= n) return s;
  return s.slice(0, n) + "…";
}

function dateOut(d) {
  try {
    if (d === null || d === undefined) return null;
    var s = String(d);
    if (!s || s === "missing value") return null;
    if (d.toISOString) return d.toISOString();
    return s;
  } catch (e) {
    return null;
  }
}
