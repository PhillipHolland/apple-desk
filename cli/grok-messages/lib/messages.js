// Messages.app JXA. Doctor, resolve, and send. No message bodies are read here.
// Person sends go to a participant (1:1). A chat send happens only for an explicit guid.
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
  var Messages = Application("Messages");
  var op = payload.op;

  function fail(error, message, extra) {
    var body = {ok: false, error: error, message: message};
    if (extra) {
      for (var k in extra) {
        if (Object.prototype.hasOwnProperty.call(extra, k)) body[k] = extra[k];
      }
    }
    return JSON.stringify(body);
  }

  function normHandle(value) {
    var raw = String(value || "").trim();
    if (!raw) return "";
    if (raw.indexOf("@") !== -1) return raw.toLowerCase();
    var digits = "";
    for (var i = 0; i < raw.length; i++) {
      var ch = raw.charAt(i);
      if (ch >= "0" && ch <= "9") digits += ch;
    }
    if (raw.charAt(0) === "+" && digits) return "+" + digits;
    if (digits.length === 10) return "+1" + digits;
    if (digits.length === 11 && digits.charAt(0) === "1") return "+" + digits;
    return raw;
  }

  function sameHandle(a, b) {
    if (!a || !b) return false;
    if (String(a) === String(b)) return true;
    var na = normHandle(a);
    var nb = normHandle(b);
    return na !== "" && na === nb;
  }

  function serviceName(account) {
    try { return String(account.serviceType()); }
    catch (e) { return ""; }
  }

  function matchesService(name, wanted) {
    if (!wanted) return true;
    return String(name || "").toLowerCase() === String(wanted).toLowerCase();
  }

  function participantRecord(participant, service) {
    var handle = "";
    var id = "";
    var name = "";
    try { handle = String(participant.handle()); } catch (e) { handle = ""; }
    try { id = String(participant.id()); } catch (e2) { id = ""; }
    try { name = String(participant.name() || ""); } catch (e3) { name = ""; }
    return {participant: participant, service: service || "", handle: handle, id: id, name: name};
  }

  function findParticipants(handle, service) {
    var out = [];
    var accounts;
    try { accounts = Messages.accounts; }
    catch (e) { return out; }
    var n = accounts.length;
    for (var i = 0; i < n; i++) {
      var account = accounts[i];
      var st = serviceName(account);
      if (!matchesService(st, service)) continue;
      var parts;
      try { parts = account.participants; }
      catch (e2) { continue; }
      var pn = parts.length;
      for (var j = 0; j < pn; j++) {
        var rec = participantRecord(parts[j], st);
        if (sameHandle(rec.handle, handle)) out.push(rec);
      }
    }
    return out;
  }

  function rankService(name) {
    var key = String(name || "");
    if (key === "iMessage") return 0;
    if (key === "RCS") return 1;
    if (key === "SMS") return 2;
    return 9;
  }

  function pickParticipant(cands) {
    if (!cands.length) return null;
    var best = cands[0];
    for (var i = 1; i < cands.length; i++) {
      if (rankService(cands[i].service) < rankService(best.service)) best = cands[i];
    }
    return best;
  }

  function findChat(chatId) {
    var n = Messages.chats.length;
    for (var i = 0; i < n; i++) {
      var chat = Messages.chats[i];
      try {
        if (String(chat.id()) === chatId) return chat;
      } catch (e) {}
    }
    return null;
  }

  function otherParticipantCount(chat) {
    try { return chat.participants.length; }
    catch (e) { return -1; }
  }

  function chatIsGroup(chat) {
    var id = "";
    try { id = String(chat.id()); } catch (e) { id = ""; }
    if (id.indexOf(";+;") !== -1) return true;
    var count = otherParticipantCount(chat);
    if (count > 1) return true;
    return false;
  }

  function chatSummary(chat) {
    var id = "";
    var name = "";
    try { id = String(chat.id()); } catch (e) { id = ""; }
    try { name = String(chat.name() || ""); } catch (e2) { name = ""; }
    var count = otherParticipantCount(chat);
    return {
      chatId: id,
      name: name || null,
      participantCount: count,
      group: chatIsGroup(chat)
    };
  }

  if (op === "doctor") {
    var accountCount = 0;
    try { accountCount = Messages.accounts.length; } catch (e) { accountCount = null; }
    return JSON.stringify({
      ok: true,
      name: Messages.name(),
      version: Messages.version(),
      scriptingChatCount: Messages.chats.length,
      accountCount: accountCount
    });
  }

  if (op === "resolve_participant") {
    var handle = String(payload.handle || "");
    if (!handle) return fail("bad_request", "resolve_participant needs a handle");
    var found = findParticipants(handle, payload.service || null);
    var picked = pickParticipant(found);
    if (!picked) {
      return JSON.stringify({
        ok: true,
        found: false,
        handle: normHandle(handle),
        candidateCount: 0
      });
    }
    return JSON.stringify({
      ok: true,
      found: true,
      handle: normHandle(picked.handle),
      service: picked.service,
      participantId: picked.id,
      candidateCount: found.length
    });
  }

  if (op === "resolve_chat") {
    var lookId = String(payload.chatId || "");
    if (!lookId) return fail("bad_request", "resolve_chat needs a chat id");
    var looked = findChat(lookId);
    if (!looked) {
      return JSON.stringify({
        ok: true,
        found: false,
        chatId: lookId,
        message: "That chat is not in the Messages scripting list."
      });
    }
    var summary = chatSummary(looked);
    summary.ok = true;
    summary.found = true;
    return JSON.stringify(summary);
  }

  if (op === "send_participant") {
    var text = payload.text;
    var who = String(payload.handle || "");
    if (!who || typeof text !== "string" || text.length === 0) {
      return fail("bad_request", "send_participant needs a person handle and text. Nothing was sent.");
    }
    var cands = findParticipants(who, payload.service || null);
    var buddy = pickParticipant(cands);
    if (buddy) {
      try {
        Messages.send(text, {to: buddy.participant});
      } catch (e) {
        return fail(
          "messages_error",
          "Messages refused the 1:1 participant send. Nothing else was retried. " + String(e && e.message ? e.message : e)
        );
      }
      return JSON.stringify({
        ok: true,
        sent: true,
        route: "participant",
        handle: normHandle(buddy.handle),
        service: buddy.service,
        participantId: buddy.id
      });
    }

    // No participant object. Fall back only to a proven 1:1 chat, never a group.
    var directId = String(payload.directChatId || "");
    if (!directId) {
      return fail(
        "not_in_messages_ui",
        "No Messages participant matches that handle, and there is no 1:1 chat to use. Nothing was sent. A group that merely contains the handle is not a target."
      );
    }
    var direct = findChat(directId);
    if (!direct) {
      return fail(
        "not_in_messages_ui",
        "No Messages participant matches that handle, and the 1:1 chat is not in the scripting list. Nothing was sent."
      );
    }
    if (chatIsGroup(direct)) {
      var g = chatSummary(direct);
      return fail(
        "refusing_group",
        "Refusing to send. The only scripting chat for that handle is a group (" + (g.name || g.chatId) + "). Nothing was sent. Pass --chat-guid to message that group on purpose.",
        {chatId: g.chatId, name: g.name, participantCount: g.participantCount}
      );
    }
    try {
      Messages.send(text, {to: direct});
    } catch (e2) {
      return fail(
        "messages_error",
        "Messages refused the 1:1 chat send. Nothing else was retried. " + String(e2 && e2.message ? e2.message : e2)
      );
    }
    var sentSummary = chatSummary(direct);
    return JSON.stringify({
      ok: true,
      sent: true,
      route: "direct_chat",
      chatId: sentSummary.chatId,
      name: sentSummary.name,
      participantCount: sentSummary.participantCount,
      group: false
    });
  }

  if (op === "send_chat") {
    var chatId = String(payload.chatId || "");
    var body = payload.text;
    if (!chatId || typeof body !== "string" || body.length === 0) {
      return fail("bad_request", "send_chat needs a chat guid and text. Nothing was sent.");
    }
    var target = findChat(chatId);
    if (!target) {
      return fail(
        "not_in_messages_ui",
        "That chat is not in the Messages scripting list, so nothing was sent. Unknown-sender and junk chats are often missing there. Open the chat in Messages once and retry. Nothing was sent."
      );
    }
    var info = chatSummary(target);
    try {
      Messages.send(body, {to: target});
    } catch (e3) {
      return fail(
        "messages_error",
        "Messages refused the send. Nothing else was retried. " + String(e3 && e3.message ? e3.message : e3)
      );
    }
    return JSON.stringify({
      ok: true,
      sent: true,
      route: "chat",
      chatId: info.chatId,
      name: info.name,
      participantCount: info.participantCount,
      group: info.group
    });
  }

  // Legacy op used to send to whatever chat id was resolved, including groups. It does not send.
  if (op === "send") {
    return fail(
      "bad_request",
      "The old chat-id send is disabled. Use send_participant for a person or send_chat with an explicit guid. Nothing was sent."
    );
  }

  return fail("bad_request", "unknown op");
}
