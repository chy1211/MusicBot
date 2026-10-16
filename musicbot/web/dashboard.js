"use strict";
const $ = (id) => document.getElementById(id);
let secret = "", selected = "", state = null, busy = false, connected = false;
let queueRevision = null, generation = 0, loading = false, stateGeneration = 0;
const labels = {playing: "播放中", paused: "已暫停", stopped: "已停止", disconnected: "尚未加入語音"};
function notice(message, error = false) {
  $("notice").textContent = message;
  $("notice").classList.toggle("error", error);
}
function duration(seconds) {
  seconds = Math.floor(Math.max(0, seconds || 0));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor(seconds / 60) % 60;
  return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(seconds % 60).padStart(2, "0");
}
async function api(path, method = "GET", data) {
  const headers = {"X-MusicBot-Dashboard": "1"};
  if (secret) headers.Authorization = "Bearer " + secret;
  if (data !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {method, headers, cache: "no-store",
    body: data === undefined ? undefined : JSON.stringify(data)});
  const body = await response.json();
  if (!response.ok) {
    if (response.status === 401) $("auth").open = true;
    const error = new Error(body.error || "連線失敗，請稍後再試。");
    error.status = response.status; throw error;
  }
  return body;
}
function controls() {
  const usable = connected && !busy && !!selected;
  const hasPlayer = usable && state && state.status !== "disconnected";
  for (const id of ["toggle", "skip", "repeat", "volume"]) $(id).disabled = !hasPlayer;
  $("enqueue").disabled = !usable || resolving;
  document.querySelectorAll("#preview-results button").forEach((button) => {
    button.disabled = !usable || button.dataset.boundary === "1";
  });
  $("shuffle").disabled = !hasPlayer || !state.queue.length;
  $("guild").disabled = busy;
  document.querySelectorAll("#queue button").forEach((button) => {
    button.disabled = !hasPlayer || button.dataset.boundary === "1";
  });
}
function imageElement(url, className = "queue-cover") {
  const img = document.createElement("img");
  img.className = className; img.alt = ""; img.loading = "lazy";
  if (url) img.src = url;
  else img.hidden = className !== "queue-cover";
  img.addEventListener("error", () => {
    img.removeAttribute("src"); img.hidden = className !== "queue-cover";
  });
  return img;
}
function renderQueue() {
  if (queueRevision === state.revision) return;
  if (drag) cancelDrag("佇列已更新，已取消拖曳，請再試一次。");
  queueRevision = state.revision;
  $("queue").replaceChildren();
  $("queue-count").textContent = String(state.queue.length);
  $("queue-empty").hidden = state.queue.length !== 0;
  for (const song of state.queue) {
    const li = document.createElement("li");
    li.dataset.position = String(song.position);
    const number = document.createElement("span");
    number.className = "number"; number.textContent = String(song.position).padStart(2, "0");
    const img = imageElement(song.thumbnail);
    const info = document.createElement("div"); info.className = "song";
    const title = document.createElement("p"); title.textContent = song.title;
    const source = document.createElement("small"); source.textContent = "等待播放";
    info.append(title, source);
    const time = document.createElement("span"); time.className = "song-length";
    time.textContent = song.duration ? duration(song.duration) : "未知";
    const actions = document.createElement("div"); actions.className = "actions";
    const rev = state.revision;
    const handle = document.createElement("button");
    handle.textContent = "⋮⋮"; handle.className = "drag-handle";
    handle.setAttribute("aria-label", "拖曳排序：" + song.title + "；鍵盤請用旁邊的上移或下移按鈕");
    handle.setAttribute("aria-describedby", "drag-help");
    handle.title = "拖曳排序（手機長按）";
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
    li.append(number, img, info, time, actions); $("queue").append(li);
  }
}
let drag = null;
function cancelDrag(message) {
  if (!drag) return;
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
  const row = document.elementFromPoint(drag.x, drag.y)?.closest("#queue > li");
  if (!row) return;
  if (drag.targetRow) {
    drag.targetRow.classList.toggle("drop-target", false);
    drag.targetRow.classList.toggle("drop-after", false);
  }
  drag.target = Number(row.dataset.position); drag.targetRow = row;
  row.classList.toggle("drop-target", drag.target !== drag.from);
  row.classList.toggle("drop-after", drag.target > drag.from);
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
    if (event.button !== 0 || event.isPrimary === false || busy || !connected || drag) return;
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
    cancelDrag();
    if (completed.active && completed.epoch === generation && completed.from !== completed.target)
      return act("queue/move", {from: completed.from, to: completed.target, revision: completed.rev});
  });
  for (const type of ["pointercancel", "lostpointercapture"]) handle.addEventListener(type, () => {
    if (drag && drag.handle === handle) cancelDrag();
  });
}
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") cancelDrag("已取消拖曳。");
});
let resolving = false, resolveGeneration = 0, previewResults = [];
function clearPreview() {
  ++resolveGeneration; resolving = false; previewResults = [];
  $("preview-panel").hidden = true; $("preview-results").replaceChildren();
}
async function resolveQuery() {
  const query = $("query").value.trim();
  if (!query || resolving || busy || !connected || !selected) return;
  clearPreview();
  const epoch = generation, requestId = ++resolveGeneration, guild = selected;
  resolving = true; controls(); notice("正在查詢，只解析歌曲資訊…");
  try {
    const result = await api("api/guilds/" + guild + "/resolve", "POST", {query});
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
      if (/^https?:\/\//i.test(song.url)) { link.href = song.url; link.target = "_blank"; link.rel = "noopener noreferrer"; }
      info.append(title, length, link);
      if (song.reason || song.warning) {
        const reason = document.createElement("p"); reason.className = song.reason ? "reason" : "hint";
        reason.textContent = song.reason || song.warning; info.append(reason);
      }
      if (song.entries) {
        const list = document.createElement("ol");
        for (const item of song.entries) {
          const li = document.createElement("li");
          li.textContent = item.title + " · " + (item.duration ? duration(item.duration) : "長度未知") +
            (item.reason ? " · 略過：" + item.reason : "");
          list.append(li);
        }
        info.append(list);
      }
      const button = document.createElement("button"); button.className = "primary";
      button.textContent = song.allowed ? "加入佇列" : "無法加入";
      button.dataset.boundary = song.allowed ? "0" : "1";
      button.addEventListener("click", async () => {
        if (button.disabled) return;
        // Keep the same token after network errors; the server deduplicates it.
        if (await act("play", {query: song.url, preview_id: song.preview_id})) {
          clearPreview(); $("query").value = ""; controls();
        }
      });
      article.append(art, info, button); $("preview-results").append(article);
    }
    notice("請確認預覽，再按「加入佇列」。預覽五分鐘內有效。");
  } catch (error) {
    if (epoch === generation && requestId === resolveGeneration) notice(error.message, true);
  } finally {
    if (epoch === generation && requestId === resolveGeneration) { resolving = false; controls(); }
  }
}

function render(next, force = false) {
  state = next;
  $("title").textContent = state.current ? state.current.title : "選一首喜歡的歌";
  $("subtitle").textContent = state.current ? "讓音樂繼續陪你" : "請先加入 Discord 語音頻道，再點播歌曲";
  $("play-status").textContent = labels[state.status] || "準備中";
  $("toggle").textContent = state.status === "playing" ? "暫停 Ⅱ" : "播放 ▶";
  $("bar-title").textContent = state.current ? state.current.title : "還沒有播放中的歌曲";
  $("bar-status").textContent = labels[state.status] || "準備中";
  const cover = state.current && state.current.thumbnail;
  if (cover) { $("bar-cover").src = cover; $("bar-cover").hidden = false; }
  else { $("bar-cover").hidden = true; $("bar-cover").removeAttribute("src"); }
  if (cover) {
    if ($("cover").getAttribute("src") !== cover) {
      $("cover").src = cover; $("cover").hidden = false;
    }
  } else { $("cover").hidden = true; $("cover").removeAttribute("src"); }
  const total = state.current ? state.current.duration : 0;
  $("progress").max = total || 1;
  $("progress").value = total ? Math.min(state.progress, total) : 0;
  $("elapsed").textContent = duration(state.progress);
  $("duration").textContent = total ? duration(total) : "直播／長度未知";
  if ((force || document.activeElement !== $("volume")) && state.volume !== null) {
    $("volume").value = state.volume; $("volume-label").value = state.volume + "%";
  }
  if (force || document.activeElement !== $("repeat")) $("repeat").value = state.repeat;
  renderQueue(); controls();
}
async function act(action, data = {}, method = "POST") {
  if (busy || !selected || !connected) return;
  const guild = selected, epoch = generation;
  if (drag) cancelDrag();
  ++stateGeneration;
  busy = true; controls(); notice(action === "play" ? "正在搜尋與加入歌曲，請稍候…" : "正在處理…");
  let result;
  try {
    result = await api("api/guilds/" + guild + "/" + action, method, data);
    if (epoch === generation) { render(result.state, true); notice(result.message); }
  } catch (error) {
    if (epoch === generation) notice(error.message, true);
  } finally {
    busy = false; controls();
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
  } catch (error) {
    if (epoch !== generation || guild !== selected || sequence !== stateGeneration) return;
    connected = false; $("connection").textContent = "連線中斷";
    notice(error.message, true); controls();
  }
}
function resetView() {
  cancelDrag(); clearPreview();
  queueRevision = null;
  render({status: "disconnected", current: null, progress: 0, volume: null,
    repeat: "off", queue: [], revision: ""});
}
async function connect() {
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
    if (!selected) { notice("目前沒有 OwnerID 本人所在的可用伺服器。"); return; }
    await refresh(epoch);
    if (connected) notice("已連線，可以開始點歌。");
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
  if (!busy && !loading) {
    if (selected) await refresh();
    else await connect();
  }
  window.setTimeout(poll, document.hidden ? 10000 : 1000);
}
$("cover").addEventListener("error", () => { $("cover").hidden = true; });
$("guild").addEventListener("change", async () => {
  ++generation; selected = $("guild").value; state = null;
  connected = false; resetView(); controls(); await refresh();
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
$("shuffle").addEventListener("click", () => act("queue/shuffle", {revision: state.revision}));
connect().finally(() => window.setTimeout(poll, 1000));
