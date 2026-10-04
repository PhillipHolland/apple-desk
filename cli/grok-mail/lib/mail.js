/* Apple Desk Mail bridge. Fixed code; requests are private UTF-8 JSON files.
 * No Mail database access and no executable interpolation of message contents. */
ObjC.import('Foundation');
ObjC.import('AppKit');
var MP='mailmsg:v1:', BP='mailbox:v1:', AP='mailatt:v1:', CP='mailcursor:v2:';
var sendStarted=false;
function fail(code,message,details){var e=new Error(message);e.code=code;e.details=details;throw e;}
function has(o,k){return Object.prototype.hasOwnProperty.call(o,k);}
function opt(r,k,d){return has(r.options||{},k)?r.options[k]:d;}
function flag(r,k){return (r.flags||[]).indexOf(k)>=0;}
function txt(v){return v===null||v===undefined?'':String(v);}
function enc(p,v){return p+encodeURIComponent(JSON.stringify(v));}
function dec(p,s){if(typeof s!=='string'||s.indexOf(p)!==0||s.length>32768)fail('INVALID_REFERENCE','Use a reference returned by apple-desk.');try{return JSON.parse(decodeURIComponent(s.slice(p.length)));}catch(e){fail('INVALID_REFERENCE','Malformed reference.');}}
function integer(v,d,min,max,n){if(v===undefined)return d;if(!/^-?\d+$/.test(String(v))||Number(v)<min||Number(v)>max)fail('INVALID_INPUT',n+' must be '+min+'..'+max+'.');return Number(v);}
function optional(fn,d){try{var v=fn();return v===null||v===undefined?d:v;}catch(e){if([-1712,-1743,-600].indexOf(Number(e.errorNumber))>=0)throw e;return d;}}
function iso(v){if(!v)return null;var d=new Date(v);return isFinite(d.getTime())?d.toISOString():null;}
function capped(v,n){var s=txt(v),end=Math.min(n,s.length);if(end<s.length&&/[\uD800-\uDBFF]/.test(s.charAt(end-1)))end--;return{text:s.slice(0,end),truncated:end<s.length,originalCharacters:s.length,returnedCharacters:end};}
function count(c,max){var n=Number(c.length);if(!Number.isSafeInteger(n)||n<0)fail('BACKEND_ERROR','Invalid collection count.');if(max!==null&&n>max)fail('LIMIT_EXCEEDED','Collection is too large.',{count:n,maximum:max});return n;}
function pathOK(p){return Array.isArray(p)&&p.length>0&&p.length<=40&&p.every(function(s){return typeof s==='string'&&s.length>0&&s.length<=2048;});}
function boxRef(a,p){return enc(BP,{accountID:a,path:p});}
function messageRef(a,p,id,rfc){return enc(MP,{accountID:a,mailboxPath:p,id:id,messageID:rfc});}
function parseMessage(s){var v=dec(MP,s);if(!v||typeof v.accountID!=='string'||!v.accountID||!pathOK(v.mailboxPath)||!Number.isSafeInteger(v.id)||v.id<0||typeof v.messageID!=='string')fail('INVALID_REFERENCE','Invalid message reference.');return v;}
function mailboxIdentity(a,v){if(typeof a!=='string'||!a)fail('INVALID_INPUT','Supply --account ID (or unique account name).');if(typeof v!=='string'||!v)fail('INVALID_INPUT','Supply --mailbox reference or exact path.');var p;if(v.indexOf(BP)===0){var b=dec(BP,v);if(!b||b.accountID!==a||!pathOK(b.path))fail('INVALID_REFERENCE','Mailbox reference must match the account ID.');p=b.path;}else{p=v.split('/');if(!pathOK(p))fail('INVALID_INPUT','Invalid mailbox path.');}return{accountID:a,path:p,ref:boxRef(a,p)};}
function resolveAccount(mail,selector){if(typeof selector!=='string'||!selector)fail('INVALID_INPUT','Supply --account ID or unique name.');var byID=mail.accounts.byId(selector);try{if(String(byID.id())===selector)return byID;}catch(e){if([-1712,-1743,-600].indexOf(Number(e.errorNumber))>=0)throw e;}var found=mail.accounts.whose({name:selector}),n=count(found,null);if(n>1)fail('AMBIGUOUS_REFERENCE','Account name is ambiguous; use its ID.');if(n===1)return found[0];fail('NOT_FOUND','Mail account not found. Run accounts.');}
function resolveMailbox(mail,a,v){var b=mailboxIdentity(a,v),current=resolveAccount(mail,b.accountID);b.accountID=String(current.id());for(var i=0;i<b.path.length;i++){var matches=current.mailboxes.whose({name:b.path[i]}),n=count(matches,null);if(!n)fail('NOT_FOUND','Mailbox not found. Run mailboxes.');if(n!==1)fail('AMBIGUOUS_REFERENCE','Mailbox path is ambiguous.');current=matches[0];}b.ref=boxRef(b.accountID,b.path);b.object=current;return b;}
function resolveMessage(mail,s){var r=parseMessage(s),b=resolveMailbox(mail,r.accountID,boxRef(r.accountID,r.mailboxPath)),m=b.object.messages.byId(r.id);try{if(Number(m.id())!==r.id||r.messageID&&String(m.messageId())!==r.messageID)fail('STALE_REFERENCE','Message identity changed; search again.');}catch(e){if(e.code||[-1712,-1743,-600].indexOf(Number(e.errorNumber))>=0)throw e;fail('STALE_REFERENCE','Message moved or is unavailable; search again.');}return{object:m,box:b,identity:r};}
function metadata(m,b){var id=Number(m.id()),rfc=txt(optional(function(){return m.messageId();},''));return{ref:messageRef(b.accountID,b.path,id,rfc),id:id,messageID:rfc,accountID:b.accountID,mailbox:b.ref,subject:txt(m.subject()),sender:txt(m.sender()),dateReceived:iso(optional(function(){return m.dateReceived();},null)),dateSent:iso(optional(function(){return m.dateSent();},null)),read:Boolean(m.readStatus()),flagged:Boolean(m.flaggedStatus()),flagIndex:Number(optional(function(){return m.flagIndex();},-1)),size:Number(optional(function(){return m.messageSize();},0))};}
function recipients(c){var out=[],n=count(c,1000);for(var i=0;i<n;i++)out.push({address:txt(c[i].address()),name:txt(optional(function(){return c[i].name();},''))});return out;}
function accounts(mail){var out=[],n=count(mail.accounts,1000);for(var i=0;i<n;i++){var a=mail.accounts[i];out.push({id:txt(a.id()),name:txt(a.name()),emailAddresses:a.emailAddresses(),enabled:Boolean(a.enabled()),type:txt(a.accountType())});}return{accounts:out};}
function mailboxes(mail,r){var a=resolveAccount(mail,opt(r,'account')),id=String(a.id()),limit=integer(opt(r,'limit'),1000,1,5000,'limit'),rows=[],partial=false;function visit(c,parent){if(parent.length>=40){partial=true;return;}var n=count(c.mailboxes,null);for(var i=0;i<n;i++){if(rows.length>=limit){partial=true;return;}var b=c.mailboxes[i],p=parent.concat([String(b.name())]);rows.push({ref:boxRef(id,p),accountID:id,name:p[p.length-1],path:p,displayPath:p.join('/'),unread:Number(b.unreadCount())});visit(b,p);}}visit(a,[]);return{mailboxes:rows,partial:partial};}

/* Search never counts or enumerates the messages collection. A cursor refers
 * to the first uncompleted index, with bounded first/previous ID anchors. */
function searchClockMilliseconds(){return Number($.NSProcessInfo.processInfo.systemUptime)*1000;}
function prepareSearch(r) {
    var box = mailboxIdentity(opt(r, 'account'), opt(r, 'mailbox', 'INBOX'));
    var s = {
        request: r, box: box,
        limit: integer(opt(r, 'limit'), 20, 1, 200, 'limit'),
        maxScan: integer(opt(r, 'max-scan'), 500, 1, 5000, 'max-scan'),
        maxBody: integer(opt(r, 'max-body'), 20000, 1, 200000, 'max-body'),
        includeBody: flag(r, 'include-body'), messages: [],
        offset: 0, index: 0, firstID: null, previous: null, resolvedAccountID: null,
        scanned: 0, reachedEnd: false, timedOut: false, needsRestart: false,
        stopReason: 'initializing', stopError: null,
        startedAtMilliseconds: searchClockMilliseconds(), pageBudgetMilliseconds: null
    };
    if (flag(r, 'read') && flag(r, 'unread')) fail('INVALID_INPUT', 'Choose read or unread, not both.');
    s.filters = {
        from: opt(r, 'from', ''), subject: opt(r, 'subject', ''), query: opt(r, 'query', ''),
        since: opt(r, 'since', ''), before: opt(r, 'before', ''), body: opt(r, 'body-contains', ''),
        read: flag(r, 'read'), unread: flag(r, 'unread'), flagged: flag(r, 'flagged')
    };
    ['from', 'subject', 'query', 'since', 'before', 'body'].forEach(function(k) {
        if (typeof s.filters[k] !== 'string') fail('INVALID_INPUT', 'Filters must be strings.');
    });
    var timeout = Number(opt(r, 'timeout', '30'));
    if (!isFinite(timeout) || timeout < 1 || timeout > 120) fail('INVALID_INPUT', 'timeout must be 1..120 seconds.');
    if (Object.keys(s.filters).some(function(k) { return Boolean(s.filters[k]); })) {
        s.pageBudgetMilliseconds = Math.min(20000, timeout * 500);
    }
    s.since = s.filters.since ? Date.parse(s.filters.since) : null;
    s.before = s.filters.before ? Date.parse(s.filters.before) : null;
    if ((s.since !== null && !isFinite(s.since)) || (s.before !== null && !isFinite(s.before)) ||
            (s.since !== null && s.before !== null && s.since >= s.before)) {
        fail('INVALID_INPUT', 'Invalid since/before dates.');
    }
    s.scope = JSON.stringify({box: box.ref, filters: s.filters, includeBody: s.includeBody, maxBody: s.maxBody});
    var cursor = opt(r, 'cursor');
    if (cursor) {
        if (cursor.indexOf('mailcursor:v1:') === 0) {
            fail('STALE_CURSOR', 'Restart without cursor; version 1 cursors cannot resume.');
        }
        var value = dec(CP, cursor);
        if (!value || value.scope !== s.scope || !Number.isSafeInteger(value.offset) || value.offset < 0 || value.offset > 2147483646) {
            fail('INVALID_REFERENCE', 'Cursor scope differs. Keep account, mailbox, filters and body options unchanged.');
        }
        if (value.firstID !== null && (!Number.isSafeInteger(value.firstID) || value.firstID < 0)) {
            fail('INVALID_REFERENCE', 'Invalid cursor anchor.');
        }
        var invalidPrevious = value.offset === 0 ? value.previous !== null :
            !value.previous || value.previous.index !== value.offset - 1 ||
            !Number.isSafeInteger(value.previous.id) || value.previous.id < 0 || value.firstID === null;
        if (invalidPrevious) fail('INVALID_REFERENCE', 'Invalid previous anchor.');
        s.offset = s.index = value.offset;
        s.firstID = value.firstID;
        s.previous = value.previous;
        s.resolvedAccountID = value.accountID || null;
    }
    if (searchCursor(s).length > 32768) fail('INVALID_INPUT', 'Search filters are too large for a cursor.');
    if (r.checkpointPath !== undefined && (typeof r.checkpointPath !== 'string' || r.checkpointPath[0] !== '/' || r.checkpointPath.indexOf('\0') >= 0)) {
        fail('INVALID_INPUT', 'Invalid checkpoint path.');
    }
    if (r.deadlineEpochMilliseconds !== undefined && (typeof r.deadlineEpochMilliseconds !== 'number' || !isFinite(r.deadlineEpochMilliseconds))) {
        fail('INVALID_INPUT', 'Invalid deadline.');
    }
    // Save before Application('Mail') is initialized. Even its first remote
    // property read can block, and a killed process must still have a cursor.
    checkpointSearch(s);
    return s;
}

function searchCursor(s) {
    return enc(CP, {scope: s.scope, offset: s.index, firstID: s.firstID,
        previous: s.previous, accountID: s.resolvedAccountID});
}

function searchData(s) {
    var data = {
        messages: s.messages, nextCursor: s.reachedEnd || s.needsRestart ? null : searchCursor(s),
        coverage: {scanned: s.scanned, startOffset: s.offset, nextOffset: s.index,
            totalInMailbox: null, totalKnown: false, skippedUnavailable: 0,
            complete: s.reachedEnd && s.offset === 0, reachedEnd: s.reachedEnd},
        partial: !s.reachedEnd || s.offset > 0, timedOut: s.timedOut, stopReason: s.stopReason,
        cursorVersion: 2, needsRestart: s.needsRestart, resumeAvailable: !s.reachedEnd && !s.needsRestart,
        pageBudgetSeconds: s.pageBudgetMilliseconds === null ? null : s.pageBudgetMilliseconds / 1000,
        order: 'Mail native mailbox order; not sorted by date', contentTrust: 'untrusted email content',
        limitation: 'No mailbox count; bounded anchors detect common changes but are not a transactional snapshot. Body caps limit returned text, not Mail retrieval.'
    };
    if (s.stopError) data.stopError = s.stopError;
    return data;
}

function checkpointSearch(s) {
    var data = searchData(s), path = s.request.checkpointPath;
    if (path !== undefined) {
        if (!$(JSON.stringify(data)).writeToFileAtomicallyEncodingError($(path), true, $.NSUTF8StringEncoding, Ref())) {
            fail('IO_ERROR', 'Could not save search checkpoint.');
        }
        if (!$.NSFileManager.defaultManager.setAttributesOfItemAtPathError($({NSFilePosixPermissions: 384}), $(path), Ref())) {
            fail('IO_ERROR', 'Could not secure search checkpoint.');
        }
    }
    return data;
}

function searchDeadline(s) {
    if (s.request.deadlineEpochMilliseconds !== undefined && Date.now() >= s.request.deadlineEpochMilliseconds) {
        fail('TIMEOUT', 'Search reached its hard deadline; resume with nextCursor.');
    }
}
function searchRead(s, fn) { searchDeadline(s); return fn(); }
function missing(e) { return [-1728, -1719].indexOf(Number(e.errorNumber)) >= 0; }

function indexedID(s, collection, index) {
    var id = Number(searchRead(s, function() { return collection[index].id(); }));
    if (!Number.isSafeInteger(id) || id < 0) fail('BACKEND_ERROR', 'Invalid message ID.');
    return id;
}

function anchor(s, collection, expected) {
    var id;
    try { id = indexedID(s, collection, expected.index); }
    catch (e) {
        if (!missing(e)) throw e;
        fail('STALE_CURSOR', 'Mailbox changed; restart without cursor.');
    }
    if (id !== expected.id) fail('STALE_CURSOR', 'Mailbox changed; restart without cursor.');
}

function anchors(s, collection) {
    if (s.firstID !== null) anchor(s, collection, {index: 0, id: s.firstID});
    if (s.previous && s.previous.index !== 0) anchor(s, collection, s.previous);
    else if (s.previous && s.previous.id !== s.firstID) fail('STALE_CURSOR', 'Cursor anchors disagree.');
}

function searchFailure(s, error) {
    var number = Number(error.errorNumber);
    var code = error.code || (number === -1712 ? 'TIMEOUT' : number === -1743 ? 'PERMISSION_REQUIRED' :
        number === -600 ? 'MAIL_NOT_RUNNING' : missing(error) ? 'STALE_CURSOR' : 'BACKEND_ERROR');
    s.timedOut = code === 'TIMEOUT';
    s.needsRestart = code === 'STALE_CURSOR' || code === 'INVALID_REFERENCE';
    s.stopReason = s.timedOut ? 'timeout' : 'candidate-error';
    s.stopError = {code: code,
        message: error.code ? error.message : 'Mail could not finish this candidate; it was not skipped.',
        details: {index: s.index}};
    if (isFinite(number)) s.stopError.details.appleEventError = number;
    return checkpointSearch(s);
}

function searchCandidate(s, collection, id) {
    // Resolve by stable local ID after reading one indexed ID. Reusing the
    // deferred indexed specifier for all fields could mix different messages.
    var message = collection.byId(id), cache = {};
    function get(key) {
        if (!has(cache, key)) cache[key] = searchRead(s, function() { return message[key](); });
        return cache[key];
    }
    function includes(value, query) {
        return !query || txt(value).toLocaleLowerCase().indexOf(query.toLocaleLowerCase()) >= 0;
    }
    var filters = s.filters;
    if ((filters.read || filters.unread) && Boolean(get('readStatus')) !== filters.read) return null;
    if (filters.flagged && !Boolean(get('flaggedStatus'))) return null;
    if (filters.from && !includes(get('sender'), filters.from)) return null;
    if (filters.subject && !includes(get('subject'), filters.subject)) return null;
    if (filters.query && !includes(txt(get('subject')) + '\n' + txt(get('sender')), filters.query)) return null;
    if (s.since !== null || s.before !== null) {
        var date = iso(get('dateReceived')), instant = date === null ? null : Date.parse(date);
        if ((s.since !== null && (instant === null || instant < s.since)) ||
                (s.before !== null && (instant === null || instant >= s.before))) return null;
    }
    if (filters.body && !includes(get('content'), filters.body)) return null;
    var rfc = txt(get('messageId'));
    var item = {ref: messageRef(s.box.accountID, s.box.path, id, rfc), id: id, messageID: rfc,
        accountID: s.box.accountID, mailbox: s.box.ref, subject: txt(get('subject')), sender: txt(get('sender')),
        dateReceived: iso(get('dateReceived')), dateSent: iso(get('dateSent')), read: Boolean(get('readStatus')),
        flagged: Boolean(get('flaggedStatus')), flagIndex: Number(get('flagIndex')), size: Number(get('messageSize'))};
    if (s.includeBody) item.body = capped(get('content'), s.maxBody);
    return item;
}

function search(mail, request, prepared) {
    var s = prepared || prepareSearch(request), box, collection;
    try {
        searchDeadline(s);
        box = resolveMailbox(mail, s.box.accountID, s.box.ref);
        if (s.resolvedAccountID && s.resolvedAccountID !== box.accountID) {
            fail('STALE_CURSOR', 'Account identity changed; restart the search.');
        }
        s.resolvedAccountID = box.accountID;
        s.box = box;
        collection = box.object.messages;
        s.stopReason = 'validating-cursor';
        checkpointSearch(s);
        anchors(s, collection);
    } catch (error) {
        if (error.code === 'TIMEOUT' || Number(error.errorNumber) === -1712) return searchFailure(s, error);
        if (error.code === 'STALE_CURSOR') searchFailure(s, error);
        throw error;
    }
    s.stopReason = 'scanning';
    checkpointSearch(s);
    while (s.scanned < s.maxScan && s.messages.length < s.limit) {
        try {
            // Limit/max-scan win at the loop boundary. A true hard deadline
            // wins over a cooperative page budget; it must remain an error.
            searchDeadline(s);
            if (s.scanned > 0 && s.pageBudgetMilliseconds !== null &&
                    searchClockMilliseconds() - s.startedAtMilliseconds >= s.pageBudgetMilliseconds) {
                s.stopReason = 'page-budget';
                return checkpointSearch(s);
            }
            var id;
            try { id = indexedID(s, collection, s.index); }
            catch (error) {
                if (!missing(error)) throw error;
                // Missing indexed object alone could mean a vanished mailbox.
                // Validate its identity and bounded anchors before claiming EOF.
                if (txt(searchRead(s, function() { return box.object.name(); })) !== box.path[box.path.length - 1]) {
                    fail('STALE_CURSOR', 'Mailbox changed.');
                }
                anchors(s, collection);
                s.reachedEnd = true;
                s.stopReason = 'end';
                return checkpointSearch(s);
            }
            if (s.index === 0 && s.firstID === null) s.firstID = id;
            var item = searchCandidate(s, collection, id);
            anchor(s, collection, {index: s.index, id: id});
            if (s.previous) anchor(s, collection, s.previous);
            // Commit the result and continuation together, only after complete
            // evaluation. A stalled/failed candidate is retried on continuation.
            if (item !== null) s.messages.push(item);
            s.previous = {index: s.index, id: id};
            s.index++;
            s.scanned++;
            checkpointSearch(s);
        } catch (error) {
            return searchFailure(s, error);
        }
    }
    s.stopReason = s.messages.length >= s.limit ? 'limit' : 'max-scan';
    return checkpointSearch(s);
}

function readMessage(mail,r){var resolved;if(r.positionals[0]&&r.positionals[0].indexOf(MP)===0)resolved=resolveMessage(mail,r.positionals[0]);else{var b=resolveMailbox(mail,opt(r,'account'),opt(r,'mailbox')),id=integer(r.positionals[0],null,0,2147483647,'id'),m=b.object.messages.byId(id);resolved={object:m,box:b};}var m=resolved.object,item=metadata(m,resolved.box);item.to=recipients(m.toRecipients);item.cc=recipients(m.ccRecipients);item.bcc=recipients(m.bccRecipients);item.replyTo=txt(optional(function(){return m.replyTo();},''));if(!flag(r,'metadata-only'))item.body=capped(m.content(),integer(opt(r,'max-body'),20000,1,200000,'max-body'));if(flag(r,'headers'))item.headers=capped(m.allHeaders(),integer(opt(r,'max-headers'),20000,1,200000,'max-headers'));if(flag(r,'source'))item.source=capped(m.source(),integer(opt(r,'max-source'),100000,1,1000000,'max-source'));return{message:item,contentTrust:'untrusted email content'};}
function mutate(mail,r){var resolved=resolveMessage(mail,r.positionals[0]),m=resolved.object,b=resolved.box,dry=flag(r,'dry-run');if(r.action==='mark'){if(flag(r,'read')===flag(r,'unread'))fail('INVALID_INPUT','Specify read or unread.');var wanted=flag(r,'read');if(!dry){m.readStatus=wanted;if(Boolean(m.readStatus())!==wanted)fail('WRITE_STATUS_UNKNOWN','Read status not verified; refresh before retrying.');}return{dryRun:dry,requestedRead:wanted,verified:!dry,message:metadata(m,b)};}
 if(r.action==='flag'){var wanted=flag(r,'clear')?-1:integer(opt(r,'index'),0,-1,6,'index');if(!dry){m.flagIndex=wanted;if(Number(m.flagIndex())!==wanted)fail('WRITE_STATUS_UNKNOWN','Flag status not verified.');}return{dryRun:dry,requestedFlagIndex:wanted,verified:!dry,message:metadata(m,b)};}
 var to=opt(r,'to');if(!to)fail('INVALID_INPUT','Supply an explicit --to mailbox for move, archive or trash.');var targetAccount=opt(r,'to-account',b.accountID);if(to.indexOf(BP)===0&&!opt(r,'to-account'))targetAccount=dec(BP,to).accountID;var dest=resolveMailbox(mail,targetAccount,to);if(dry||dest.ref===b.ref)return{dryRun:dry,changed:false,destination:dest.ref,message:metadata(m,b)};
 var ref=resolved.identity;if(ref.messageID&&count(dest.object.messages.whose({messageId:ref.messageID}),null)>0)fail('AMBIGUOUS_REFERENCE','Destination already contains this Message-ID; move not attempted.');mail.move(m,{to:dest.object});var moved=dest.object.messages.byId(ref.id),verified=false;try{verified=Number(moved.id())===ref.id&&(!ref.messageID||String(moved.messageId())===ref.messageID);}catch(e){}if(!verified&&ref.messageID){var matches=dest.object.messages.whose({messageId:ref.messageID});if(count(matches,null)===1){moved=matches[0];verified=true;}}if(!verified)fail('WRITE_STATUS_UNKNOWN','Move requested but new identity is unverified. Search destination before retrying.',{destination:dest.ref});return{changed:true,verified:true,previousRef:r.positionals[0],destination:dest.ref,message:metadata(moved,dest),synchronization:'local Mail state only'};
}
function attachmentMetadata(a,i,message){var v={message:message,id:txt(a.id()),index:i,name:txt(a.name()),size:Number(a.fileSize())};return{ref:enc(AP,v),id:v.id,name:v.name,size:v.size,mimeType:txt(optional(function(){return a.mimeType();},'')),downloaded:Boolean(a.downloaded())};}
function attachmentList(mail,r){var resolved=resolveMessage(mail,r.positionals[0]),c=resolved.object.mailAttachments,n=count(c,1000),out=[];for(var i=0;i<n;i++)out.push(attachmentMetadata(c[i],i,r.positionals[0]));return{message:r.positionals[0],attachments:out};}
function attachmentSave(mail,r){var ref=dec(AP,r.positionals[0]);if(!ref||!Number.isSafeInteger(ref.index)||ref.index<0||ref.index>=1000||typeof ref.id!=='string')fail('INVALID_REFERENCE','Invalid attachment reference.');var resolved=resolveMessage(mail,ref.message),c=resolved.object.mailAttachments;if(ref.index>=count(c,1000))fail('STALE_REFERENCE','Attachment unavailable.');var a=c[ref.index];if(txt(a.id())!==ref.id||txt(a.name())!==ref.name||Number(a.fileSize())!==ref.size)fail('STALE_REFERENCE','Attachment identity changed.');if(!Boolean(a.downloaded()))fail('ATTACHMENT_NOT_DOWNLOADED','Download this attachment in Mail first.');var p=opt(r,'output');if(typeof p!=='string'||p[0]!=='/'||p.indexOf('\0')>=0)fail('INVALID_INPUT','Supply absolute output path.');var fm=$.NSFileManager.defaultManager;if(fm.fileExistsAtPath($(p)))fail('FILE_EXISTS','Output already exists.');var parent=ObjC.unwrap($(p).stringByDeletingLastPathComponent),isDir=Ref();if(!fm.fileExistsAtPathIsDirectory($(parent),isDir)||!isDir[0])fail('INVALID_INPUT','Output parent directory must exist.');if(flag(r,'dry-run'))return{dryRun:true,output:p};var stage=parent+'/.apple-desk-attachment-'+ObjC.unwrap($.NSUUID.UUID.UUIDString),file=stage+'/content';if(!fm.createDirectoryAtPathWithIntermediateDirectoriesAttributesError($(stage),false,$({NSFilePosixPermissions:448}),Ref()))fail('IO_ERROR','Cannot create attachment staging directory.');try{mail.save(a,{in:Path(file)});if(!fm.fileExistsAtPath($(file)))fail('WRITE_STATUS_UNKNOWN','Mail did not create attachment file.');if(!fm.setAttributesOfItemAtPathError($({NSFilePosixPermissions:384}),$(file),Ref()))fail('IO_ERROR','Cannot secure attachment.');if(!fm.linkItemAtPathToPathError($(file),$(p),Ref()))fail('IO_ERROR','Cannot publish attachment without replacing an existing path.');return{saved:true,output:p,attachment:attachmentMetadata(a,ref.index,ref.message),permissions:'0600'};}finally{fm.removeItemAtPathError($(stage),Ref());}}
function address(v){var s=txt(v).trim(),m=/<([^<>]+)>$/.exec(s);return(m?m[1]:s).trim().toLowerCase();}
function validateDraft(mail,d){if(!d||['new','reply','forward'].indexOf(d.kind)<0)fail('INVALID_INPUT','Invalid draft kind.');if(typeof d.from!=='string'||!d.from||/[\r\n\0]/.test(d.from))fail('INVALID_INPUT','Explicit sender required.');['to','cc','bcc','attachments'].forEach(function(k){if(!Array.isArray(d[k])||d[k].length>100||!d[k].every(function(v){return typeof v==='string'&&v.length>0&&v.indexOf('\0')<0;}))fail('INVALID_INPUT','Invalid '+k+'.');});['to','cc','bcc'].forEach(function(k){d[k].forEach(function(v){if(/[\r\n]/.test(v)||address(v).indexOf('@')<=0)fail('INVALID_INPUT','Invalid recipient.');});});if(typeof d.body!=='string'||d.body.length>500000||d.body.indexOf('\0')>=0)fail('INVALID_INPUT','Invalid body.');if(has(d,'subject')&&(typeof d.subject!=='string'||/[\r\n\0]/.test(d.subject)||d.subject.length>2000))fail('INVALID_INPUT','Invalid subject.');if(d.kind==='new'&&!has(d,'subject'))fail('INVALID_INPUT','Subject required.');if(d.kind!=='reply'&&!d.to.length)fail('INVALID_INPUT','A to recipient is required.');var matches=accounts(mail).accounts.filter(function(a){return a.enabled&&a.emailAddresses.some(function(v){return address(v)===address(d.from);});});if(matches.length!==1)fail(matches.length?'AMBIGUOUS_REFERENCE':'INVALID_INPUT','Sender must identify one enabled Mail account.');d.attachments.forEach(function(p){var dir=Ref();if(p[0]!=='/'||!$.NSFileManager.defaultManager.fileExistsAtPathIsDirectory($(p),dir)||dir[0])fail('INVALID_INPUT','Attachment file is missing.');});}
function replaceRecipients(mail,m,key,type,values){if(count(m[key],1000))mail.delete(m[key]);values.forEach(function(v){m[key].push(mail[type]({address:v}));});}
// Outgoing attachments expose a file-name property in Mail's rich-text suite.
// Read it independently after insertion. Unsupported or mismatching readback
// must stop before Mail.send rather than silently omit a requested file.
function attachmentPath(value) {
    var path = txt(value);
    if (path.indexOf('file://') === 0) {
        path = ObjC.unwrap($.NSURL.URLWithString($(path)).path);
    }
    if (!path || path[0] !== '/') {
        fail('COMPOSE_VERIFICATION_FAILED', 'Mail did not expose an attachment file path; not sent.');
    }
    return ObjC.unwrap($(path).stringByStandardizingPath.stringByResolvingSymlinksInPath);
}

function outgoingAttachmentPaths(message) {
    var collection = message.content.attachments, result = [];
    var n = count(collection, 1000);
    for (var i = 0; i < n; i++) result.push(attachmentPath(collection[i].fileName()));
    return result;
}

function plainBody(value) {
    return txt(value).replace(/\r\n?/g, '\n');
}

function compose(mail, r) {
    var d = r.input;
    validateDraft(mail, d);
    var original = d.kind === 'new' ? null : resolveMessage(mail, d.replyToMessage);
    var originalAttachments = [];
    if (d.kind === 'forward') {
        var collection = original.object.mailAttachments;
        var attachmentCount = count(collection, 1000);
        for (var i = 0; i < attachmentCount; i++) originalAttachments.push(txt(collection[i].name()));
        if (d.body && originalAttachments.length) {
            fail('UNSUPPORTED_OPERATION', 'A forward with original attachments requires an empty body to preserve native content.');
        }
    }
    var derived = d.kind === 'reply' && !d.to.length && !d.cc.length && !d.bcc.length;
    if (r.action === 'draft-send' && derived) {
        fail('INVALID_INPUT', 'Sending a reply requires explicit reviewed recipients; update to/cc/bcc or open it in Mail.');
    }
    if (flag(r, 'dry-run')) {
        return {dryRun: true, from: d.from, to: d.to, cc: d.cc, bcc: d.bcc,
            recipientMode: derived ? 'derived-by-Mail-at-compose-time' : 'explicit', kind: d.kind};
    }
    var m;
    if (d.kind === 'reply') {
        m = mail.reply(original.object, {openingWindow: false, replyToAll: Boolean(d.replyAll)});
    } else if (d.kind === 'forward') {
        m = mail.forward(original.object, {openingWindow: false});
    } else {
        m = mail.OutgoingMessage({visible: false, sender: d.from, subject: d.subject, content: d.body});
        mail.outgoingMessages.push(m);
    }
    m.sender = d.from;
    if (has(d, 'subject')) m.subject = d.subject;
    var expectedBody;
    if (d.kind === 'forward') {
        expectedBody = d.body ? d.body + '\n\n' + txt(m.content()) : txt(m.content());
        if (d.body) m.content = expectedBody;
    } else {
        expectedBody = d.body;
        m.content = expectedBody;
    }
    if (!derived) {
        replaceRecipients(mail, m, 'toRecipients', 'ToRecipient', d.to);
        replaceRecipients(mail, m, 'ccRecipients', 'CcRecipient', d.cc);
        replaceRecipients(mail, m, 'bccRecipients', 'BccRecipient', d.bcc);
    }
    if (plainBody(m.content()) !== plainBody(expectedBody)) {
        fail('COMPOSE_VERIFICATION_FAILED', 'Mail changed the requested body; not sent.');
    }
    var originalPaths = outgoingAttachmentPaths(m);
    var originalNames = originalPaths.map(function(p) { return ObjC.unwrap($(p).lastPathComponent); }).sort();
    if (JSON.stringify(originalNames) !== JSON.stringify(originalAttachments.slice().sort())) {
        fail('COMPOSE_VERIFICATION_FAILED', 'Mail did not preserve the expected original attachments; not sent.');
    }
    d.attachments.forEach(function(p) {
        m.content.attachments.push(mail.Attachment({fileName: Path(p)}));
    });
    var wantedPaths = originalPaths.concat(d.attachments.map(attachmentPath)).sort();
    var actualPaths = outgoingAttachmentPaths(m).sort();
    if (JSON.stringify(actualPaths) !== JSON.stringify(wantedPaths)) {
        fail('COMPOSE_VERIFICATION_FAILED', 'Mail did not preserve the requested attachment files; not sent.');
    }
    if (address(m.sender()) !== address(d.from)) {
        fail('COMPOSE_VERIFICATION_FAILED', 'Mail changed the sender; not sent.');
    }
    if (has(d, 'subject') && txt(m.subject()) !== d.subject) {
        fail('COMPOSE_VERIFICATION_FAILED', 'Mail changed the subject; not sent.');
    }
    // Insertion may introduce object-replacement characters for attachment
    // positions. The exact body was verified before insertion; without files
    // verify it once more immediately before sending.
    if (!actualPaths.length && plainBody(m.content()) !== plainBody(expectedBody)) {
        fail('COMPOSE_VERIFICATION_FAILED', 'Mail changed the requested body; not sent.');
    }
    var to = recipients(m.toRecipients), cc = recipients(m.ccRecipients), bcc = recipients(m.bccRecipients);
    if (!to.length && !cc.length && !bcc.length) {
        fail('COMPOSE_VERIFICATION_FAILED', 'No recipients; not sent.');
    }
    if (!derived) {
        [[to, d.to], [cc, d.cc], [bcc, d.bcc]].forEach(function(pair) {
            var got = pair[0].map(function(v) { return address(v.address); }).sort();
            var wanted = pair[1].map(address).sort();
            if (JSON.stringify(got) !== JSON.stringify(wanted)) {
                fail('COMPOSE_VERIFICATION_FAILED', 'Mail changed recipients; not sent.');
            }
        });
    }
    var result = {from: txt(m.sender()), subject: txt(m.subject()), to: to, cc: cc, bcc: bcc,
        outgoingID: Number(m.id()), kind: d.kind, attachmentsVerified: true,
        attachmentCount: actualPaths.length};
    if (r.action === 'draft-open') {
        m.visible = true;
        result.status = 'opened-in-Mail';
        result.limitation = 'Compose handoff; CLI draft is separate. Reopening creates another compose window.';
        return result;
    }
    sendStarted = true;
    if (mail.send(m) !== true) fail('SEND_STATUS_UNKNOWN', 'Mail did not confirm acceptance.');
    result.status = 'accepted-by-Mail';
    result.accepted = true;
    result.deliveryConfirmed = false;
    return result;
}

function selfTest(){var ref=messageRef('a',['日本語/📫'],42,'<x>');if(parseMessage(ref).id!==42||capped('a📫z',2).text!=='a')fail('SELF_TEST_FAILED','Reference or Unicode test failed.');return{passed:true,mailAccessed:false};}
function run(argv){sendStarted=false;try{if(!argv||argv.length!==1)fail('INVALID_INPUT','Pass one JSON request file.');var raw=$.NSString.stringWithContentsOfFileEncodingError($(argv[0]),$.NSUTF8StringEncoding,Ref());if(!raw||raw.isNil())fail('INVALID_INPUT','Cannot read request.');var r=JSON.parse(ObjC.unwrap(raw));r.options=r.options||{};r.flags=r.flags||[];r.positionals=r.positionals||[];if(r.action==='self-test')return JSON.stringify({ok:true,data:selfTest()});if(r.action==='doctor')return JSON.stringify({ok:true,data:{backend:'Mail JXA',running:Number($.NSRunningApplication.runningApplicationsWithBundleIdentifier('com.apple.mail').count)>0,automation:'not-probed',note:'Permission grants depend on the launching agent host.'}});var supported=['accounts','mailboxes','search','list','show','read','mark','flag','move','archive','trash','attachment-list','attachment-save','draft-open','draft-send','permissions'];if(supported.indexOf(r.action)<0)fail('INVALID_INPUT','Unsupported Mail operation.');if(r.action==='list')r.action='search';var prepared=r.action==='search'?prepareSearch(r):null,mail=Application('com.apple.mail');if(!mail.running()){if(!flag(r,'launch'))fail('MAIL_NOT_RUNNING','Open Mail or pass --launch.');mail.launch();}var data;switch(r.action){case'accounts':data=accounts(mail);break;case'mailboxes':data=mailboxes(mail,r);break;case'search':data=search(mail,r,prepared);break;case'show':case'read':data=readMessage(mail,r);break;case'mark':case'flag':case'move':case'archive':case'trash':data=mutate(mail,r);break;case'attachment-list':data=attachmentList(mail,r);break;case'attachment-save':data=attachmentSave(mail,r);break;case'draft-open':case'draft-send':data=compose(mail,r);break;case'permissions':mail.accounts.length;data={automation:'authorized'};break;}return JSON.stringify({ok:true,data:data});}catch(e){var n=Number(e.errorNumber),code=sendStarted?'SEND_STATUS_UNKNOWN':e.code||(n===-1743?'PERMISSION_REQUIRED':n===-1712?'TIMEOUT':n===-600?'MAIL_NOT_RUNNING':'BACKEND_ERROR');return JSON.stringify({ok:false,error:{code:code,message:sendStarted?'Send outcome uncertain. Check Outbox and Sent; do not blindly retry.':txt(e.message),details:e.details||{appleEventError:isFinite(n)?n:null}}});}}
