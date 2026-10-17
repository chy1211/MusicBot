"use strict";
// Shares authenticated api/state helpers with dashboard.js; all text uses textContent.
let libraryData = null, libraryActive = "favorites", libraryPendingSong = null, libraryBusy = false;
let libraryPage = "play";
function libraryButton(text, run) {
  const b = document.createElement("button"); b.type = "button"; b.textContent = text;
  b.addEventListener("click", () => libraryRun(b, run)); return b;
}
async function libraryRun(button, run) {
  if (libraryBusy) return;
  libraryBusy = true; buttonBusy(button, true);
  try { await run(); } catch (error) { notice(error.message || "操作失敗，請稍後再試。", true); }
  finally { libraryBusy = false; buttonBusy(button, false); button.disabled = false; }
}
function libraryClear() {
  libraryData = null; libraryPendingSong = null; libraryActive = "favorites";
  libraryImportPending = null;
  if (libraryImportUI) {
    const ui = libraryImportUI;
    ui.preview.hidden = ui.form.hidden = ui.sync.hidden = ui.origin.hidden = true;
    ui.url.value = ui.name.value = ui.title.textContent = ui.summary.textContent = ui.origin.textContent = "";
    ui.tracks.replaceChildren(); ui.spotify.disabled = true;
    ui.spotify.textContent = "Spotify"; ui.status.hidden = true;
  }
  $("library-list").replaceChildren(); $("playlist-picker").replaceChildren();
  libraryView("play");
  $("library-panel").hidden = true; $("library-save-dialog").close?.();
}
function libraryView(page) {
  libraryPage = page;
  $("play-view").hidden = page !== "play"; $("library-panel").hidden = page !== "library";
  if ($("admin-panel")) $("admin-panel").hidden = page !== "admin";
  if ($("popular-panel")) $("popular-panel").hidden = page !== "popular";
  for (const key of ["play", "library", "admin", "popular"]) if ($("nav-" + key)) $("nav-" + key).setAttribute("aria-pressed", String(key === page));
}
async function libraryLoad() {
  const epoch = generation;
  const value = await api("/api/library");
  if (epoch !== generation || !(authMode === "owner" || authenticated)) return false;
  libraryData = value; libraryRender(); return true;
}
function libraryRender() {
  const select = $("library-select"); select.replaceChildren();
  if (!libraryData) return;
  for (const item of libraryData.playlists) {
    const option = document.createElement("option"); option.value = item.id;
    option.textContent = item.name + "（" + item.tracks.length + " 首）"; select.append(option);
  }
  if (!libraryData.playlists.some(p => p.id === libraryActive)) libraryActive = "favorites";
  select.value = libraryActive;
  const list = libraryData.playlists.find(p => p.id === libraryActive);
  libraryImportRender(list);
  $("library-name").value = list.name; $("library-name").disabled = list.id === "favorites";
  $("library-rename").disabled = $("library-delete").disabled = list.id === "favorites";
  $("library-list").replaceChildren();
  const selectedTracks = new Set();
  function play(all) { return libraryPlay(list, all ? undefined : [...selectedTracks]); }
  $("library-play-all").onclick = () => libraryRun($("library-play-all"), () => play(true));
  $("library-play-selected").disabled = true;
  $("library-play-selected").onclick = () => libraryRun($("library-play-selected"), () => play(false));
  list.tracks.forEach((song, index) => {
    const row = document.createElement("li"); row.className = "library-track";
    const check = document.createElement("input"); check.type = "checkbox";
    check.setAttribute("aria-label", "選取：" + song.title);
    check.addEventListener("change", () => {
      if (check.checked) selectedTracks.add(String(index)); else selectedTracks.delete(String(index));
      $("library-play-selected").disabled = selectedTracks.size === 0;
    });
    const label = document.createElement("span");
    label.textContent = song.title + " · " + (song.duration ? duration(song.duration) : "長度未知");
    const actions = document.createElement("div"); actions.className = "actions";
    for (const [text, to] of [["↑", index - 1], ["↓", index + 1], ["刪除", null]]) {
      const b = libraryButton(text, () => libraryChange(list.id, {action: to === null ? "remove" : "move", index, to}));
      b.disabled = to !== null && (to < 0 || to >= list.tracks.length);
      b.setAttribute("aria-label", text + "：" + song.title); actions.append(b);
    }
    row.append(check, label, actions); $("library-list").append(row);
  });
  $("library-empty").hidden = list.tracks.length !== 0;
}
async function libraryChange(id, data, method = "PATCH", suffix = "") {
  const epoch = generation, revision = libraryData.revision;
  const result = await api("/api/library/" + encodeURIComponent(id) + suffix, method, {...data, revision});
  if (epoch !== generation) return;
  libraryData = result; libraryRender(); notice("已更新歌單。");
}
async function libraryPlay(list, chosen) {
  if (!selected || !connected) throw new Error("請先選擇可用的伺服器。");
  const guild = selected, epoch = generation;
  const data = {revision: libraryData.revision};
  if (chosen !== undefined) data.selected_items = chosen;
  const result = await api("/api/guilds/" + guild + "/library/" + encodeURIComponent(list.id) + "/play", "POST", data);
  if (epoch !== generation || guild !== selected) return;
  render(result.state, true); notice(result.message, result.skipped > 0);
}
async function librarySave(song, favorite = false) {
  if (!safeURL(song?.url)) throw new Error("這首歌曲沒有可收藏的來源網址。");
  if (!await libraryLoad()) return;
  const track = {title: song.title, url: song.url, duration: song.duration || null};
  if (favorite) return libraryChange("favorites", {track}, "POST", "/tracks");
  libraryPendingSong = track;
  $("playlist-picker").replaceChildren();
  for (const list of libraryData.playlists) {
    const option = document.createElement("option"); option.value = list.id; option.textContent = list.name;
    $("playlist-picker").append(option);
  }
  $("library-save-dialog").showModal();
}
function librarySaveButton(song) {
  const button = libraryButton("加到歌單…", () => librarySave(song));
  button.className = "save-to-library"; return button;
}
$("nav-play").addEventListener("click", () => libraryView("play"));
$("nav-library").addEventListener("click", () => libraryRun($("nav-library"), async () => {
  libraryView("library"); await libraryLoad();
}));
$("library-select").addEventListener("change", () => { libraryActive = $("library-select").value; libraryRender(); });
$("library-refresh").addEventListener("click", () => libraryRun($("library-refresh"), libraryLoad));
$("library-create").addEventListener("submit", event => {
  event.preventDefault();
  return libraryRun($("library-create-button"), async () => {
    const epoch = generation;
    const result = await api("/api/library", "POST", {name: $("library-new-name").value});
    if (epoch !== generation) return;
    libraryData = result; libraryActive = result.playlists.at(-1).id;
    $("library-new-name").value = ""; libraryRender();
  });
});
$("library-rename").addEventListener("click", () => libraryRun($("library-rename"), () => libraryChange(libraryActive, {name: $("library-name").value})));
$("library-delete").addEventListener("click", () => {
  if (!window.confirm("確定刪除這份歌單？")) return;
  return libraryRun($("library-delete"), () => libraryChange(libraryActive, {}, "DELETE"));
});
$("favorite").addEventListener("click", () => libraryRun($("favorite"), () => librarySave(state?.current, true)));
$("library-save-cancel").addEventListener("click", () => $("library-save-dialog").close());
$("library-save-confirm").addEventListener("click", () => libraryRun($("library-save-confirm"), async () => {
  if (!libraryPendingSong) return;
  await libraryChange($("playlist-picker").value, {track: libraryPendingSong}, "POST", "/tracks");
  $("library-save-dialog").close(); libraryPendingSong = null;
}));

let libraryImportUI = null, libraryImportPending = null;
function libraryImportElement(tag, text, id) {
  const element = document.createElement(tag);
  if (text) element.textContent = text;
  if (id) element.id = id;
  return element;
}
function libraryInitImports() {
  const wrap = libraryImportElement("section", "", "library-import-panel");
  wrap.className = "library-import";
  const toggle = libraryButton("從連結匯入", async () => {
    form.hidden = !form.hidden;
    toggle.setAttribute("aria-expanded", String(!form.hidden));
  });
  toggle.setAttribute("aria-expanded", "false");
  toggle.setAttribute("aria-controls", "library-import-form");
  const form = libraryImportElement("form", "", "library-import-form"); form.hidden = true;
  form.className = "input-row";
  const sourceLabel = libraryImportElement("label", "來源", "library-import-source-label");
  sourceLabel.setAttribute("for", "library-import-source");
  const source = libraryImportElement("select", "", "library-import-source");
  const youtube = libraryImportElement("option", "YouTube／YouTube Music"); youtube.value = "youtube";
  const spotify = libraryImportElement("option", "Spotify（目前無法讀取）"); spotify.value = "spotify"; spotify.disabled = true;
  source.append(youtube, spotify); source.value = "youtube";
  const label = libraryImportElement("label", "公開歌單連結"); label.setAttribute("for", "library-import-url");
  const url = libraryImportElement("input", "", "library-import-url");
  url.type = "url"; url.required = true; url.maxLength = 2000;
  url.placeholder = "https://www.youtube.com/playlist?list=…";
  const previewButton = libraryImportElement("button", "預覽"); previewButton.type = "submit";
  const status = libraryImportElement("p", "目前無法讀取 Spotify 歌單", "library-import-status");
  status.setAttribute("role", "status");
  const preview = libraryImportElement("section", "", "library-import-preview"); preview.hidden = true;
  const title = libraryImportElement("h3"), summary = libraryImportElement("p"), tracks = libraryImportElement("ol");
  const nameLabel = libraryImportElement("label", "新歌單名稱"); nameLabel.setAttribute("for", "library-import-name");
  const name = libraryImportElement("input", "", "library-import-name"); name.maxLength = 60; name.required = true;
  const confirm = libraryButton("匯入成新歌單", async () => {
    const pending = libraryImportPending;
    if (!pending || pending.generation !== generation || pending.guild !== selected) throw new Error("預覽已失效，請重新預覽。");
    const result = await api("/api/library/import", "POST", {preview_id: pending.preview_id, revision: pending.revision, name: name.value});
    if (pending.generation !== generation) return;
    libraryData = result; libraryActive = result.playlists.at(-1).id;
    libraryImportPending = null; preview.hidden = true; libraryRender(); notice(result.message);
  });
  preview.append(title, summary, tracks, nameLabel, name, confirm);
  form.append(sourceLabel, source, label, url, previewButton);
  const sync = libraryButton("從來源重新同步", librarySync);
  sync.hidden = true;
  const origin = libraryImportElement("p", "", "library-source"); origin.hidden = true;
  origin.className = "library-source";
  wrap.append(toggle, form, status, preview, origin, sync); $("library-panel").append(wrap);
  libraryImportUI = {form, source, spotify, url, status, preview, title, summary, tracks, name, sync, origin};
  form.addEventListener("submit", event => {
    event.preventDefault();
    return libraryRun(previewButton, async () => {
      if (!selected) throw new Error("請先選擇伺服器。");
      if (url.value.includes("open.spotify.com") && spotify.disabled) throw new Error("目前無法讀取 Spotify 歌單");
      const guild = selected, epoch = generation;
      const value = await api("/api/guilds/" + guild + "/library/import/preview", "POST", {url: url.value.trim()});
      if (epoch !== generation || guild !== selected) return;
      libraryImportPending = {...value, generation: epoch, guild};
      source.value = value.source_type; title.textContent = value.title;
      summary.textContent = (value.count_is_minimum ? "來源至少 " : "來源共 ") + value.count + " 首，將匯入 " + value.import_count + " 首。" + value.warning;
      tracks.replaceChildren();
      for (const track of value.tracks) tracks.append(libraryImportElement("li", track.title + " · " + (track.duration ? duration(track.duration) : "長度未知")));
      name.value = Array.from(value.title).slice(0, 60).join(""); preview.hidden = false;
    });
  });
}
function libraryImportRender(list) {
  const ui = libraryImportUI;
  if (!ui) return;
  if (libraryData?.sources) {
    ui.spotify.disabled = !libraryData.sources.spotify;
    ui.spotify.textContent = libraryData.sources.spotify ? "Spotify" : "Spotify（目前無法讀取）";
    ui.status.hidden = !!libraryData.sources.spotify;
    ui.status.textContent = libraryData.sources.spotify ? "" : "目前無法讀取 Spotify 歌單";
  }
  ui.sync.hidden = ui.origin.hidden = !list?.source_url;
  ui.origin.textContent = list?.source_url ? "來源：" + list.source_url : "";
}
async function librarySync() {
  if (!selected) throw new Error("請先選擇伺服器。");
  const epoch = generation, guild = selected, pid = libraryActive, revision = libraryData.revision;
  const value = await api("/api/guilds/" + guild + "/library/" + encodeURIComponent(pid) + "/sync/preview", "POST", {revision});
  if (epoch !== generation || guild !== selected || pid !== libraryActive) return;
  const text = "重新同步將取代目前曲目：新增 " + value.diff.added + " 首、移除 " + value.diff.removed + " 首。"
    + value.warning + "確定從來源重新同步？";
  if (!window.confirm(text)) return;
  const result = await api("/api/library/" + encodeURIComponent(pid) + "/sync", "POST", {preview_id: value.preview_id, revision: value.revision});
  if (epoch !== generation || guild !== selected) return;
  libraryData = result; libraryRender(); notice(result.message);
}
libraryInitImports();
