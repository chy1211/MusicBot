"use strict";
const $ = (id) => document.getElementById(id);
let secret = "", selected = "", state = null, busy = false, connected = false;
let queueRevision = null, generation = 0, loading = false;
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
    throw new Error(body.error || "連線失敗，請稍後再試。");
  }
  return body;
}
function controls() {
  const usable = connected && !busy && !!selected;
  const hasPlayer = usable && state && state.status !== "disconnected";
  for (const id of ["toggle", "skip", "repeat", "volume"]) $(id).disabled = !hasPlayer;
  $("enqueue").disabled = !usable;
  $("shuffle").disabled = !hasPlayer || !state.queue.length;
  $("guild").disabled = busy;
  document.querySelectorAll("#queue button").forEach((button) => {
    button.disabled = !hasPlayer || button.dataset.boundary === "1";
  });
}
function renderQueue() {
  if (queueRevision === state.revision) return;
  queueRevision = state.revision;
  $("queue").replaceChildren();
  $("queue-count").textContent = String(state.queue.length);
  $("queue-empty").hidden = state.queue.length !== 0;
  for (const song of state.queue) {
    const li = document.createElement("li");
    const number = document.createElement("span");
    number.className = "number"; number.textContent = String(song.position).padStart(2, "0");
    const info = document.createElement("div"); info.className = "song";
    const title = document.createElement("p"); title.textContent = song.title;
    const time = document.createElement("small"); time.textContent = song.duration ? duration(song.duration) : "直播／長度未知";
    info.append(title, time);
    const actions = document.createElement("div"); actions.className = "actions";
    for (const [text, label, target] of [["↑", "上移", song.position - 1], ["↓", "下移", song.position + 1], ["×", "刪除", null]]) {
      const button = document.createElement("button"); button.textContent = text;
      button.setAttribute("aria-label", label + "：" + song.title);
      button.title = label;
      button.dataset.boundary = target !== null && (target < 1 || target > state.queue.length) ? "1" : "0";
      // Capture the exact revision the user saw, including duplicate URLs.
      const rev = state.revision;
      button.addEventListener("click", () => target === null
        ? act("queue/" + song.position, {revision: rev}, "DELETE")
        : act("queue/move", {from: song.position, to: target, revision: rev}));
      actions.append(button);
    }
    li.append(number, info, actions); $("queue").append(li);
  }
}
function render(next, force = false) {
  state = next;
  $("title").textContent = state.current ? state.current.title : "選一首喜歡的歌";
  $("subtitle").textContent = state.current ? "讓音樂繼續陪你" : "請先加入 Discord 語音頻道，再點播歌曲";
  $("play-status").textContent = labels[state.status] || "準備中";
  $("toggle").textContent = state.status === "playing" ? "暫停 Ⅱ" : "播放 ▶";
  const cover = state.current && state.current.thumbnail;
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
  const guild = selected;
  if (!guild) return;
  try {
    const next = await api("api/guilds/" + guild + "/state");
    if (epoch !== generation || guild !== selected) return;
    connected = true; $("connection").textContent = "已連線"; render(next, force);
  } catch (error) {
    if (epoch !== generation || guild !== selected) return;
    connected = false; $("connection").textContent = "連線中斷";
    notice(error.message, true); controls();
  }
}
function resetView() {
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
$("play-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = $("query").value.trim();
  if (query && await act("play", {query})) $("query").value = "";
});
$("toggle").addEventListener("click", () => act(state.status === "playing" ? "pause" : "resume"));
$("skip").addEventListener("click", () => act("skip"));
$("repeat").addEventListener("change", () => act("repeat", {mode: $("repeat").value}));
$("volume").addEventListener("input", () => { $("volume-label").value = $("volume").value + "%"; });
$("volume").addEventListener("change", () => act("volume", {volume: Number($("volume").value)}));
$("shuffle").addEventListener("click", () => act("queue/shuffle", {revision: state.revision}));
connect().finally(() => window.setTimeout(poll, 1000));
