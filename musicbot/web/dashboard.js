"use strict";
const $ = (id) => document.getElementById(id);
let secret = "", selected = "", state = null, busy = false, connected = false;
let queueRevision = null, generation = 0, loading = false, stateGeneration = 0;
let authMode = null, authenticated = false;
let manualGuild = "", entryGuild = "", viewerKey = "owner";
const labels = () => ({playing: t("m0040"), paused: t("m0041"), stopped: t("m0042"), disconnected: t("m0043")});
let toastTimer = null, toastVersion = 0;
function notice(message, error = false) {
  const version = ++toastVersion;
  window.clearTimeout(toastTimer);
  $("notice").textContent = message;
  $("notice").classList.toggle("error", error);
  $("notice").classList.toggle("visible", !!message);
  if (message) toastTimer = window.setTimeout(() => {
    if (version === toastVersion) {
      $("notice").textContent = "";
      $("notice").classList.toggle("visible", false);
    }
  }, error ? 10000 : 4500);
}
// Preserve the original nodes (including translation markers and listeners).
const busyButtonLabels = new WeakMap();
function buttonLabel(button, key, count = null, suffix = null) {
  const label = document.createElement("span");
  label.dataset.i18n = key; label.textContent = t(key);
  button.replaceChildren(label);
  if (count !== null) {
    const number = document.createElement("span"); number.textContent = String(count);
    const end = document.createElement("span");
    end.dataset.i18n = suffix; end.textContent = t(suffix);
    button.append(number, end);
  }
}
function translateButton(button) {
  const visit = node => {
    if (node.dataset?.i18n) node.textContent = t(node.dataset.i18n);
    for (const child of node.children || []) visit(child);
  };
  visit(button);
}
function buttonBusy(button, active, count = null) {
  const navigation = /^nav-/.test(button.id || "");
  if (!navigation && active && !busyButtonLabels.has(button)) {
    const nodes = Array.from(button.childNodes || button.children || []);
    if (!nodes.length) {
      const label = document.createElement("span"); label.textContent = button.textContent;
      nodes.push(label);
    }
    busyButtonLabels.set(button, nodes);
    buttonLabel(button, count === null ? "m0044" : "m0102", count, "m0103");
  } else if (!navigation && !active && busyButtonLabels.has(button)) {
    button.replaceChildren(...busyButtonLabels.get(button));
    busyButtonLabels.delete(button);
    translateButton(button);
  }
  button.dataset.loading = active ? "1" : "0";
  button.classList.toggle("is-loading", active && !navigation);
  button.setAttribute("aria-busy", String(active));
  if (active) button.disabled = true;
}
function safeURL(value) {
  try {
    if (/[\u0000-\u001f]/.test(String(value))) return "";
    const url = new URL(value);
    return /^https?:$/.test(url.protocol) && !url.username && !url.password ? value : "";
  } catch { return ""; }
}
let suppressSongLinksUntil = 0;
function songLinkURL(value) {
  const url = safeURL(value);
  if (!url) return "";
  const key = songIdentity(url);
  return key.startsWith("youtube:") ? "https://www.youtube.com/watch?v=" + key.slice(8) : url;
}
function songTitle(element, song) {
  element.textContent = song?.title || "";
  const url = songLinkURL(song?.url || "");
  if (!url) return element;
  const link = document.createElement("a"); link.className = "song-title";
  link.textContent = song.title; link.href = url; link.target = "_blank"; link.rel = "noopener noreferrer";
  link.addEventListener("click", event => {
    if (drag || Date.now() < suppressSongLinksUntil) event.preventDefault();
  });
  element.replaceChildren(link);
  return element;
}
function songIdentity(value) {
  const raw = safeURL(String(value || "").trim());
  if (!raw) return "";
  const url = new URL(raw), host = url.hostname.toLowerCase();
  const parts = url.pathname.split("/").filter(Boolean);
  const youtube = host === "youtube.com" || host.endsWith(".youtube.com") ||
    host === "youtube-nocookie.com" || host.endsWith(".youtube-nocookie.com");
  const id = host === "youtu.be" || host === "www.youtu.be" ? parts[0] :
    youtube ? (url.pathname === "/watch" ? url.searchParams.get("v") :
      ["shorts", "embed", "live", "v"].includes(parts[0]) ? parts[1] : "") : "";
  if (id && /^[A-Za-z0-9_-]{11}$/.test(id)) return "youtube:" + id;
  url.hash = "";
  url.pathname = url.pathname.replace(/\/+$/, "") || "/";
  for (const key of [...url.searchParams.keys()])
    if (/^utm_/i.test(key) || /^(si|feature|fbclid|gclid)$/i.test(key)) url.searchParams.delete(key);
  url.searchParams.sort();
  return url.href;
}
function requesterName(song) { return song?.requester?.name || t("m0045"); }
const reduceMotion = () => !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
function duration(seconds) {
  seconds = Math.floor(Math.max(0, seconds || 0));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor(seconds / 60) % 60;
  return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(seconds % 60).padStart(2, "0");
}
function authDisplay() {
  const signedIn = authMode === "owner" || authenticated;
  $("dashboard").hidden = !signedIn;
  $("login-screen").hidden = signedIn;
  $("discord-login").hidden = authMode !== "discord";
  $("auth").hidden = authMode !== "owner";
  $("user-profile").hidden = authMode !== "discord" || !authenticated;
  $("identity-note").textContent = authMode === "discord"
    ? t("m0046")
    : t("m0047");
}
function signedOut(message = t("m0048")) {
  closeSongChoices(false);
  stopEvents();
  if (typeof libraryClear === "function") libraryClear();
  if (typeof adminClear === "function") adminClear();
  ++generation; ++stateGeneration;
  lyricsPreference = false;
  authenticated = false; connected = false; loading = false; selected = ""; manualGuild = "";
  secret = ""; $("secret").value = ""; $("query").value = "";
  $("guild").replaceChildren(); $("user-name").textContent = "";
  $("user-avatar").removeAttribute("src"); $("user-avatar").hidden = true;
  resetView(); state = null; controls(); authDisplay();
  $("login-status").textContent = message;
  connectionStatus(t("m0049"));
  notice("");
}
async function initialize() {
  captureEntryGuild();
  try {
    const response = await fetch("/auth/session", {cache: "no-store", credentials: "same-origin"});
    if (!response.ok) throw new Error(t("m0050"));
    const session = await response.json();
    if (!["owner", "discord"].includes(session.auth_mode) || typeof session.authenticated !== "boolean" ||
        (session.auth_mode === "owner" && !session.authenticated))
      throw new Error(t("m0051"));
    authMode = session.auth_mode;
    authenticated = session.authenticated;
    if (authMode === "discord") {
      secret = "";
      if (!authenticated || !session.user) { signedOut(); return; }
      $("user-name").textContent = session.user.name;
      if (/^https:\/\//i.test(session.user.avatar || "")) {
        $("user-avatar").src = session.user.avatar; $("user-avatar").hidden = false;
      }
    }
    viewerKey = authMode === "discord" ? "user:" + session.user.id : "owner";
    readLyricsPreference();
    authDisplay(); await connect();
  } catch (error) {
    signedOut(error.message);
    $("login-status").classList.toggle("error", true);
  }
}
async function logout(allDevices = false) {
  if (authMode !== "discord" || !authenticated || busy) return;
  busy = true; controls();
  try { await api(allDevices ? "/auth/logout-all" : "/auth/logout", "POST", {}); signedOut(allDevices ? t("m0052") : t("m0053")); }
  catch (error) { if (authenticated) notice(error.message, true); }
  finally { busy = false; controls(); }
}
async function api(path, method = "GET", data) {
  const headers = {"X-MusicBot-Dashboard": "1", "X-Dashboard-Language": dashboardLocale()};
  if (authMode === "owner" && secret) headers.Authorization = "Bearer " + secret;
  if (data !== undefined) headers["Content-Type"] = "application/json";
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), path.endsWith("/resolve") ? 25000
    : (data?.selected_items || /\/library\/.*\/play$/.test(path)) ? 150000 : 30000);
  let response, body;
  try {
    response = await fetch(path, {method, headers, cache: "no-store", credentials: "same-origin",
      signal: controller.signal, body: data === undefined ? undefined : JSON.stringify(data)});
    body = await response.json().catch(() => ({}));
  } catch (error) {
    if (error.name === "AbortError") throw new Error(t("m0054"));
    throw error;
  } finally { window.clearTimeout(timer); }

  if (!response.ok) {
    if (response.status === 401) {
      if (authMode === "discord") signedOut(body.error || t("m0055"));
      else $("auth").open = true;
    }
    const error = new Error(body.error || t("m0056"));
    error.status = response.status; error.body = body; throw error;
  }
  return body;
}
function controls() {
  const usable = (authMode === "owner" || authenticated) && connected && !busy && !!selected;
  const hasPlayer = usable && state && state.status !== "disconnected";
  for (const id of ["toggle", "skip", "repeat", "volume"]) $(id).disabled = !hasPlayer;
  const active = hasPlayer && !!state.current && ["playing", "paused"].includes(state.status);
  $("toggle").disabled = !active || state.capabilities?.[state.status === "playing" ? "pause" : "resume"] !== true;
  $("skip").disabled = !active || state.capabilities?.skip !== true;
  $("enqueue").disabled = !usable || resolving;
  $("request-action").disabled = !usable || resolving;
  const seekable = active && state.capabilities?.seek === true && state.current.duration > 0 && state.current.seekable === true;
  for (const id of ["progress"]) $(id).disabled = !seekable;
  $("lyrics-toggle").hidden = state?.lyrics_available === false;
  $("lyrics-toggle").disabled = !hasPlayer || !state.current || state.lyrics_available === false;
  for (const id of ["lyrics-minus","lyrics-plus","lyrics-sync","lyrics-reset"])
    $(id).disabled = !lyricsOpen || !lyricsLines.length || lyricsLoading || lyricsTimingBusy || !connected;
  $("favorite").disabled = !hasPlayer || !safeURL(state?.current?.url) || $("favorite").dataset.loading === "1";
  $("lyrics-search").disabled = !usable || lyricsLoading;
  $("history-refresh").disabled = !usable || historyLoading;
  document.querySelectorAll("#history-list button").forEach((button) => { button.disabled = !usable; });
  document.querySelectorAll("#preview-results button").forEach((button) => {
    button.disabled = !usable || button.dataset.boundary === "1" || button.dataset.loading === "1";
  });
  document.querySelectorAll("#preview-results input").forEach((input) => {
    input.disabled = !usable || input.dataset.boundary === "1";
  });
  document.querySelectorAll("#recommendation-list button").forEach((button) => { button.disabled = !usable || resolving; });
  $("shuffle").disabled = !hasPlayer || !state.queue.length || queueFiltered();
  $("guild").disabled = busy;
  $("logout").disabled = busy; $("logout-all").disabled = busy;
  document.querySelectorAll("#queue button").forEach((button) => {
    button.disabled = !hasPlayer || button.dataset.boundary === "1";
  });
}
function imageElement(url, className = "queue-cover") {
  const img = document.createElement("img");
  img.className = className; img.alt = ""; img.loading = "lazy";
  if (safeURL(url)) { img.src = url; img.referrerPolicy = "no-referrer"; }
  else img.hidden = className !== "queue-cover";
  img.addEventListener("error", () => {
    img.removeAttribute("src"); img.hidden = className !== "queue-cover";
  });
  return img;
}
function renderQueue() {
  const signature = JSON.stringify([state.revision, queueMine, queueSearch, state.queue]);
  if (queueRevision === signature) return;
  const before = new Map(Array.from($("queue").children, (row) =>
    [row.dataset.key, row.getBoundingClientRect().top]));

  if (drag) cancelDrag(t("m0057"));
  queueRevision = signature;
  $("queue").replaceChildren();
  $("queue-count").textContent = String(state.queue.length);
  const visible = state.queue.filter((song) => (!queueMine || song.mine === true) &&
    (!queueSearch || [song.title, requesterName(song)].some((text) => String(text || "").toLowerCase().includes(queueSearch))));
  $("queue-match-count").textContent = queueFiltered() ? t("m0058") + visible.length + "／" + state.queue.length + t("m0033") : "";
  $("queue-empty").hidden = visible.length !== 0;
  $("queue-empty").textContent = queueSearch ? t("m0059") : queueMine ? t("m0060") : t("m0061");
  const occurrences = new Map();
  for (const song of visible) {
    const li = document.createElement("li");
    li.dataset.position = String(song.position);
    const key = JSON.stringify([song.title, song.url, song.duration, song.requester]);
    const occurrence = occurrences.get(key) || 0; occurrences.set(key, occurrence + 1);
    li.dataset.key = key + occurrence;
    const number = document.createElement("span");
    number.className = "number"; number.textContent = String(song.position).padStart(2, "0");
    const img = imageElement(song.thumbnail);
    const info = document.createElement("div"); info.className = "song";
    const title = songTitle(document.createElement("p"), song);
    const source = document.createElement("small"); source.textContent = t("m0062") + requesterName(song);
    const estimate = document.createElement("small"); estimate.className = "queue-estimate";
    info.append(title, source, estimate);
    const time = document.createElement("span"); time.className = "song-length";
    time.textContent = song.duration ? duration(song.duration) : t("m0063");
    const actions = document.createElement("div"); actions.className = "actions";
    const rev = state.revision;
    const handle = document.createElement("button");
    handle.textContent = "⋮⋮"; handle.className = "drag-handle";
    handle.setAttribute("aria-label", t("m0064") + song.title + t("m0065"));
    handle.setAttribute("aria-describedby", "drag-help");
    handle.title = queueFiltered() ? t("m0066") : t("m0067");
    handle.dataset.boundary = queueFiltered() ? "1" : "0";
    installDrag(handle, li, song.position, rev);
    actions.append(handle);
    for (const [text, label, target] of [["↑", t("m0068"), song.position - 1], ["↓", t("m0069"), song.position + 1], ["×", t("m0004"), null]]) {
      const button = document.createElement("button"); button.textContent = text;
      button.setAttribute("aria-label", label + "：" + song.title);
      button.title = label;
      button.dataset.boundary = target !== null && (target < 1 || target > state.queue.length) ? "1" : "0";
      button.addEventListener("click", () => target === null
        ? act("queue/" + song.position, {revision: rev}, "DELETE")
        : act("queue/move", {from: song.position, to: target, revision: rev}));
      actions.append(button);
    }
    if (typeof librarySaveButton === "function" && safeURL(song.url)) actions.append(librarySaveButton(song));
    li.append(number, img, info, time, actions); $("queue").append(li);
  }
  if (!reduceMotion()) for (const row of $("queue").children) {
    const top = before.get(row.dataset.key), next = row.getBoundingClientRect().top;
    if (Number.isFinite(top) && top !== next && row.animate)
      row.animate([{transform: "translateY(" + (top - next) + "px)"}, {transform: "none"}],
        {duration: 240, easing: "cubic-bezier(.2,.8,.2,1)"});
  }
}
const selectionLocks = new Set();
function noSelection(kind, active) {
  if (active) selectionLocks.add(kind); else selectionLocks.delete(kind);
  document.body.classList.toggle("no-selection", selectionLocks.size > 0);
}
function connectionStatus(value) {
  const badge = $("connection");
  badge.textContent = t("m0070"); badge.title = value;
  badge.dataset.state = [t("m0125"),t("m0186"),t("m0187")].some(label=>value.includes(label)) ? "reconnecting"
    : [t("m0123"),t("m0188")].some(label=>value.includes(label)) ? "online" : "offline";
  badge.setAttribute("aria-label", t("m0071") + value);
}
let drag = null, dragVisual = null;
function settleDrag() {
  if (!dragVisual) return;
  for (const row of dragVisual.rows) {
    row.style.transform = "";
    row.classList.toggle("dragging", false);
    row.classList.toggle("settling", false);
  }
  dragVisual = null;
}
function previewDrag(drop = false) {
  if (!drag?.active || reduceMotion()) return;
  const rows = Array.from($("queue").children);
  const height = drag.row.offsetHeight || drag.row.getBoundingClientRect().height;
  const targetRow = rows.find((row) => Number(row.dataset.position) === drag.target);
  const displacement = Number.isFinite(targetRow?.offsetTop) && Number.isFinite(drag.row.offsetTop)
    ? targetRow.offsetTop - drag.row.offsetTop +
      (drag.target > drag.from ? targetRow.offsetHeight - height : 0)
    : (drag.target - drag.from) * height;
  dragVisual = {rows};
  for (const row of rows) {
    const position = Number(row.dataset.position);
    let offset = 0;
    if (position === drag.from) offset = drop
      ? displacement : drag.y - drag.startY;
    else if (drag.target > drag.from && position > drag.from && position <= drag.target) offset = -height;
    else if (drag.target < drag.from && position >= drag.target && position < drag.from) offset = height;
    row.style.transform = "translateY(" + offset + "px)" +
      (position === drag.from && !drop ? " scale(1.025)" : "");
    row.classList.toggle("settling", drop);
  }
}

function cancelDrag(message, preserve = false) {
  noSelection("queue", false);
  if (!drag) { if (!preserve) settleDrag(); return; }
  if (!preserve) settleDrag();
  const old = drag; drag = null;
  if (old.active) suppressSongLinksUntil = Date.now() + 600;
  window.clearTimeout(old.timer);
  window.cancelAnimationFrame(old.frame);
  old.row.classList.toggle("dragging", false);
  if (old.targetRow) {
    old.targetRow.classList.toggle("drop-target", false);
    old.targetRow.classList.toggle("drop-after", false);
  }
  document.body.classList.toggle("queue-dragging", false);
  if (old.handle.hasPointerCapture(old.pointerId)) old.handle.releasePointerCapture(old.pointerId);
  if (message) notice(message, true);
}
function dragTarget() {
  if (!drag || !drag.active) return;
  // Hit testing ignores visual transforms, including the row following the pointer.
  let row = Array.from($("queue").children).find((candidate) => {
    const rect = candidate.getBoundingClientRect();
    const shift = parseFloat((candidate.style.transform || "").replace("translateY(", "")) || 0;
    return drag.y >= rect.top - shift && drag.y <= rect.bottom - shift;
  });
  row = row || document.elementFromPoint(drag.x, drag.y)?.closest("#queue > li");
  if (!row) return;
  if (drag.targetRow) {
    drag.targetRow.classList.toggle("drop-target", false);
    drag.targetRow.classList.toggle("drop-after", false);
  }
  drag.target = Number(row.dataset.position); drag.targetRow = row;
  row.classList.toggle("drop-target", drag.target !== drag.from);
  row.classList.toggle("drop-after", drag.target > drag.from);
  previewDrag();
}
function dragScroll() {
  if (!drag || !drag.active) return;
  const top = 85, bottom = window.innerHeight - document.querySelector(".playback-bar").getBoundingClientRect().height - 65;
  if (drag.y < top) window.scrollBy(0, -10);
  else if (drag.y > bottom) window.scrollBy(0, 10);
  dragTarget();
  drag.frame = window.requestAnimationFrame(dragScroll);
}
function activateDrag() {
  if (!drag) return;
  drag.active = true;
  drag.row.classList.toggle("dragging", true);
  document.body.classList.toggle("queue-dragging", true);
  notice(t("m0072"));
  dragTarget(); drag.frame = window.requestAnimationFrame(dragScroll);
}
function installDrag(handle, row, from, rev) {
  handle.addEventListener("pointerdown", (event) => {
    if (handle.disabled || queueFiltered() || event.button !== 0 || event.isPrimary === false || busy || !connected || drag) return;
    drag = {handle, row, from, target: from, rev, pointerId: event.pointerId,
      x: event.clientX, y: event.clientY, startX: event.clientX, startY: event.clientY,
      active: false, touch: event.pointerType !== "mouse", epoch: generation};
    noSelection("queue", true);
    handle.setPointerCapture(event.pointerId);
    if (drag.touch) drag.timer = window.setTimeout(activateDrag, 420);
  });
  handle.addEventListener("pointermove", (event) => {
    if (!drag || drag.handle !== handle || drag.pointerId !== event.pointerId) return;
    drag.x = event.clientX; drag.y = event.clientY;
    if (!drag.active && Math.hypot(drag.x - drag.startX, drag.y - drag.startY) > 8) {
      if (drag.touch) { cancelDrag(); return; }
      activateDrag();
    }
    if (drag && drag.active) { event.preventDefault(); dragTarget(); }
  });
  handle.addEventListener("pointerup", (event) => {
    if (!drag || drag.handle !== handle || drag.pointerId !== event.pointerId) return;
    const completed = drag;
    const move = completed.active && completed.epoch === generation && completed.from !== completed.target;
    if (move) previewDrag(true);
    cancelDrag(undefined, move);
    if (move) return act("queue/move", {from: completed.from, to: completed.target, revision: completed.rev});
  });
  for (const type of ["pointercancel", "lostpointercapture"]) handle.addEventListener(type, () => {
    if (drag && drag.handle === handle) cancelDrag();
  });
}
function shortcutEditing(target) {
  return !!(target?.isContentEditable || target?.closest?.(
    'input, select, textarea, [contenteditable]:not([contenteditable="false"]), [role="textbox"], [role="combobox"], [role="menu"], [role="menuitem"]'));
}
function shortcutsHelp() {
  if (!document.querySelector('dialog[open], [role="dialog"][aria-modal="true"]:not([hidden])'))
    $("shortcuts-dialog").showModal();
}
function keyboardShortcut(event) {
  if (event.key === "Escape") {
    if ($("shortcuts-dialog").open) { event.preventDefault(); $("shortcuts-dialog").close(); }
    closeSongChoices(); cancelDrag(t("m0073")); cancelSeek(); noSelection("volume", false);
    return;
  }
  if (event.defaultPrevented || event.repeat || event.isComposing || event.ctrlKey || event.altKey || event.metaKey ||
      !window.matchMedia?.("(hover: hover) and (pointer: fine)").matches ||
      !(authMode === "owner" || authenticated) || $("dashboard").hidden ||
      shortcutEditing(event.target) || shortcutEditing(document.activeElement) ||
      document.querySelector('dialog[open], [role="dialog"][aria-modal="true"]:not([hidden])')) return;
  const key = event.key;
  if (key === "?") { event.preventDefault(); shortcutsHelp(); return; }
  if (key === "/" && !$("enqueue").disabled) {
    event.preventDefault();
    if (typeof libraryView === "function") libraryView("play");
    $("query").focus(); return;
  }
  const id = key === " " ? "toggle" : key?.toLowerCase() === "n" ? "skip" : null;
  // Preserve native Space activation on a focused button/link.
  if (key === " " && event.target?.closest?.("button, a, summary")) return;
  if (id && !$(id).disabled) { event.preventDefault(); return $(id).click(); }
  if (["ArrowLeft", "ArrowRight"].includes(key) && !$("progress").disabled) {
    event.preventDefault();
    const input = $("progress");
    if (!beginSeek(input, "shortcut")) return;
    input.value = Math.max(0, Math.min(state.current.duration, localProgress() + (key === "ArrowLeft" ? -10 : 10)));
    drawProgress(Number(input.value));
    return commitSeek();
  }
}
document.addEventListener("keydown", keyboardShortcut);
$("shortcuts-help").addEventListener("click", shortcutsHelp);
$("shortcuts-close").addEventListener("click", () => $("shortcuts-dialog").close());
let resolving = false, resolveGeneration = 0, previewResults = [], previewDuplicates = [];
function duplicateNote(parent, url, batch = false) {
  const note = document.createElement(batch ? "small" : "p");
  note.className = batch ? "duplicate-tag" : "hint duplicate-note";
  note.setAttribute("role", "status");
  previewDuplicates.push({note, key: songIdentity(url), batch});
  parent.append(note);
}
function updateDuplicateNotes() {
  const queued = new Map();
  for (const song of state?.queue || []) {
    const key = songIdentity(song.url);
    if (key && !queued.has(key)) queued.set(key, song.position);
  }
  const current = songIdentity(state?.current?.url);
  for (const {note, key, batch} of previewDuplicates) {
    const position = key ? queued.get(key) : undefined;
    const playing = !!key && key === current;
    note.textContent = position !== undefined
      ? batch ? t("m0074") : t("m0075") + position + t("m0033") + (playing ? t("m0076") : "")
      : playing ? batch ? t("m0077") : t("m0078") : "";
    note.hidden = !note.textContent;
  }
}
function clearPreview() {
  ++resolveGeneration; resolving = false; previewResults = []; previewDuplicates = [];
  buttonBusy($("enqueue"), false);
  $("preview-panel").hidden = true; $("preview-results").replaceChildren();
}
async function resolveQuery() {
  const query = $("query").value.trim();
  if (!query || resolving || busy || !connected || !selected) return;
  clearPreview();
  const epoch = generation, requestId = ++resolveGeneration, guild = selected;
  resolving = true; buttonBusy($("enqueue"), true); controls(); notice(t("m0079"));
  try {
    const action = $("request-action").value === "playnext" ? "playnext" : "play";
    const result = await api("api/guilds/" + guild + "/resolve", "POST", {query, action});
    if (epoch !== generation || requestId !== resolveGeneration) return;
    renderPreviewResults(result.results, action);
    notice(t("m0080"));
  } catch (error) {
    if (epoch === generation && requestId === resolveGeneration) notice(error.message, true);
  } finally {
    if (epoch === generation && requestId === resolveGeneration) { resolving = false; buttonBusy($("enqueue"), false); controls(); }
  }
}

function renderPreviewResults(results, action = "play") {
  $("preview-results").replaceChildren();
  previewDuplicates = [];
    previewResults = results;
    $("preview-panel").hidden = false;
    for (const song of previewResults) {
      const article = document.createElement("article"); article.className = "preview-item";
      const art = document.createElement("div"); art.className = "art";
      const icon = document.createElement("span"); icon.textContent = "♫";
      art.append(icon, imageElement(song.thumbnail, ""));
      const info = document.createElement("div");
      const title = document.createElement("h3"); title.textContent = song.title;
      const length = document.createElement("small");
      length.textContent = song.kind === "playlist"
        ? t("m0081") + song.count + t("m0082") + song.checked_count + t("m0083") + song.eligible_count + t("m0084")
        : song.duration ? duration(song.duration) : t("m0085");
      const link = document.createElement("a"); link.textContent = song.url || t("m0086");
      if (safeURL(song.url)) { link.href = song.url; link.target = "_blank"; link.rel = "noopener noreferrer"; }
      info.append(title, length, link);
      if (song.reason || song.warning) {
        const reason = document.createElement("p"); reason.className = song.reason ? "reason" : "hint";
        reason.textContent = song.reason || song.warning; info.append(reason);
      }
      const button = document.createElement("button"); button.className = "primary";
      const selectedItems = new Set();
      const checkboxes = [];
      let saveButton = null, selectionCount = null;
      const updateSelection = () => {
        if (selectionCount) selectionCount.textContent = t("m0087") + selectedItems.size + t("m0033");
        if (saveButton) saveButton.disabled = !selectedItems.size || libraryBusy;
        buttonLabel(button, song.kind === "playlist" ? "m0088" : song.allowed ? "m0090" : "m0091", song.kind === "playlist" ? selectedItems.size : null, "m0089");
        button.dataset.boundary = song.allowed && (song.kind !== "playlist" || selectedItems.size) ? "0" : "1";
        controls();
      };
      if (song.entries) {
        const hint = document.createElement("p"); hint.className = "hint playlist-next-hint";
        hint.textContent = t("m0092");
        info.append(hint);
        const tools = document.createElement("div"); tools.className = "selection-tools";
        for (const [label, checked] of [[t("m0093"), true], [t("m0094"), false]]) {
          const select = document.createElement("button"); select.type = "button"; select.textContent = label;
          select.dataset.boundary = song.allowed ? "0" : "1";
          select.addEventListener("click", () => {
            if (select.disabled) return;
            for (const [checkbox, item] of checkboxes) {
              checkbox.checked = checked && item.allowed && song.allowed;
              if (checkbox.checked) selectedItems.add(item.item_id);
              else selectedItems.delete(item.item_id);
            }
            updateSelection();
          });
          tools.append(select);
        }
        selectionCount = document.createElement("span"); tools.append(selectionCount);
        const list = document.createElement("ol"); list.className = "playlist-selection";
        for (const item of song.entries) {
          const li = document.createElement("li"), label = document.createElement("label");
          const checkbox = document.createElement("input"); checkbox.type = "checkbox";
          checkbox.checked = !!item.allowed && !!song.allowed && item.default_selected !== false;
          checkbox.dataset.boundary = item.allowed && song.allowed ? "0" : "1";
          checkbox.disabled = checkbox.dataset.boundary === "1";
          checkbox.setAttribute("aria-label", t("m0095") + item.title);
          if (checkbox.checked) selectedItems.add(item.item_id);
          checkbox.addEventListener("change", () => {
            if (checkbox.disabled) return;
            if (checkbox.checked) selectedItems.add(item.item_id);
            else selectedItems.delete(item.item_id);
            updateSelection();
          });
          checkboxes.push([checkbox, item]);
          const text = document.createElement("span");
          text.textContent = (item.is_requested ? t("m0096") : "") + item.title + " · " + (item.duration ? duration(item.duration) : t("m0097")) +
            (item.reason ? t("m0098") + item.reason : t("m0099"));
          label.append(checkbox, imageElement(item.thumbnail), text); duplicateNote(label, item.url, true);
          li.append(label); list.append(li);
        }
        info.append(tools, list);
        if ((song.source_url || song.saveable) && typeof librarySavePreview === "function") {
          const nameLabel = document.createElement("label"); nameLabel.textContent = t("m0100");
          const name = document.createElement("input"); name.maxLength = 60; name.value = Array.from(song.title).slice(0, 60).join("");
          nameLabel.append(name);
          saveButton = document.createElement("button"); saveButton.type = "button";
          buttonLabel(saveButton, "m0101");
          saveButton.addEventListener("click", () => librarySavePreview(song, selectedItems, name.value, saveButton));
          info.append(nameLabel, saveButton);
        }
      }
      updateSelection();
      const confirmSong = async (target, clicked = button) => {
        if (clicked.disabled || busy) return;
        const payload = {query: song.url, preview_id: song.preview_id};
        if (song.kind === "playlist") payload.selected_items = song.entries
          .filter((item) => selectedItems.has(item.item_id)).map((item) => item.item_id);
        buttonBusy(clicked, true, song.kind === "playlist" ? selectedItems.size : null);
        try {
          if (await act(target, payload)) {
            clearPreview(); $("query").value = ""; controls();
          }
        } finally { buttonBusy(clicked, false); controls(); }
      };
      button.addEventListener("click", () => confirmSong(action));
      if (action === "playnext") buttonLabel(button, song.allowed ? "m0104" : "m0105");
      article.append(art, info, button);
      if (song.kind !== "playlist") {
        const alternate = document.createElement("button");
        alternate.type = "button"; alternate.className = "subtle preview-alternate";
        alternate.dataset.boundary = song.allowed ? "0" : "1";
        buttonLabel(alternate, action === "play" ? "m0104" : "m0090");
        alternate.addEventListener("click", () => confirmSong(action === "play" ? "playnext" : "play", alternate));
        article.append(alternate);
        duplicateNote(article, song.url);
      }
      $("preview-results").append(article);
    }
    updateDuplicateNotes();
}

function render(next, force = false) {
  const previousTrack = currentTrackKey();
  state = next; stateAt = Date.now();
  if (seekDrag && seekDrag.track !== currentTrackKey()) cancelSeek();
  if (previousTrack !== currentTrackKey()) { resetLyrics(false); closeSongChoices(false); spotifyPrefetch(); }
  const source = songLinkURL(state.current?.url || "");
  $("source-link").hidden = !source;
  if (source) {
    $("source-link").href = source;
    $("source-link").textContent = /^https?:\/\/(www\.)?(youtube\.com|youtu\.be)\//i.test(source) ? t("m0106") : t("m0107");
  } else $("source-link").removeAttribute("href");
  if (typeof favoriteRender === "function") favoriteRender();
  $("toggle").textContent = state.status === "playing" ? t("m0108") : t("m0109");
  $("bar-title").textContent = state.current?.title || t("m0110");
  $("bar-title").disabled = !state.current;
  $("bar-status").textContent = state.current ? (labels()[state.status] || t("m0111")) + t("m0112") + requesterName(state.current) : t("m0113");
  $("playback-bar").classList.toggle("is-empty", !state.current);
  const cover = safeURL(state.current?.thumbnail || "");
  if (cover) { $("bar-cover").src = cover; $("bar-cover").hidden = false; }
  else { $("bar-cover").hidden = true; $("bar-cover").removeAttribute("src"); }
  const total = state.current ? state.current.duration : 0;
  drawProgress(seekDrag ? seekDrag.position : state.progress, total);
  lyricsOpen = lyricsPreference && !!state.current && state.lyrics_available !== false;
  $("lyrics-panel").hidden = !lyricsOpen || !$("song-choices").hidden;
  $("lyrics-toggle").setAttribute("aria-expanded", String(lyricsOpen));
  if (!lyricsOpen) { window.clearTimeout(lyricsOffsetTimer); lyricsOffsetTimer = null; }
  if (lyricsOpen && state.current && lyricsTrack !== currentTrackKey() && !lyricsLoading) loadLyrics();
  syncLyrics();
  for (const id of ["volume"]) if ((force || document.activeElement !== $(id)) && state.volume !== null) {
    $(id).value = state.volume; $(id + "-label").value = state.volume + "%";
  }
  $("repeat").value = state.repeat;
  $("repeat").textContent = {off:t("m0114"),song:t("m0115"),all:t("m0116")}[state.repeat] || t("m0114");
  $("repeat").setAttribute("aria-label",t("m0117") + ({off:t("m0118"),song:t("m0115"),all:t("m0119")}[state.repeat] || t("m0118")));
  $("repeat").setAttribute("aria-pressed", String(state.repeat !== "off"));
  renderQueue(); renderRecommendations(); updateDuplicateNotes(); controls(); updateQueueTimes(); renderCommunity(state);
}
async function act(action, data = {}, method = "POST") {
  if (busy || !selected || !connected) return;
  const guild = selected, epoch = generation;
  if (drag) cancelDrag();
  ++stateGeneration;
  busy = true; controls(); notice(["play", "playnext"].includes(action) ? t("m0120") : t("m0121"));
  let result;
  try {
    result = await api("api/guilds/" + guild + "/" + action, method, data);
    if (epoch === generation) {
      render(result.state, true); notice(result.message, result.added === 0 && result.skipped > 0);
      if (result.undo_token) {
        const version = toastVersion;
        window.clearTimeout(toastTimer);
        const undo = document.createElement("button"); undo.type = "button"; buttonLabel(undo, "m0122");
        undo.addEventListener("click", async () => {
          if (busy || undo.disabled || epoch !== generation) return;
          undo.disabled = true; buttonBusy(undo, true);
          await act("queue/undo", {undo_token:result.undo_token});
        });
        $("notice").append(undo);
        toastTimer = window.setTimeout(() => { if (version === toastVersion) notice(""); }, 10000);
      }
    }
  } catch (error) {
    if (epoch === generation) {
      if (error.body?.results) renderPreviewResults(error.body.results);
      notice(error.message, true);
    }
  } finally {
    settleDrag(); busy = false; controls();
    // Always reconcile after failure: the bot may already have changed state.
    if (epoch === generation) await refresh(epoch, true);
  }
  return !!result;
}
async function refresh(epoch = generation, force = false) {
  const guild = selected, sequence = ++stateGeneration;
  if (!guild) return;
  try {
    const next = await api("api/guilds/" + guild + "/state");
    if (epoch !== generation || guild !== selected || sequence !== stateGeneration) return;
    connected = true; connectionStatus(t("m0123")); render(next, force);
    if (fallbackPolling && !historyLoading && Date.now() - historyUpdated >= 15000) refreshHistory();
  } catch (error) {
    if (epoch !== generation || guild !== selected || sequence !== stateGeneration) return;
    connected = false; connectionStatus(t("m0124"));
    notice(error.message, true); controls();
  }
}
function resetView() {
  if (typeof popularClear === "function") popularClear();
  $("shortcuts-dialog").close();
  cancelDrag(); cancelSeek(); clearPreview(); resetHistory(); resetLyrics(true);
  queueSearch = ""; $("queue-search").value = "";
  queueMine = false; setQueueFilter(false);
  queueRevision = null;
  render({status: "disconnected", current: null, progress: 0, volume: null,
    repeat: "off", queue: [], revision: ""});
}

function rememberGuild(value) {
  try { window.localStorage?.setItem("musicbot-dashboard-guild", value); } catch { /* Storage may be disabled. */ }
  try { window.sessionStorage?.removeItem("musicbot-dashboard-entry-guild"); } catch { /* Storage may be disabled. */ }
}

function captureEntryGuild() {
  try {
    const url = new URL(window.location.href);
    entryGuild = url.searchParams.get("guild") || url.searchParams.get("guild_id") || "";
  } catch { entryGuild = ""; }
  if (entryGuild && !/^[0-9]{1,20}$/.test(entryGuild)) entryGuild = "";
  try {
    if (entryGuild) window.sessionStorage?.setItem("musicbot-dashboard-entry-guild", entryGuild);
    else entryGuild = window.sessionStorage?.getItem("musicbot-dashboard-entry-guild") || "";
  } catch { /* A direct URL still works if browser storage is disabled. */ }
}
function initialGuild(data) {
  const valid = value => typeof value === "string" && data.guilds.some(guild => guild.id === value);
  if (valid(manualGuild)) return manualGuild;
  let explicit = "", remembered = "";
  try {
    const url = new URL(window.location.href);
    explicit = url.searchParams.get("guild") || url.searchParams.get("guild_id") || "";
  } catch { /* A URL without a server uses the normal preference order. */ }
  if (!explicit && typeof entryGuild === "string") explicit = entryGuild;
  try { remembered = window.localStorage?.getItem("musicbot-dashboard-guild") || ""; } catch { /* Private browsing. */ }
  return [explicit, data.recommended_guild_id, remembered, data.guilds[0]?.id].find(valid) || "";
}

async function connect() {
  if (authMode !== "owner" && !authenticated) return;
  stopEvents(); fallbackPolling = true;
  const epoch = ++generation;
  loading = true; connected = false; selected = ""; state = null;
  resetView(); controls(); connectionStatus(t("m0125"));
  try {
    const data = await api("api/guilds");
    if (epoch !== generation) return;
    $("guild").replaceChildren();
    for (const guild of data.guilds) {
      const option = document.createElement("option");
      option.value = guild.id; option.textContent = guild.name; $("guild").append(option);
    }
    selected = initialGuild(data);
    $("guild").value = selected;
    if (selected) rememberGuild(selected);
    if (!selected) { notice(authMode === "owner" ? t("m0126") : t("m0127")); return; }
    await refresh(epoch);
    if (connected && typeof adminCapability === "function") adminCapability();
    if (connected && typeof libraryLoad === "function") libraryLoad().catch(() => {});
    if (connected) { notice(t("m0128")); startEvents(); }
  } catch (error) {
    if (epoch === generation) {
      notice(error.message, true); connectionStatus(t("m0129"));
    }
  } finally {
    if (epoch === generation) loading = false;
    controls();
  }
}
let sessionCheckedAt = Date.now();
async function poll() {
  if (!document.hidden && authMode === "discord" && authenticated && Date.now()-sessionCheckedAt >= 86400000) {
    sessionCheckedAt = Date.now();
    try { const profile = await api("/auth/session"); if (!profile.authenticated) signedOut(); }
    catch (error) { notice(error.message, true); }
  }
  if (!document.hidden && fallbackPolling && (authMode === "owner" || authenticated) && !busy && !loading) {
    if (selected) await refresh();
    else await connect();
  }
  window.setTimeout(poll, document.hidden ? 10000 : 1000);
}
function closeSongChoices(restore = true) {
  const wasOpen = !$("song-choices").hidden;
  $("song-choices").hidden = true;
  if (typeof lyricsOpen !== "undefined") $("lyrics-panel").hidden = !lyricsOpen;
  $("bar-title").setAttribute("aria-expanded", "false");
  if (wasOpen && restore) $("bar-title").focus();
}
$("bar-title").addEventListener("click", () => {
  if (!state?.current) return;
  const open = $("song-choices").hidden;
  closeSongChoices(false);
  if (open) { $("lyrics-panel").hidden = true; $("song-choices").hidden = false; $("bar-title").setAttribute("aria-expanded", "true"); $("source-link").focus(); }
});
document.addEventListener("pointerdown", event => {
  if (!event.target.closest?.(".bar-copy")) closeSongChoices(false);
});
document.addEventListener("focusin", event => {
  if (!event.target.closest?.(".bar-copy")) closeSongChoices(false);
});
for (const id of ["source-link", "song-spotify"]) $(id).addEventListener("click", () => closeSongChoices());
$("song-choices").addEventListener("keydown", event => {
  if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
    event.preventDefault();
    const links = [$("source-link"), $("song-spotify")];
    links[event.key === "Home" ? 0 : event.key === "End" ? 1 : document.activeElement === links[0] ? 1 : 0].focus();
  }
});
$("guild").addEventListener("change", async () => {
  stopEvents(); fallbackPolling = true;
  ++generation; selected = $("guild").value; state = null;
  manualGuild = selected; rememberGuild(selected);
  if (typeof adminClear === "function") adminClear();
  connected = false; resetView(); controls(); await refresh(); startEvents();
  if (typeof adminCapability === "function") await adminCapability();
});
$("auth-form").addEventListener("submit", (event) => {
  event.preventDefault(); secret = $("secret").value.trim(); connect();
});
$("forget").addEventListener("click", () => {
  secret = ""; $("secret").value = ""; connect();
});
$("play-form").addEventListener("submit", (event) => {
  event.preventDefault(); return resolveQuery();
});
$("preview-close").addEventListener("click", () => { clearPreview(); controls(); });
$("bar-cover").addEventListener("error", () => { $("bar-cover").hidden = true; });
$("toggle").addEventListener("click", () => act(state.status === "playing" ? "pause" : "resume"));
$("skip").addEventListener("click", () => act("skip"));
$("repeat").addEventListener("click", () => act("repeat", {mode: {off:"song",song:"all",all:"off"}[state.repeat] || "off"}));
for (const id of ["volume"]) {
  const input = $(id);
  input.addEventListener("input", () => { $(id + "-label").value = input.value + "%"; });
  input.addEventListener("change", () => { noSelection("volume", false); return act("volume", {volume: Number(input.value)}); });
  input.addEventListener("pointerdown", () => { if (!input.disabled) noSelection("volume", true); });
  for (const type of ["pointerup", "pointercancel", "lostpointercapture", "blur"])
    input.addEventListener(type, () => noSelection("volume", false));
}
$("shuffle").addEventListener("click", () => { if (!$("shuffle").disabled && !queueFiltered()) return act("queue/shuffle", {revision: state.revision}); });
$("logout").addEventListener("click", () => logout());
$("logout-all").addEventListener("click", () => logout(true));
$("user-avatar").addEventListener("error", () => { $("user-avatar").hidden = true; });

// Seek previews are separate from server state: polling can update other controls.
let seekDrag = null;
function currentTrackKey() {
  return state?.current ? JSON.stringify([selected, state.current.url, state.current.title, state.current.duration, state.current.track_token]) : "";
}
function drawProgress(position, total = state?.current?.duration || 0) {
  const value = total ? Math.max(0, Math.min(Number(position) || 0, total)) : 0;
  for (const id of ["progress"]) {
    $(id).max = total || 1; $(id).value = value;
    $(id).setAttribute("aria-valuetext", duration(value) + t("m0130") + (total ? duration(total) : t("m0097")));
  }
  for (const id of ["elapsed"]) $(id).textContent = duration(value);
  for (const id of ["duration"]) $(id).textContent = total ? duration(total) : t("m0085");
}
function cancelSeek() {
  noSelection("seek", false);
  seekDrag = null;
}
function beginSeek(input, kind, event = {}) {
  if (input.disabled || busy || !connected || !state?.current) return false;
  if (seekDrag && seekDrag.input !== input) cancelSeek();
  if (kind === "pointer") noSelection("seek", true);
  if (!seekDrag) seekDrag = {input, kind, guild: selected, epoch: generation,
    track: currentTrackKey(), trackToken: state.current.track_token, position: Number(input.value), pointerId: event.pointerId};
  return true;
}
async function commitSeek() {
  const completed = seekDrag;
  if (!completed) return;
  completed.position = Number(completed.input.value);
  cancelSeek();
  if (completed.epoch !== generation || completed.guild !== selected || completed.track !== currentTrackKey()) return;
  return act("seek", {position: completed.position, track_token: completed.trackToken});
}
function installSeek(id) {
  const input = $(id);
  input.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || event.isPrimary === false) return;
    beginSeek(input, "pointer", event);
  });
  input.addEventListener("input", () => {
    if (!beginSeek(input, "assistive")) return;
    seekDrag.position = Number(input.value); drawProgress(seekDrag.position);
  });
  const keys = ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End", "PageUp", "PageDown"];
  input.addEventListener("keydown", (event) => {
    if (event.key === "Escape") { cancelSeek(); drawProgress(state?.progress); return; }
    if (keys.includes(event.key)) beginSeek(input, "keyboard");
  });
  input.addEventListener("keyup", (event) => {
    if (keys.includes(event.key) && seekDrag?.input === input && seekDrag.kind === "keyboard") return commitSeek();
  });
  input.addEventListener("change", () => {
    // Screen readers can emit input/change without pointer or keyboard events.
    if (seekDrag?.input === input && seekDrag.kind === "assistive") return commitSeek();
  });
  input.addEventListener("blur", () => {
    if (seekDrag?.input !== input) return;
    if (seekDrag.kind !== "pointer") return commitSeek();
    cancelSeek(); drawProgress(state?.progress);
  });
}
// Native range controls manage pointer capture themselves. Taking/releasing it
// here makes Chrome emit lostpointercapture during an otherwise valid drag.
document.addEventListener("pointerup", (event) => {
  noSelection("volume", false);
  if (seekDrag?.kind === "pointer" && seekDrag.pointerId === event.pointerId) return commitSeek();
});
document.addEventListener("pointercancel", (event) => {
  noSelection("volume", false); cancelDrag();
  if (seekDrag?.kind === "pointer" && seekDrag.pointerId === event.pointerId) {
    cancelSeek(); drawProgress(state?.progress);
  }
});

let historyLoading = false, historyRequest = 0, historyUpdated = 0, recentHistory = [], recommendationRevision = null;
function recommendationSongs(history, current) {
  const seen = new Set([songIdentity(current?.url)]);
  return history.filter((song) => {
    const key = songIdentity(song.url);
    if (!key || seen.has(key)) return false;
    seen.add(key); return true;
  }).slice(0, 5);
}
async function previewHistorySong(song, guild = selected, epoch = generation) {
  if (busy || !connected || epoch !== generation || guild !== selected || !safeURL(song.url)) return;
  $("query").value = song.url; $("request-action").value = "play";
  await resolveQuery();
  if (epoch === generation && guild === selected)
    $("preview-panel").scrollIntoView?.({behavior: reduceMotion() ? "auto" : "smooth", block: "nearest"});
}
function renderRecommendations() {
  const songs = state && !state.queue.length ? recommendationSongs(recentHistory, state.current) : [];
  const signature = JSON.stringify([selected, generation, songs]);
  $("queue-recommendations").hidden = songs.length === 0;
  if (signature === recommendationRevision) return;
  recommendationRevision = signature;
  $("recommendation-list").replaceChildren();
  const guild = selected, epoch = generation;
  for (const song of songs) {
    const row = document.createElement("li"), info = document.createElement("div");
    info.className = "history-info";
    const title = songTitle(document.createElement("p"), song);
    const meta = document.createElement("small");
    meta.textContent = (song.duration ? duration(song.duration) : t("m0097")) + t("m0112") + requesterName(song);
    info.append(title, meta);
    const add = document.createElement("button"); add.type = "button"; add.textContent = t("m0131");
    add.setAttribute("aria-label", t("m0132") + song.title);
    add.addEventListener("click", () => { if (!add.disabled) return previewHistorySong(song, guild, epoch); });
    row.append(imageElement(song.thumbnail), info, add); $("recommendation-list").append(row);
  }
}
function resetHistory() {
  ++historyRequest; historyLoading = false; historyUpdated = 0; recentHistory = [];
  recommendationRevision = null; renderRecommendations();
  $("history-list").replaceChildren(); $("history-status").textContent = t("m0133");
}
function playedTime(timestamp) {
  if (timestamp === null || timestamp === undefined || !Number.isFinite(Number(timestamp)) || Number(timestamp) <= 0)
    return t("m0134");
  const date = new Date(Number(timestamp) * 1000), difference = Math.max(0, Date.now() - date.getTime());
  if (!Number.isFinite(date.getTime())) return t("m0134");
  if (difference < 60000) return t("m0135");
  if (difference < 3600000) return Math.floor(difference / 60000) + t("m0136");
  return date.toLocaleString(dashboardLocale(), {timeZone: dashboardTimeZone(), month: "numeric", day: "numeric",
    hour: "2-digit", minute: "2-digit", hour12: false});
}
async function refreshHistory(manual = false) {
  if (!selected || !connected || historyLoading) return;
  const guild = selected, epoch = generation, request = ++historyRequest;
  historyLoading = true; controls();
  try {
    const result = await api("api/guilds/" + guild + "/history");
    if (epoch !== generation || guild !== selected || request !== historyRequest) return;
    applyHistory(result, guild, epoch);
  } catch (error) {
    if (epoch === generation && request === historyRequest) {
      // Optional history failures never disconnect the playback controls.
      $("history-status").textContent = error.message || t("m0137");
      if (manual) notice(error.message, true);
      historyUpdated = Date.now();
    }
  } finally { if (epoch === generation && request === historyRequest) { historyLoading = false; controls(); } }
}

function applyHistory(result, guild = selected, epoch = generation) {
  ++historyRequest; historyLoading = false;
    $("history-list").replaceChildren();
    const entries = recentHistory = (result.history || []).slice(0, 50);
    renderRecommendations();
    $("history-status").textContent = entries.length ? "" : t("m0138");
    for (const song of entries) {
      const row = document.createElement("li"), info = document.createElement("div");
      info.className = "history-info";
      const title = songTitle(document.createElement("p"), song);
      const meta = document.createElement("small");
      meta.textContent = (song.duration ? duration(song.duration) : t("m0097")) + t("m0112") + requesterName(song) + " · " + playedTime(song.played_at);
      info.append(title, meta);
      if (safeURL(song.requester?.avatar)) {
        const avatar = imageElement(song.requester.avatar, "requester-avatar"); avatar.alt = ""; info.append(avatar);
      }
      const actions = document.createElement("div"); actions.className = "history-actions";
      if (safeURL(song.url)) {
        const replay = document.createElement("button"); replay.type = "button"; replay.textContent = t("m0139");
        replay.addEventListener("click", async () => {
          if (replay.disabled || busy || epoch !== generation || guild !== selected) return;
          await previewHistorySong(song, guild, epoch);
        });
        const link = document.createElement("a"); link.textContent = t("m0140");
        link.href = song.url; link.target = "_blank"; link.rel = "noopener noreferrer";
        actions.append(replay, link);
        if (typeof librarySaveButton === "function") actions.append(librarySaveButton(song));
      }
      row.append(imageElement(song.thumbnail), info, actions); $("history-list").append(row);
    }
    historyUpdated = Date.now();
  controls();
}

let lyricsOpen = false, lyricsPreference = false, lyricsLoading = false, lyricsRequest = 0, lyricsTrack = "", lyricsLines = [], lyricsActive = -1;
let lyricsOffset = 0, lyricsVideo = "", lyricsOffsetTimer = null, lyricsOffsetSequence = 0, lyricsTimingBusy = false, lyricsSyncArmed = false;
let lyricsUserScrollUntil = 0, lyricsAutoScrollUntil = 0, lyricsCenterPending = false;
function readLyricsPreference() {
  try { lyricsPreference = window.localStorage?.getItem("musicbot-lyrics:"+viewerKey) === "on"; }
  catch { lyricsPreference = false; }
}
function resetLyrics(close = false) {
  ++lyricsRequest; ++lyricsOffsetSequence; lyricsLoading = false; lyricsTrack = ""; lyricsLines = []; lyricsActive = -1;
  lyricsOffset=0;lyricsVideo="";lyricsSyncArmed=false;lyricsTimingBusy=false;
  window.clearTimeout(lyricsOffsetTimer);lyricsOffsetTimer=null;
  $("lyrics-content").replaceChildren(); $("lyrics-content").textContent = "";
  $("lyrics-content").classList.toggle("plain-lyrics", false);
  $("lyrics-status").textContent = ""; $("lyrics-search-form").hidden = true;
  $("lyrics-query").value = ""; $("lyrics-heading").textContent = t("m0141");
  $("lyrics-offset").textContent="";$("lyrics-sync-prompt").hidden=true;$("lyrics-sync").textContent=t("m0142");
  $("lyrics-timing-controls").hidden=true;
  lyricsUserScrollUntil=0;lyricsAutoScrollUntil=0;lyricsCenterPending=false;
  if (close) {
    lyricsOpen = false; $("lyrics-panel").hidden = true;
    $("lyrics-toggle").setAttribute("aria-expanded", "false");
  }
}
function applyLyricsOffset(value) {
  lyricsOffset = Number.isFinite(Number(value.offset)) ? Number(value.offset) : 0;
  const source = {matched:t("m0143"),silence:t("m0144"),manual:t("m0145"),duration:t("m0146")}[value.offset_source];
  $("lyrics-offset").textContent = (source ? source+" · "+(lyricsOffset>=0?"+":"")+lyricsOffset.toFixed(1)+t("m0147") :
    t("m0148")) + (value.analysis_pending ? t("m0149") : "");
  lyricsActive=-2;syncLyrics();
}
async function pollLyricsOffset() {
  window.clearTimeout(lyricsOffsetTimer);lyricsOffsetTimer=null;
  if (!lyricsOpen || !lyricsVideo || !lyricsLines.length || state?.lyrics_available === false) return;
  if (lyricsTimingBusy) { lyricsOffsetTimer=window.setTimeout(pollLyricsOffset,5000);return; }
  const key=currentTrackKey(),epoch=generation,sequence=++lyricsOffsetSequence,guild=selected;
  try {
    if (!lyricsTimingBusy) {
      const value=await api("api/guilds/"+guild+"/lyrics/offset");
      if (lyricsOpen && key===currentTrackKey() && epoch===generation && sequence===lyricsOffsetSequence) applyLyricsOffset(value);
    }
  } catch (error) {
    if (error.status===403 && epoch===generation && key===currentTrackKey()) {
      if (state) state.lyrics_available=false;
      toggleLyrics(false,false);controls();
    }
  } finally {
    if (lyricsOpen && key===currentTrackKey() && epoch===generation)
      lyricsOffsetTimer=window.setTimeout(pollLyricsOffset,5000);
  }
}
async function loadLyrics(query = "") {
  if (!lyricsOpen || !selected || !connected || !state?.current || state.lyrics_available === false) return;
  const guild = selected, epoch = generation, key = currentTrackKey(), request = ++lyricsRequest;
  lyricsLoading = true; lyricsTrack = key; lyricsLines = []; lyricsActive = -1;
  window.clearTimeout(lyricsOffsetTimer);lyricsOffsetTimer=null;lyricsSyncArmed=false;
  $("lyrics-content").replaceChildren(); $("lyrics-content").textContent = "";
  $("lyrics-content").classList.toggle("plain-lyrics", false);
  $("lyrics-status").textContent = t("m0150"); $("lyrics-search-form").hidden = true; controls();
  $("lyrics-timing-controls").hidden=true;$("lyrics-sync-prompt").hidden=true;$("lyrics-sync").textContent=t("m0142");
  try {
    const result = await api("api/guilds/" + guild + "/lyrics" + (query ? "?query=" + encodeURIComponent(query) : ""));
    if (!lyricsOpen || epoch !== generation || guild !== selected || key !== currentTrackKey() || request !== lyricsRequest) return;
    $("lyrics-heading").textContent = result.artist ? result.title + " · " + result.artist : result.title || t("m0141");
    lyricsVideo=result.video_id || "";
    $("lyrics-offset").textContent="";
    if (result.status === "synced" && Array.isArray(result.lines) && result.lines.length) {
      lyricsLines = result.lines.map((line) => ({time: Number(line.time), text: String(line.text || "")}))
        .filter((line) => Number.isFinite(line.time)).sort((a, b) => a.time - b.time);
      for (const line of lyricsLines) {
        const row = document.createElement("p"); row.textContent = line.text || "♪"; $("lyrics-content").append(row);
      }
      $("lyrics-status").textContent = "";
      $("lyrics-timing-controls").hidden=!lyricsVideo;
      applyLyricsOffset(result);
      if (lyricsVideo) lyricsOffsetTimer=window.setTimeout(pollLyricsOffset,5000);
    } else if (result.status === "plain" && result.plain_lyrics) {
      $("lyrics-content").textContent = result.plain_lyrics;
      $("lyrics-status").textContent = t("m0151"); $("lyrics-content").classList.toggle("plain-lyrics", true);
    } else if (result.status === "instrumental") {
      $("lyrics-status").textContent=t("m0152");
    } else {
      $("lyrics-status").textContent = result.status === "unavailable" ? t("m0153") : t("m0154");
      $("lyrics-search-form").hidden = false;
    }
  } catch (error) {
    if (epoch === generation && request === lyricsRequest && lyricsOpen) {
      $("lyrics-status").textContent = error.message || t("m0155");
      if (error.status===403) { if(state) state.lyrics_available=false;toggleLyrics(false,false); }
      else $("lyrics-search-form").hidden = false;
      notice(error.message, true);
    }
  } finally { if (epoch === generation && request === lyricsRequest) { lyricsLoading = false; controls(); } }
}
function syncLyrics() {
  if (!lyricsOpen || !lyricsLines.length) return;
  const progress = (seekDrag ? seekDrag.position : localProgress()) - lyricsOffset;
  let index = -1;
  for (let i = 0; i < lyricsLines.length && lyricsLines[i].time <= progress; i++) index = i;
  if (index !== lyricsActive) {
    lyricsActive = index;lyricsCenterPending=true;
    Array.from($("lyrics-content").children).forEach((row, i) => {
      row.classList.toggle("current-line", i === index);
      if (i === index) row.setAttribute("aria-current", "true");
      else row.removeAttribute("aria-current");
    });
  }
  if (lyricsCenterPending && Date.now()>=lyricsUserScrollUntil && index>=0) {
    const box=$("lyrics-content"),row=box.children[index];
    // Hidden panels have no layout yet. Keep the pending center until visible.
    if (!row || !box.clientHeight) return;
    const rowRect=row.getBoundingClientRect(),boxRect=box.getBoundingClientRect();
    // Both rectangles use viewport coordinates, independent of offsetParent.
    // Measure after highlighting: the larger active font can wrap onto more lines.
    const top=Math.max(0,box.scrollTop+rowRect.top-boxRect.top-box.clientTop-box.clientHeight/2+rowRect.height/2);
    lyricsAutoScrollUntil=Date.now()+1200;
    // Scroll only this viewport, including the fallback for older browsers.
    if (typeof box.scrollTo === "function") box.scrollTo({top,behavior:reduceMotion()?"auto":"smooth"});
    else box.scrollTop=top;
    lyricsCenterPending=false;
  }
}
function toggleLyrics(open = !lyricsOpen, persist = true) {
  if (open && state?.lyrics_available===false) return;
  if (persist) {
    lyricsPreference=open;
    try { window.localStorage?.setItem("musicbot-lyrics:"+viewerKey,open?"on":"off"); } catch {}
  }
  lyricsOpen = open; $("lyrics-panel").hidden = !open;
  if (open) lyricsCenterPending=true;
  $("lyrics-toggle").setAttribute("aria-expanded", String(open));
  if (!open) { ++lyricsRequest;++lyricsOffsetSequence;lyricsLoading=false;window.clearTimeout(lyricsOffsetTimer);lyricsOffsetTimer=null; }
  else if (lyricsTrack !== currentTrackKey() || !$("lyrics-content").textContent && !lyricsLines.length) return loadLyrics();
  else if(lyricsVideo)lyricsOffsetTimer=window.setTimeout(pollLyricsOffset,5000);
  if (open) syncLyrics();
}
async function changeLyricsOffset(action, extra = {}) {
  if (!lyricsOpen || lyricsTimingBusy || !lyricsVideo || !lyricsLines.length) return;
  const key=currentTrackKey(),epoch=generation,guild=selected,sequence=++lyricsOffsetSequence;
  lyricsTimingBusy=true;controls();
  try {
    const value=await api("api/guilds/"+guild+"/lyrics/offset","POST",{action,track_token:state.current.track_token,...extra});
    if (lyricsOpen && key===currentTrackKey() && epoch===generation && sequence===lyricsOffsetSequence) {
      applyLyricsOffset(value);lyricsSyncArmed=false;$("lyrics-sync").textContent=t("m0142");$("lyrics-sync-prompt").hidden=true;
    }
  } catch(error){if(epoch===generation&&key===currentTrackKey())notice(error.message,true);}
  finally {if(epoch===generation&&key===currentTrackKey()){lyricsTimingBusy=false;controls();}}
}
$("lyrics-minus").addEventListener("click",()=>changeLyricsOffset("adjust",{delta:-.5}));
$("lyrics-plus").addEventListener("click",()=>changeLyricsOffset("adjust",{delta:.5}));
$("lyrics-reset").addEventListener("click",()=>changeLyricsOffset("reset"));
$("lyrics-sync").addEventListener("click",()=>{
  if(!lyricsSyncArmed){
    const first=lyricsLines.find(line=>line.text.trim());if(!first)return;
    lyricsSyncArmed=true;$("lyrics-sync").textContent=t("m0156");
    $("lyrics-sync-prompt").textContent=t("m0157")+first.text+t("m0158");$("lyrics-sync-prompt").hidden=false;
  }else return changeLyricsOffset("sync",{position:localProgress()});
});
function lyricUserScroll() { lyricsUserScrollUntil=Date.now()+5000;lyricsCenterPending=true; }
for(const event of ["wheel","touchstart","pointerdown","keydown"]) $("lyrics-content").addEventListener(event,lyricUserScroll,{passive:true});
$("lyrics-content").addEventListener("scroll",()=>{if(Date.now()>lyricsAutoScrollUntil)lyricUserScroll();},{passive:true});
installSeek("progress");
$("history-refresh").addEventListener("click", () => refreshHistory(true));
$("lyrics-toggle").addEventListener("click", () => toggleLyrics());
$("lyrics-close").addEventListener("click", () => { toggleLyrics(false); $("lyrics-toggle").focus?.(); });
$("lyrics-search-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const query = $("lyrics-query").value.trim();
  if (query && !lyricsLoading) return loadLyrics(query);
});
$("request-action").addEventListener("change", () => { clearPreview(); controls(); });



/* Shared-clock progress and queue estimates. Only received state resets the anchor. */
let stateAt = Date.now(), queueMine = false, queueSearch = "";
function queueFiltered() { return queueMine || !!queueSearch; }
function localProgress(now = Date.now()) {
  const base = Math.max(0, Number(state?.progress) || 0);
  const value = base + (connected && state?.status === "playing" ? Math.max(0, now - stateAt) / 1000 : 0);
  const total = Number(state?.current?.duration);
  return Number.isFinite(total) && total > 0 ? Math.min(total, value) : value;
}
function queueSchedule(value, progress = Number(value?.progress) || 0) {
  const valid = (n) => Number.isFinite(Number(n)) && Number(n) > 0;
  const songs = value?.queue || [];
  const known = songs.reduce((sum, song) => sum + (valid(song.duration) ? Number(song.duration) : 0), 0);
  const unknown = songs.some((song) => !valid(song.duration));
  const minutes = Math.ceil(known / 60);
  const total = (unknown ? t("m0159") : t("m0000")) + Math.floor(minutes / 60) + t("m0160") + minutes % 60 + t("m0161") +
    (unknown ? t("m0162") : "");
  let wait = value?.current && valid(value.current.duration) ? Math.max(0, Number(value.current.duration) - progress) : null;
  const times = new Map();
  for (const song of songs) {
    let text;
    if (value.repeat === "song") text = t("m0163");
    else if (value.status === "paused") text = t("m0164");
    else if (value.status !== "playing" || wait === null) text = t("m0165");
    else text = wait < 60 ? t("m0166") : t("m0167") + Math.ceil(wait / 60) + t("m0168");
    times.set(song.position, text);
    if (wait !== null) wait = valid(song.duration) ? wait + Number(song.duration) : null;
  }
  return {total, times};
}
function updateQueueTimes() {
  const schedule = queueSchedule(state, localProgress());
  $("queue-total").textContent = schedule.total;
  $("queue-timing-note").textContent = state?.repeat === "all" ? t("m0169") : "";
  for (const row of $("queue").children) {
    const time = row.children[2]?.children[2];
    if (time) time.textContent = schedule.times.get(Number(row.dataset.position)) || t("m0165");
  }
}
function setQueueFilter(mine) {
  queueMine = mine;
  cancelDrag(); queueRevision = null;
  $("queue-all").setAttribute("aria-pressed", String(!mine));
  $("queue-mine").setAttribute("aria-pressed", String(mine));
  const reason = [mine ? t("m0170") : "", queueSearch ? t("m0171") : ""].filter(Boolean).join("＋");
  $("drag-help").textContent = reason
    ? reason + t("m0172")
    : t("m0173");
  $("shuffle").title = reason ? reason + t("m0174") : t("m0175");
  if (state) { renderQueue(); controls(); updateQueueTimes(); }
}
function renderCommunity(value) {
  const listeners = value?.listeners || {connected: false, members: []};
  const members = listeners.members || [];
  $("listeners-status").textContent = listeners.connected
    ? (listeners.channel || t("m0176")) + "・" + members.length + t("m0177")
    : t("m0178");
  const list = $("listeners-list"); list.replaceChildren();
  const add = (member, parent) => {
    const row = document.createElement("span"); row.className = "listener";
    const name = document.createElement("span"); name.textContent = member.name;
    row.append(imageElement(member.avatar, "listener-avatar"), name); parent.append(row);
  };
  members.slice(0, 8).forEach((member) => add(member, list));
  if (members.length > 8) {
    const details = document.createElement("details"), summary = document.createElement("summary");
    summary.textContent = t("m0179") + (members.length - 8) + t("m0177"); details.append(summary);
    const more = document.createElement("div"); more.className = "listeners-list";
    members.slice(8).forEach((member) => add(member, more)); details.append(more); list.append(details);
  }
  const records = (value?.activity?.activity || []).slice(0, 100);
  $("activity-list").replaceChildren();
  $("activity-status").textContent = records.length ? t("m0180") : t("m0181");
  for (const item of records) {
    const row = document.createElement("li"), line = document.createElement("p"), meta = document.createElement("small");
    line.textContent = item.actor + "・" + item.detail;
    const stamp = new Date(Number(item.time) * 1000);
    const time = Number.isFinite(stamp.getTime()) ? stamp.toLocaleTimeString(dashboardLocale(),
      {timeZone: dashboardTimeZone(), hour12: false}) : t("m0182");
    meta.textContent = time + "・" + ({web: t("m0183"), discord_text: t("m0184"), discord_slash: t("m0185")}[item.source] || "Discord") + "・" + item.result;
    row.append(line, meta); $("activity-list").append(row);
  }
}
/* EventSource is manually reopened so its retry is bounded and observable. */
let eventSource = null, eventTimer = null, eventWatchdog = null, eventEpoch = 0;
let eventFailures = 0, fallbackPolling = true, nextStreamTry = 0;
function stopEvents() {
  ++eventEpoch;
  if (eventSource) eventSource.close();
  eventSource = null;
  window.clearTimeout(eventTimer); window.clearTimeout(eventWatchdog);
}
function streamEligible() {
  return typeof EventSource !== "undefined" && !!selected && !document.hidden &&
    (authMode === "discord" ? authenticated : !secret);
}
function startEvents(reset = true) {
  stopEvents();
  if (reset) { eventFailures = 0; nextStreamTry = 0; }
  if (!streamEligible()) { fallbackPolling = true; return; }
  const epoch = eventEpoch, guild = selected, view = generation;
  const source = eventSource = new EventSource("/api/guilds/" + guild + "/events?lang=" + encodeURIComponent(dashboardLocale()));
  const current = () => epoch === eventEpoch && source === eventSource && guild === selected && view === generation;
  const failed = async () => {
    if (!current()) return;
    source.close(); eventSource = null; window.clearTimeout(eventWatchdog);
    ++eventFailures; fallbackPolling = true;
    // A regular authenticated read distinguishes expired login/removed membership
    // from a network/proxy failure (EventSource does not expose HTTP status).
    await refresh(view);
    if (epoch !== eventEpoch || guild !== selected || view !== generation) return;
    const delay = eventFailures >= 4 ? 60000 : Math.min(30000, 1000 * 2 ** (eventFailures - 1));
    nextStreamTry = Date.now() + delay;
    connectionStatus(eventFailures >= 4 ? t("m0186") : t("m0187"));
    eventTimer = window.setTimeout(() => {
      if (epoch === eventEpoch && guild === selected && view === generation) startEvents(false);
    }, delay);
  };
  source.addEventListener("snapshot", (event) => {
    if (!current()) return;
    try {
      const bundle = JSON.parse(event.data);
      if (String(bundle.state?.guild_id) !== guild) throw new Error("invalid guild");
      ++stateGeneration; connected = true; fallbackPolling = false; eventFailures = 0;
      window.clearTimeout(eventWatchdog);
      render(bundle.state);
      if (bundle.history) applyHistory(bundle.history, guild, view);
      connectionStatus(t("m0188"));
      nextStreamTry = 0;
    } catch { failed(); }
  });
  source.addEventListener("access", (event) => {
    if (!current()) return;
    source.close(); eventSource = null; fallbackPolling = true;
    let status; try { status = JSON.parse(event.data).status; } catch { status = 401; }
    if (status === 401) signedOut(t("m0055"));
    else {
      stopEvents(); ++generation; selected = ""; state = null; connected = false;
      resetView(); controls(); notice(t("m0189"), true);
      connect();
    }
  });
  source.onerror = failed;
  eventWatchdog = window.setTimeout(failed, 20000);
}
function localTick() {
  if (!document.hidden && state) {
    if (!seekDrag) drawProgress(localProgress());
    updateQueueTimes(); syncLyrics();
  }
  window.setTimeout(localTick, lyricsOpen ? 250 : 1000);
}
$("queue-search").addEventListener("input", () => {
  queueSearch = $("queue-search").value.trim().toLowerCase();
  setQueueFilter(queueMine);
});
$("queue-all").addEventListener("click", () => setQueueFilter(false));
$("queue-mine").addEventListener("click", () => setQueueFilter(true));
document.addEventListener("visibilitychange", async () => {
  stopEvents();
  if (!document.hidden && selected) { await refresh(); startEvents(); }
});

initialize().finally(() => { window.setTimeout(poll, 1000); window.setTimeout(localTick, 1000); });

window.addEventListener?.("blur", () => { cancelDrag(); cancelSeek(); noSelection("volume", false); });


let spotifyRequest = 0;
async function spotifyPrefetch() {
  const request = ++spotifyRequest, epoch = generation, key = currentTrackKey(), guild = selected;
  const link = $("song-spotify"), title = state?.current?.title || "";
  link.hidden = !key; link.removeAttribute("href");
  link.setAttribute("aria-disabled","true");
  link.classList.toggle("is-loading",!!key);
  if (!key || !connected || !guild) return;
  try {
    const value = await api("api/guilds/" + guild + "/spotify");
    if (request !== spotifyRequest || epoch !== generation || key !== currentTrackKey()) return;
    const url = safeURL(value.url);
    if (url && new URL(url).protocol === "https:" && new URL(url).hostname === "open.spotify.com") link.setAttribute("href", url);
  } catch {
    if (request !== spotifyRequest || epoch !== generation || key !== currentTrackKey()) return;
    link.setAttribute("href", "https://open.spotify.com/search/" + encodeURIComponent(title));
  } finally {
    if (request === spotifyRequest && epoch === generation && key === currentTrackKey()) {
      link.classList.toggle("is-loading",false); link.setAttribute("aria-disabled",String(!link.getAttribute("href")));
    }
  }
}
$("song-spotify").addEventListener("click", event => {
  if ($("song-spotify").getAttribute("aria-disabled") === "true") event.preventDefault();
});


// offsetLeft/Top and client sizes share the padding-box coordinate system.
// Clamp to padding so border, safe-area insets and fractional layout cannot spill.
function segmentGeometry(group, active, style) {
  const left = parseFloat(style.paddingLeft) || 0, right = parseFloat(style.paddingRight) || 0;
  const top = parseFloat(style.paddingTop) || 0, bottom = parseFloat(style.paddingBottom) || 0;
  const width = Math.max(0, group.clientWidth-left-right), height = Math.max(0, group.clientHeight-top-bottom);
  const w = Math.min(active.offsetWidth,width), h = Math.min(active.offsetHeight,height);
  return {x:Math.max(left,Math.min(active.offsetLeft,group.clientWidth-right-w)),
    y:Math.max(top,Math.min(active.offsetTop,group.clientHeight-bottom-h)),w,h};
}

/* Progressive visual helpers are optional; no dependency on layout in VM tests. */
function initGlass() {
  if (!document.documentElement) return;
  const root = document.documentElement, nav = document.querySelector(".page-tabs");
  // Clear glass is the only appearance; reduced transparency still falls back via CSS.
  root.dataset.glass = "clear";
  try { window.localStorage.removeItem("musicbot-glass"); } catch {}
  // Chromium URL filters are progressive. Safari/Firefox keep portable blur.
  const transparency = window.matchMedia("(prefers-reduced-transparency: reduce)");
  const contrast = window.matchMedia("(prefers-contrast: more)");
  const refraction = () => {
    const chrome = /Chrome|Chromium/.test(navigator.userAgent) && !/Firefox/.test(navigator.userAgent);
    root.classList.toggle("liquid-refraction",chrome && CSS.supports("backdrop-filter",'url("#glass-edge")') &&
      !transparency.matches && !contrast.matches && (navigator.hardwareConcurrency || 4)>=4);
  };
  transparency.addEventListener?.("change",refraction);contrast.addEventListener?.("change",refraction);refraction();
  window.setTimeout(() => {
    if (!root.classList.contains("liquid-refraction") || document.hidden) return;
    const samples=[];let previous=performance.now();
    const measure = now => {
      samples.push(now-previous);previous=now;
      if(samples.length<45)requestAnimationFrame(measure);
      else {
        samples.splice(0,5);samples.sort((a,b)=>a-b);
        if(samples[Math.floor(samples.length*.95)]>34)root.classList.remove("liquid-refraction");
      }
    };
    requestAnimationFrame(measure);
  },1800);
  const groups = [...document.querySelectorAll(".page-tabs,.queue-filters")];
  const align = () => {
    nav.classList.toggle("mobile-glass", window.innerWidth <= 760);
    for (const group of groups) {
      const active = group.querySelector('button[aria-pressed="true"]:not([hidden])');
      if (!active) continue;
      const geometry = segmentGeometry(group,active,getComputedStyle(group));
      if (!geometry.w || !geometry.h) continue; // Hidden on first authentication paint.
      for (const [name,value] of Object.entries(geometry)) group.style.setProperty("--seg-"+name,value+"px");
      if (!group.hasAttribute("data-seg-ready")) {
        group.setAttribute("data-seg-ready","");
        requestAnimationFrame(() => requestAnimationFrame(() => group.setAttribute("data-seg-animated","")));
      }
    }
  };
  new MutationObserver(align).observe($("dashboard"),{subtree:true,attributes:true,attributeFilter:["aria-pressed","hidden"]});
  const observer = new ResizeObserver(align);
  for (const group of groups) {
    observer.observe(group);
    for (const button of group.querySelectorAll("button")) observer.observe(button);
    group.addEventListener("transitionend",align);
  }
  window.addEventListener("resize",align);
  window.addEventListener("orientationchange",align);
  window.visualViewport?.addEventListener("resize",align);
  document.fonts?.ready.then(align);
  align();
  let lastY = window.scrollY, ticking = false;
  window.addEventListener("scroll", () => {
    if (ticking) return; ticking = true;
    requestAnimationFrame(() => {
      const y = window.scrollY;
      if (Math.abs(y-lastY)>6) nav.classList.toggle("nav-compact",y>lastY && y>80);
      lastY=y;ticking=false;align();
    });
  },{passive:true});
  if (window.matchMedia("(hover:hover) and (pointer:fine) and (prefers-reduced-motion:no-preference)").matches)
    for (const panel of document.querySelectorAll(".sidebar,.playback-bar")) panel.addEventListener("pointermove",event=>{
      const rect=panel.getBoundingClientRect();
      panel.style.setProperty("--pointer-x",event.clientX-rect.left+"px");panel.style.setProperty("--pointer-y",event.clientY-rect.top+"px");
    },{passive:true});
}
initGlass();
