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
  finally { libraryBusy = false; buttonBusy(button, false); button.disabled = false; favoriteRender(); controls(); }
}
function libraryClear() {
  libraryData = null; libraryPendingSong = null; libraryActive = "favorites";
  libraryImportPending = null;
  favoriteRender();
  if (libraryImportUI) {
    libraryImportUI.sync.hidden = libraryImportUI.origin.hidden = true;
    libraryImportUI.origin.textContent = "";
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
  libraryData = value; libraryRender(); favoriteRender(); return true;
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
  libraryData = result; libraryRender(); favoriteRender(); notice(result.message || "已更新歌單。");
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
function favoriteRender() {
  const button = $("favorite"), key = songIdentity(state?.current?.url);
  const saved = !!key && !!libraryData?.playlists[0]?.tracks.some(t => songIdentity(t.url) === key);
  button.setAttribute("aria-pressed", String(saved));
  button.title = saved ? "取消收藏" : "收藏這首歌";
  button.textContent = saved ? "♥ 已收藏" : "♡ 收藏";
  button.classList.toggle("is-favorite", saved);
  if (button.dataset.loading === "1") button.disabled = true;
}
$("favorite").addEventListener("click", () => libraryRun($("favorite"), async () => {
  const song = state?.current, epoch = generation;
  if (!song || !await libraryLoad() || epoch !== generation) return;
  const key = songIdentity(song.url);
  const saved = libraryData.playlists[0].tracks.some(t => songIdentity(t.url) === key);
  await libraryChange("favorites", saved ? {action:"remove_url",url:song.url}
    : {track:{title:song.title,url:song.url,duration:song.duration || null}}, saved ? "PATCH" : "POST", saved ? "" : "/tracks");
  if (!reduceMotion() && $("favorite").animate)
    $("favorite").animate([{transform:"scale(1)"},{transform:"scale(1.12)"},{transform:"scale(1)"}], {duration:230});
}));
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
  const hint = libraryButton("要匯入歌單？在上方點歌框貼上歌單網址", async () => {
    libraryView("play"); $("query").focus();
  });
  hint.className = "subtle library-import-hint";
  $("library-import-hint").append(hint);
  const sync = libraryButton("從來源重新同步", librarySync); sync.hidden = true;
  const origin = libraryImportElement("p", "", "library-source"); origin.hidden = true;
  $("library-panel").append(origin, sync);
  libraryImportUI = {sync, origin};
}
function libraryImportRender(list) {
  if (!libraryImportUI) return;
  libraryImportUI.sync.hidden = libraryImportUI.origin.hidden = !list?.source_url;
  libraryImportUI.origin.textContent = list?.source_url ? "來源：" + list.source_url : "";
}
async function librarySavePreview(song, selectedItems, name, button) {
  return libraryRun(button, async () => {
    const epoch = generation;
    const result = await api("/api/library/import", "POST", {
      preview_id: song.preview_id, revision: song.save_revision,
      name, selected_items: [...selectedItems]});
    if (epoch !== generation) return;
    libraryData = result; libraryActive = result.playlists.at(-1).id;
    clearPreview(); libraryView("library"); libraryRender(); notice(result.message);
  });
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
