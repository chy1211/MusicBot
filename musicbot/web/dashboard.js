"use strict";
const $ = (id) => document.getElementById(id);
let secret = "", selected = "", state = null, busy = false, connected = false;
let queueRevision = null, generation = 0, loading = false, stateGeneration = 0;
let authMode = null, authenticated = false;
const labels = {playing: "播放中", paused: "已暫停", stopped: "已停止", disconnected: "尚未加入語音"};
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
function buttonBusy(button, active, label = "處理中…") {
  if (active && button.dataset.loading !== "1") button.dataset.label = button.textContent;
  button.dataset.loading = active ? "1" : "0";
  button.classList.toggle("is-loading", active);
  button.setAttribute("aria-busy", String(active));
  button.textContent = active ? label : button.dataset.label || button.textContent;
  if (active) button.disabled = true;
}
function safeURL(value) {
  try {
    if (/[\u0000-\u001f]/.test(String(value))) return "";
    const url = new URL(value);
    return /^https?:$/.test(url.protocol) && !url.username && !url.password ? value : "";
  } catch { return ""; }
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
    if (/^utm_/i.test(key) || /^(fbclid|gclid)$/i.test(key)) url.searchParams.delete(key);
  url.searchParams.sort();
  return url.href;
}
function requesterName(song) { return song?.requester?.name || "自動播放"; }
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
    ? "即時更新 · 以你的 Discord 身分與權限操作 · 操作前請加入機器人所在的語音頻道"
    : "即時更新 · 以 OwnerID 本人權限操作 · 加入佇列前需先進入 Discord 語音頻道";
}
function signedOut(message = "登入後即可查看你的伺服器並點歌。") {
  stopEvents();
  if (typeof libraryClear === "function") libraryClear();
  if (typeof adminClear === "function") adminClear();
  ++generation; ++stateGeneration;
  authenticated = false; connected = false; loading = false; selected = "";
  secret = ""; $("secret").value = ""; $("query").value = "";
  $("guild").replaceChildren(); $("user-name").textContent = "";
  $("user-avatar").removeAttribute("src"); $("user-avatar").hidden = true;
  resetView(); state = null; controls(); authDisplay();
  $("login-status").textContent = message;
  $("connection").textContent = "尚未登入";
  notice("");
}
async function initialize() {
  try {
    const response = await fetch("/auth/session", {cache: "no-store", credentials: "same-origin"});
    if (!response.ok) throw new Error("無法確認登入狀態，請重新整理頁面。");
    const session = await response.json();
    if (!["owner", "discord"].includes(session.auth_mode) || typeof session.authenticated !== "boolean" ||
        (session.auth_mode === "owner" && !session.authenticated))
      throw new Error("登入狀態無效，請重新整理頁面。");
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
    authDisplay(); await connect();
  } catch (error) {
    signedOut(error.message);
    $("login-status").classList.toggle("error", true);
  }
}
async function logout() {
  if (authMode !== "discord" || !authenticated || busy) return;
  busy = true; controls();
  try { await api("/auth/logout", "POST", {}); signedOut("已登出。"); }
  catch (error) { if (authenticated) notice(error.message, true); }
  finally { busy = false; controls(); }
}
async function api(path, method = "GET", data) {
  const headers = {"X-MusicBot-Dashboard": "1"};
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
    if (error.name === "AbortError") throw new Error("操作逾時，請先查看佇列，再重新查詢或重試。");
    throw error;
  } finally { window.clearTimeout(timer); }

  if (!response.ok) {
    if (response.status === 401) {
      if (authMode === "discord") signedOut(body.error || "登入已過期，請重新登入。");
      else $("auth").open = true;
    }
    const error = new Error(body.error || "連線失敗，請稍後再試。");
    error.status = response.status; throw error;
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
  for (const id of ["progress", "hero-progress"]) $(id).disabled = !seekable;
  $("lyrics-toggle").disabled = !hasPlayer || !state.current;
  $("favorite").disabled = !hasPlayer || !safeURL(state?.current?.url);
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
  $("logout").disabled = busy;
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

  if (drag) cancelDrag("佇列已更新，已取消拖曳，請再試一次。");
  queueRevision = signature;
  $("queue").replaceChildren();
  $("queue-count").textContent = String(state.queue.length);
  const visible = state.queue.filter((song) => (!queueMine || song.mine === true) &&
    (!queueSearch || [song.title, requesterName(song)].some((text) => String(text || "").toLowerCase().includes(queueSearch))));
  $("queue-match-count").textContent = queueFiltered() ? "顯示 " + visible.length + "／" + state.queue.length + " 首" : "";
  $("queue-empty").hidden = visible.length !== 0;
  $("queue-empty").textContent = queueSearch ? "沒有符合搜尋的歌曲。" : queueMine ? "目前沒有你點播的歌曲。" : "目前佇列是空的。";
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
    const title = document.createElement("p"); title.textContent = song.title;
    const source = document.createElement("small"); source.textContent = "點播：" + requesterName(song);
    const estimate = document.createElement("small"); estimate.className = "queue-estimate";
    info.append(title, source, estimate);
    const time = document.createElement("span"); time.className = "song-length";
    time.textContent = song.duration ? duration(song.duration) : "未知";
    const actions = document.createElement("div"); actions.className = "actions";
    const rev = state.revision;
    const handle = document.createElement("button");
    handle.textContent = "⋮⋮"; handle.className = "drag-handle";
    handle.setAttribute("aria-label", "拖曳排序：" + song.title + "；鍵盤請用旁邊的上移或下移按鈕");
    handle.setAttribute("aria-describedby", "drag-help");
    handle.title = queueFiltered() ? "篩選中停用拖曳，請用上下移按鈕" : "拖曳排序（手機長按）";
    handle.dataset.boundary = queueFiltered() ? "1" : "0";
    installDrag(handle, li, song.position, rev);
    actions.append(handle);
    for (const [text, label, target] of [["↑", "上移", song.position - 1], ["↓", "下移", song.position + 1], ["×", "刪除", null]]) {
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
  if (!drag) { if (!preserve) settleDrag(); return; }
  if (!preserve) settleDrag();
  const old = drag; drag = null;
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
  notice("拖曳中，放開以儲存順序；按 Esc 可取消。");
  dragTarget(); drag.frame = window.requestAnimationFrame(dragScroll);
}
function installDrag(handle, row, from, rev) {
  handle.addEventListener("pointerdown", (event) => {
    if (handle.disabled || queueFiltered() || event.button !== 0 || event.isPrimary === false || busy || !connected || drag) return;
    drag = {handle, row, from, target: from, rev, pointerId: event.pointerId,
      x: event.clientX, y: event.clientY, startX: event.clientX, startY: event.clientY,
      active: false, touch: event.pointerType !== "mouse", epoch: generation};
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
    cancelDrag("已取消拖曳。");
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
      ? batch ? "已在佇列" : "這首已經在佇列第 " + position + " 首" + (playing ? "，且目前正在播放" : "")
      : playing ? batch ? "正在播放" : "這首目前正在播放" : "";
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
  resolving = true; buttonBusy($("enqueue"), true); controls(); notice("正在查詢，只解析歌曲資訊…");
  try {
    const action = $("request-action").value === "playnext" ? "playnext" : "play";
    const result = await api("api/guilds/" + guild + "/resolve", "POST", {query, action});
    if (epoch !== generation || requestId !== resolveGeneration) return;
    previewResults = result.results;
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
        ? "播放清單 · 共 " + song.count + " 首 · 已檢查 " + song.checked_count + " 首，" + song.eligible_count + " 首可加入"
        : song.duration ? duration(song.duration) : "直播／長度未知";
      const link = document.createElement("a"); link.textContent = song.url || "來源網址無法使用";
      if (safeURL(song.url)) { link.href = song.url; link.target = "_blank"; link.rel = "noopener noreferrer"; }
      info.append(title, length, link);
      if (song.reason || song.warning) {
        const reason = document.createElement("p"); reason.className = song.reason ? "reason" : "hint";
        reason.textContent = song.reason || song.warning; info.append(reason);
      }
      const button = document.createElement("button"); button.className = "primary";
      const selectedItems = new Set();
      const checkboxes = [];
      const updateSelection = () => {
        button.textContent = song.kind === "playlist" ? "加入選取的 " + selectedItems.size + " 首" : song.allowed ? "加入佇列" : "無法加入";
        button.dataset.boundary = song.allowed && (song.kind !== "playlist" || selectedItems.size) ? "0" : "1";
        controls();
      };
      if (song.entries) {
        const hint = document.createElement("p"); hint.className = "hint playlist-next-hint";
        hint.textContent = "播放清單依原順序加入佇列；下一首播放目前只提供單曲。";
        info.append(hint);
        const tools = document.createElement("div"); tools.className = "selection-tools";
        for (const [label, checked] of [["全選", true], ["全不選", false]]) {
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
        const list = document.createElement("ol"); list.className = "playlist-selection";
        for (const item of song.entries) {
          const li = document.createElement("li"), label = document.createElement("label");
          const checkbox = document.createElement("input"); checkbox.type = "checkbox";
          checkbox.checked = !!item.allowed && !!song.allowed;
          checkbox.dataset.boundary = item.allowed && song.allowed ? "0" : "1";
          checkbox.disabled = checkbox.dataset.boundary === "1";
          checkbox.setAttribute("aria-label", "選取：" + item.title);
          if (checkbox.checked) selectedItems.add(item.item_id);
          checkbox.addEventListener("change", () => {
            if (checkbox.disabled) return;
            if (checkbox.checked) selectedItems.add(item.item_id);
            else selectedItems.delete(item.item_id);
            updateSelection();
          });
          checkboxes.push([checkbox, item]);
          const text = document.createElement("span");
          text.textContent = item.title + " · " + (item.duration ? duration(item.duration) : "長度未知") +
            (item.reason ? " · 無法加入：" + item.reason : " · 可加入");
          label.append(checkbox, text); duplicateNote(label, item.url, true);
          li.append(label); list.append(li);
        }
        info.append(tools, list);
      }
      updateSelection();
      const confirmSong = async (target, clicked = button) => {
        if (clicked.disabled || busy) return;
        const payload = {query: song.url, preview_id: song.preview_id};
        if (song.kind === "playlist") payload.selected_items = song.entries
          .filter((item) => selectedItems.has(item.item_id)).map((item) => item.item_id);
        buttonBusy(clicked, true, song.kind === "playlist" ? "處理中（" + selectedItems.size + " 首）…" : "處理中…");
        try {
          if (await act(target, payload)) {
            clearPreview(); $("query").value = ""; controls();
          }
        } finally { buttonBusy(clicked, false); controls(); }
      };
      button.addEventListener("click", () => confirmSong(action));
      if (action === "playnext") button.textContent = song.allowed ? "下一首播放" : "無法插播";
      article.append(art, info, button);
      if (song.kind !== "playlist") {
        const alternate = document.createElement("button");
        alternate.type = "button"; alternate.className = "subtle preview-alternate";
        alternate.dataset.boundary = song.allowed ? "0" : "1";
        alternate.textContent = action === "play" ? "下一首播放" : "加入佇列";
        alternate.addEventListener("click", () => confirmSong(action === "play" ? "playnext" : "play", alternate));
        article.append(alternate);
        duplicateNote(article, song.url);
      }
      $("preview-results").append(article);
    }
    updateDuplicateNotes();
    notice("請確認預覽，再選擇加入方式。預覽五分鐘內有效。");
  } catch (error) {
    if (epoch === generation && requestId === resolveGeneration) notice(error.message, true);
  } finally {
    if (epoch === generation && requestId === resolveGeneration) { resolving = false; buttonBusy($("enqueue"), false); controls(); }
  }
}

function render(next, force = false) {
  const previousTrack = currentTrackKey();
  state = next; stateAt = Date.now();
  if (seekDrag && seekDrag.track !== currentTrackKey()) cancelSeek();
  if (previousTrack !== currentTrackKey()) resetLyrics(false);
  $("title").textContent = state.current ? state.current.title : "選一首喜歡的歌";
  $("subtitle").textContent = state.current ? "點播：" + requesterName(state.current) : "請先加入 Discord 語音頻道，再點播歌曲";
  const source = safeURL(state.current?.url || "");
  $("source-link").hidden = !source;
  if (source) {
    $("source-link").href = source;
    $("source-link").textContent = /^https?:\/\/(www\.)?(youtube\.com|youtu\.be)\//i.test(source)
      ? "在 YouTube 開啟 ↗" : "在來源網站開啟 ↗";
  } else $("source-link").removeAttribute("href");
  $("play-status").textContent = labels[state.status] || "準備中";
  $("toggle").textContent = state.status === "playing" ? "暫停 Ⅱ" : "播放 ▶";
  $("bar-title").textContent = state.current ? state.current.title : "還沒有播放中的歌曲";
  $("bar-status").textContent = labels[state.status] || "準備中";
  const cover = safeURL(state.current?.thumbnail || "");
  if (cover) { $("bar-cover").src = cover; $("bar-cover").hidden = false; }
  else { $("bar-cover").hidden = true; $("bar-cover").removeAttribute("src"); }
  if (cover) {
    if ($("cover").getAttribute("src") !== cover) {
      $("cover").src = cover; $("cover").hidden = false;
    }
  } else { $("cover").hidden = true; $("cover").removeAttribute("src"); }
  const total = state.current ? state.current.duration : 0;
  drawProgress(seekDrag ? seekDrag.position : state.progress, total);
  if (lyricsOpen && state.current && lyricsTrack !== currentTrackKey() && !lyricsLoading) loadLyrics();
  syncLyrics();
  if ((force || document.activeElement !== $("volume")) && state.volume !== null) {
    $("volume").value = state.volume; $("volume-label").value = state.volume + "%";
  }
  if (force || document.activeElement !== $("repeat")) $("repeat").value = state.repeat;
  renderQueue(); renderRecommendations(); updateDuplicateNotes(); controls(); updateQueueTimes(); renderCommunity(state);
}
async function act(action, data = {}, method = "POST") {
  if (busy || !selected || !connected) return;
  const guild = selected, epoch = generation;
  if (drag) cancelDrag();
  ++stateGeneration;
  busy = true; controls(); notice(["play", "playnext"].includes(action) ? "正在搜尋與加入歌曲，請稍候…" : "正在處理…");
  let result;
  try {
    result = await api("api/guilds/" + guild + "/" + action, method, data);
    if (epoch === generation) { render(result.state, true); notice(result.message, result.added === 0 && result.skipped > 0); }
  } catch (error) {
    if (epoch === generation) notice(error.message, true);
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
    connected = true; $("connection").textContent = "已連線"; render(next, force);
    if (fallbackPolling && !historyLoading && Date.now() - historyUpdated >= 15000) refreshHistory();
  } catch (error) {
    if (epoch !== generation || guild !== selected || sequence !== stateGeneration) return;
    connected = false; $("connection").textContent = "連線中斷";
    notice(error.message, true); controls();
  }
}
function resetView() {
  $("shortcuts-dialog").close();
  cancelDrag(); cancelSeek(); clearPreview(); resetHistory(); resetLyrics(true);
  queueSearch = ""; $("queue-search").value = "";
  queueMine = false; setQueueFilter(false);
  queueRevision = null;
  render({status: "disconnected", current: null, progress: 0, volume: null,
    repeat: "off", queue: [], revision: ""});
}
async function connect() {
  if (authMode !== "owner" && !authenticated) return;
  stopEvents(); fallbackPolling = true;
  const epoch = ++generation;
  loading = true; connected = false; selected = ""; state = null;
  resetView(); controls(); $("connection").textContent = "連線中";
  try {
    const data = await api("api/guilds");
    if (epoch !== generation) return;
    $("guild").replaceChildren();
    for (const guild of data.guilds) {
      const option = document.createElement("option");
      option.value = guild.id; option.textContent = guild.name; $("guild").append(option);
    }
    selected = $("guild").value;
    if (!selected) { notice(authMode === "owner" ? "目前沒有 OwnerID 本人所在的可用伺服器。" : "目前沒有你與機器人共同所在的伺服器。"); return; }
    await refresh(epoch);
    if (connected && typeof adminCapability === "function") adminCapability();
    if (connected) { notice("已連線，可以開始點歌。"); startEvents(); }
  } catch (error) {
    if (epoch === generation) {
      notice(error.message, true); $("connection").textContent = "連線失敗";
    }
  } finally {
    if (epoch === generation) loading = false;
    controls();
  }
}
async function poll() {
  if (!document.hidden && fallbackPolling && (authMode === "owner" || authenticated) && !busy && !loading) {
    if (selected) await refresh();
    else await connect();
  }
  window.setTimeout(poll, document.hidden ? 10000 : 1000);
}
$("cover").addEventListener("error", () => { $("cover").hidden = true; });
$("guild").addEventListener("change", async () => {
  stopEvents(); fallbackPolling = true;
  ++generation; selected = $("guild").value; state = null;
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
$("repeat").addEventListener("change", () => act("repeat", {mode: $("repeat").value}));
$("volume").addEventListener("input", () => { $("volume-label").value = $("volume").value + "%"; });
$("volume").addEventListener("change", () => act("volume", {volume: Number($("volume").value)}));
$("shuffle").addEventListener("click", () => { if (!$("shuffle").disabled && !queueFiltered()) return act("queue/shuffle", {revision: state.revision}); });
$("logout").addEventListener("click", logout);
$("user-avatar").addEventListener("error", () => { $("user-avatar").hidden = true; });

// Seek previews are separate from server state: polling can update other controls.
let seekDrag = null;
function currentTrackKey() {
  return state?.current ? JSON.stringify([selected, state.current.url, state.current.title, state.current.duration, state.current.track_token]) : "";
}
function drawProgress(position, total = state?.current?.duration || 0) {
  const value = total ? Math.max(0, Math.min(Number(position) || 0, total)) : 0;
  for (const id of ["progress", "hero-progress"]) {
    $(id).max = total || 1; $(id).value = value;
    $(id).setAttribute("aria-valuetext", duration(value) + "，共 " + (total ? duration(total) : "長度未知"));
  }
  for (const id of ["elapsed", "hero-elapsed"]) $(id).textContent = duration(value);
  for (const id of ["duration", "hero-duration"]) $(id).textContent = total ? duration(total) : "直播／長度未知";
}
function cancelSeek() {
  seekDrag = null;
}
function beginSeek(input, kind, event = {}) {
  if (input.disabled || busy || !connected || !state?.current) return false;
  if (seekDrag && seekDrag.input !== input) cancelSeek();
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
  if (seekDrag?.kind === "pointer" && seekDrag.pointerId === event.pointerId) return commitSeek();
});
document.addEventListener("pointercancel", (event) => {
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
    const title = document.createElement("p"); title.textContent = song.title;
    const meta = document.createElement("small");
    meta.textContent = (song.duration ? duration(song.duration) : "長度未知") + " · 點播：" + requesterName(song);
    info.append(title, meta);
    const add = document.createElement("button"); add.type = "button"; add.textContent = "加入";
    add.setAttribute("aria-label", "加入：" + song.title);
    add.addEventListener("click", () => { if (!add.disabled) return previewHistorySong(song, guild, epoch); });
    row.append(imageElement(song.thumbnail), info, add); $("recommendation-list").append(row);
  }
}
function resetHistory() {
  ++historyRequest; historyLoading = false; historyUpdated = 0; recentHistory = [];
  recommendationRevision = null; renderRecommendations();
  $("history-list").replaceChildren(); $("history-status").textContent = "尚無播放紀錄。";
}
function playedTime(timestamp) {
  if (timestamp === null || timestamp === undefined || !Number.isFinite(Number(timestamp)) || Number(timestamp) <= 0)
    return "播放時間未知";
  const date = new Date(Number(timestamp) * 1000), difference = Math.max(0, Date.now() - date.getTime());
  if (!Number.isFinite(date.getTime())) return "播放時間未知";
  if (difference < 60000) return "剛剛";
  if (difference < 3600000) return Math.floor(difference / 60000) + " 分鐘前";
  return date.toLocaleString("zh-TW", {timeZone: "Asia/Taipei", month: "numeric", day: "numeric",
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
      $("history-status").textContent = error.message || "暫時無法取得播放紀錄。";
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
    $("history-status").textContent = entries.length ? "播放時間以台灣時間顯示。" : "還沒有播放紀錄，先點一首喜歡的歌。";
    for (const song of entries) {
      const row = document.createElement("li"), info = document.createElement("div");
      info.className = "history-info";
      const title = document.createElement("p"); title.textContent = song.title;
      const meta = document.createElement("small");
      meta.textContent = (song.duration ? duration(song.duration) : "長度未知") + " · 點播：" + requesterName(song) + " · " + playedTime(song.played_at);
      info.append(title, meta);
      if (safeURL(song.requester?.avatar)) {
        const avatar = imageElement(song.requester.avatar, "requester-avatar"); avatar.alt = ""; info.append(avatar);
      }
      const actions = document.createElement("div"); actions.className = "history-actions";
      if (safeURL(song.url)) {
        const replay = document.createElement("button"); replay.type = "button"; replay.textContent = "再點一次";
        replay.addEventListener("click", async () => {
          if (replay.disabled || busy || epoch !== generation || guild !== selected) return;
          await previewHistorySong(song, guild, epoch);
        });
        const link = document.createElement("a"); link.textContent = "來源 ↗";
        link.href = song.url; link.target = "_blank"; link.rel = "noopener noreferrer";
        actions.append(replay, link);
        if (typeof librarySaveButton === "function") actions.append(librarySaveButton(song));
      }
      row.append(imageElement(song.thumbnail), info, actions); $("history-list").append(row);
    }
    historyUpdated = Date.now();
  controls();
}

let lyricsOpen = false, lyricsLoading = false, lyricsRequest = 0, lyricsTrack = "", lyricsLines = [], lyricsActive = -1;
function resetLyrics(close = false) {
  ++lyricsRequest; lyricsLoading = false; lyricsTrack = ""; lyricsLines = []; lyricsActive = -1;
  $("lyrics-content").replaceChildren(); $("lyrics-content").textContent = "";
  $("lyrics-content").classList.toggle("plain-lyrics", false);
  $("lyrics-status").textContent = ""; $("lyrics-search-form").hidden = true;
  $("lyrics-query").value = ""; $("lyrics-heading").textContent = "歌詞";
  if (close) {
    lyricsOpen = false; $("lyrics-panel").hidden = true;
    $("lyrics-toggle").setAttribute("aria-expanded", "false");
  }
}
async function loadLyrics(query = "") {
  if (!selected || !connected || !state?.current) return;
  const guild = selected, epoch = generation, key = currentTrackKey(), request = ++lyricsRequest;
  lyricsLoading = true; lyricsTrack = key; lyricsLines = []; lyricsActive = -1;
  $("lyrics-content").replaceChildren(); $("lyrics-content").textContent = "";
  $("lyrics-content").classList.toggle("plain-lyrics", false);
  $("lyrics-status").textContent = "正在找歌詞…"; $("lyrics-search-form").hidden = true; controls();
  try {
    const result = await api("api/guilds/" + guild + "/lyrics" + (query ? "?query=" + encodeURIComponent(query) : ""));
    if (epoch !== generation || guild !== selected || key !== currentTrackKey() || request !== lyricsRequest) return;
    $("lyrics-heading").textContent = result.artist ? result.title + " · " + result.artist : result.title || "歌詞";
    if (result.status === "synced" && Array.isArray(result.lines) && result.lines.length) {
      lyricsLines = result.lines.map((line) => ({time: Number(line.time), text: String(line.text || "")}))
        .filter((line) => Number.isFinite(line.time)).sort((a, b) => a.time - b.time);
      for (const line of lyricsLines) {
        const row = document.createElement("p"); row.textContent = line.text || "♪"; $("lyrics-content").append(row);
      }
      $("lyrics-status").textContent = "歌詞隨播放進度更新。"; syncLyrics();
    } else if (result.status === "plain" && result.plain_lyrics) {
      $("lyrics-content").textContent = result.plain_lyrics;
      $("lyrics-status").textContent = "純文字歌詞"; $("lyrics-content").classList.toggle("plain-lyrics", true);
    } else {
      $("lyrics-status").textContent = result.status === "unavailable" ? "歌詞服務暫時無法使用，請稍後再試。" : "找不到歌詞";
      $("lyrics-search-form").hidden = false;
    }
  } catch (error) {
    if (epoch === generation && request === lyricsRequest) {
      $("lyrics-status").textContent = error.message || "暫時無法取得歌詞。";
      $("lyrics-search-form").hidden = false; notice(error.message, true);
    }
  } finally { if (epoch === generation && request === lyricsRequest) { lyricsLoading = false; controls(); } }
}
function syncLyrics() {
  if (!lyricsOpen || !lyricsLines.length) return;
  const progress = localProgress();
  let index = -1;
  for (let i = 0; i < lyricsLines.length && lyricsLines[i].time <= progress; i++) index = i;
  if (index === lyricsActive) return;
  lyricsActive = index;
  Array.from($("lyrics-content").children).forEach((row, i) => {
    row.classList.toggle("current-line", i === index);
    if (i === index) {
      row.setAttribute("aria-current", "true");
      row.scrollIntoView?.({behavior: reduceMotion() ? "auto" : "smooth", block: "nearest"});
    } else row.removeAttribute("aria-current");
  });
}
function toggleLyrics(open = !lyricsOpen) {
  lyricsOpen = open; $("lyrics-panel").hidden = !open;
  $("lyrics-toggle").setAttribute("aria-expanded", String(open));
  if (open && lyricsTrack !== currentTrackKey()) return loadLyrics();
}
installSeek("progress"); installSeek("hero-progress");
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
  const total = (unknown ? "已知 " : "共 ") + Math.floor(minutes / 60) + " 小時 " + minutes % 60 + " 分" +
    (unknown ? "・含長度未知歌曲" : "");
  let wait = value?.current && valid(value.current.duration) ? Math.max(0, Number(value.current.duration) - progress) : null;
  const times = new Map();
  for (const song of songs) {
    let text;
    if (value.repeat === "song") text = "單曲重複中，時間未定";
    else if (value.status === "paused") text = "暫停中，時間順延";
    else if (value.status !== "playing" || wait === null) text = "時間未定";
    else text = wait < 60 ? "約 1 分鐘內" : "約 " + Math.ceil(wait / 60) + " 分鐘後";
    times.set(song.position, text);
    if (wait !== null) wait = valid(song.duration) ? wait + Number(song.duration) : null;
  }
  return {total, times};
}
function updateQueueTimes() {
  const schedule = queueSchedule(state, localProgress());
  $("queue-total").textContent = schedule.total;
  $("queue-timing-note").textContent = state?.repeat === "all" ? "整個佇列重複：顯示本輪預計時間。" : "";
  for (const row of $("queue").children) {
    const time = row.children[2]?.children[2];
    if (time) time.textContent = schedule.times.get(Number(row.dataset.position)) || "時間未定";
  }
}
function setQueueFilter(mine) {
  queueMine = mine;
  cancelDrag(); queueRevision = null;
  $("queue-all").setAttribute("aria-pressed", String(!mine));
  $("queue-mine").setAttribute("aria-pressed", String(mine));
  const reason = [mine ? "我的點歌" : "", queueSearch ? "搜尋篩選中" : ""].filter(Boolean).join("＋");
  $("drag-help").textContent = reason
    ? reason + "：停用拖曳與洗牌；↑ ↓ 與刪除仍使用完整佇列的位置。"
    : "拖曳 ⋮⋮ 調整順序；手機請長按把手。也可用 ↑ ↓ 按鈕，按 Esc 取消拖曳。";
  $("shuffle").title = reason ? reason + "：停用洗牌，請先清除篩選。" : "將完整佇列洗牌";
  if (state) { renderQueue(); controls(); updateQueueTimes(); }
}
function renderCommunity(value) {
  const listeners = value?.listeners || {connected: false, members: []};
  const members = listeners.members || [];
  $("listeners-status").textContent = listeners.connected
    ? (listeners.channel || "語音頻道") + "・" + members.length + " 人"
    : "機器人目前不在語音頻道";
  const list = $("listeners-list"); list.replaceChildren();
  const add = (member, parent) => {
    const row = document.createElement("span"); row.className = "listener";
    const name = document.createElement("span"); name.textContent = member.name;
    row.append(imageElement(member.avatar, "listener-avatar"), name); parent.append(row);
  };
  members.slice(0, 8).forEach((member) => add(member, list));
  if (members.length > 8) {
    const details = document.createElement("details"), summary = document.createElement("summary");
    summary.textContent = "另外 " + (members.length - 8) + " 人"; details.append(summary);
    const more = document.createElement("div"); more.className = "listeners-list";
    members.slice(8).forEach((member) => add(member, more)); details.append(more); list.append(details);
  }
  const records = (value?.activity?.activity || []).slice(0, 100);
  $("activity-list").replaceChildren();
  $("activity-status").textContent = records.length ? "最近 100 筆操作，重新啟動後清空。" : "尚無操作紀錄。";
  for (const item of records) {
    const row = document.createElement("li"), line = document.createElement("p"), meta = document.createElement("small");
    line.textContent = item.actor + "・" + item.detail;
    const stamp = new Date(Number(item.time) * 1000);
    const time = Number.isFinite(stamp.getTime()) ? stamp.toLocaleTimeString("zh-TW",
      {timeZone: "Asia/Taipei", hour12: false}) : "時間未知";
    meta.textContent = time + "・" + ({web: "網頁", discord_text: "Discord 文字", discord_slash: "Discord 斜線"}[item.source] || "Discord") + "・" + item.result;
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
  const source = eventSource = new EventSource("/api/guilds/" + guild + "/events");
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
    $("connection").textContent = eventFailures >= 4 ? "一般更新・即時連線重試中" : "即時連線重試中";
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
      $("connection").textContent = "即時連線";
      nextStreamTry = 0;
    } catch { failed(); }
  });
  source.addEventListener("access", (event) => {
    if (!current()) return;
    source.close(); eventSource = null; fallbackPolling = true;
    let status; try { status = JSON.parse(event.data).status; } catch { status = 401; }
    if (status === 401) signedOut("登入已過期，請重新登入。");
    else {
      stopEvents(); ++generation; selected = ""; state = null; connected = false;
      resetView(); controls(); notice("你已無法查看這個伺服器，正在更新伺服器清單。", true);
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
  window.setTimeout(localTick, 1000);
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
