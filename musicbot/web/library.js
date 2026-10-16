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
  $("library-list").replaceChildren(); $("playlist-picker").replaceChildren();
  libraryView("play");
  $("library-panel").hidden = true; $("library-save-dialog").close?.();
}
function libraryView(page) {
  libraryPage = page;
  $("play-view").hidden = page !== "play"; $("library-panel").hidden = page !== "library";
  if ($("admin-panel")) $("admin-panel").hidden = page !== "admin";
  for (const key of ["play", "library", "admin"]) if ($("nav-" + key)) $("nav-" + key).setAttribute("aria-pressed", String(key === page));
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
