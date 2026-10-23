"use strict";
// Shares authenticated api/state helpers with dashboard.js; all text uses textContent.
let libraryData = null, libraryActive = "favorites", libraryPendingSong = null, libraryBusy = false;
let libraryPage = "play", libraryDetailOpen = false;
function libraryButton(key, run) {
  const b = document.createElement("button"); b.type = "button"; buttonLabel(b, key);
  b.addEventListener("click", () => libraryRun(b, run)); return b;
}
async function libraryRun(button, run) {
  if (libraryBusy) return;
  libraryBusy = true; buttonBusy(button, true);
  try { await run(); } catch (error) { notice(error.message || t("m0190"), true); }
  finally { libraryBusy = false; buttonBusy(button, false); button.disabled = false; favoriteRender(); controls(); }
}
function libraryClear() {
  libraryData = null; libraryPendingSong = null; libraryActive = "favorites"; libraryDetailOpen = false;
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
  window.dispatchEvent?.(new CustomEvent("musicbot:navigate", {detail: page}));
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
function playlistName(item) { return item.id === "favorites" ? t("m0192") : item.name; }
function libraryTrack(song) {
  const track = {title: song.title, url: song.url, duration: song.duration || null};
  const thumbnail = typeof playlistCoverThumbnail === "function" ? playlistCoverThumbnail(song) : safeURL(song?.thumbnail || "");
  if (thumbnail) track.thumbnail = thumbnail;
  return track;
}
function libraryPlaylistCover(tracks, size, extraClass = "") {
  if (typeof playlistCoverElement !== "function") return null;
  const cover = playlistCoverElement(tracks, size);
  if (extraClass) cover.className += " " + extraClass;
  return cover;
}
function libraryRender() {
  $("library-playlists").replaceChildren();
  if (!libraryData) return;
  if (!libraryData.playlists.some(p => p.id === libraryActive)) libraryActive = "favorites";
  for (const item of libraryData.playlists) {
    const row = document.createElement("li"), button = document.createElement("button");
    button.type = "button"; button.className = "library-choice";
    const title = document.createElement("span"); title.className = "library-choice-title"; title.textContent = playlistName(item);
    const meta = document.createElement("small");
    meta.textContent = item.tracks.length + t("m0191") + (item.source_type === "spotify" ? "Spotify" : item.source_url ? "YouTube" : item.id === "favorites" ? t("m0192") : t("m0193"));
    const cover = libraryPlaylistCover(item.tracks, 48);
    if (cover) { button.style.gridTemplateColumns = "48px minmax(0, 1fr)"; cover.style.gridRow = "span 2"; cover.style.gridColumn = "1"; title.style.gridColumn = meta.style.gridColumn = "2"; }
    if (cover) button.append(cover);
    button.append(title, meta); button.setAttribute("aria-current", String(item.id === libraryActive));
    button.addEventListener("click", () => {
      libraryActive = item.id; libraryDetailOpen = true; libraryRender();
      $("library-detail-heading").focus();
    });
    row.append(button); $("library-playlists").append(row);
  }
  const list = libraryData.playlists.find(p => p.id === libraryActive);
  $("library-panel").classList.toggle("detail-open", libraryDetailOpen);
  const heading = $("library-detail-heading"), headingTitle = document.createElement("span");
  headingTitle.textContent = playlistName(list);
  const hero = libraryPlaylistCover(list.tracks, 64, "playlist-cover-hero");
  if (hero) {
    heading.style.display = "flex"; heading.style.alignItems = "center"; heading.style.gap = "12px";
    heading.replaceChildren(hero, headingTitle);
  } else heading.textContent = playlistName(list);
  $("library-meta").textContent = list.tracks.length + t("m0033") + (list.source_url ? " · " + (list.source_type === "spotify" ? "Spotify" : "YouTube") : "");
  $("library-rename-form").hidden = list.id === "favorites";
  $("library-delete").hidden = list.id === "favorites";
  $("library-actions").open = false;
  libraryImportRender(list);
  $("library-name").value = playlistName(list); $("library-name").disabled = list.id === "favorites";
  $("library-rename").disabled = $("library-delete").disabled = list.id === "favorites";
  $("library-list").replaceChildren();
  const selectedTracks = new Set();
  function play(all) { return libraryPlay(list, all ? undefined : [...selectedTracks]); }
  $("library-enqueue-all").onclick = () => libraryRun($("library-enqueue-all"), () => play(true));
  $("library-play-all").disabled = !list.tracks.length;
  $("library-enqueue-all").disabled = !list.tracks.length;
  $("library-play-all").onclick = () => libraryRun($("library-play-all"), () => play(true));
  $("library-play-selected").disabled = true;
  $("library-play-selected").onclick = () => libraryRun($("library-play-selected"), () => play(false));
  list.tracks.forEach((song, index) => {
    const row = document.createElement("li"); row.className = "library-track";
    const check = document.createElement("input"); check.type = "checkbox";
    check.setAttribute("aria-label", t("m0095") + song.title);
    check.addEventListener("change", () => {
      if (check.checked) selectedTracks.add(String(index)); else selectedTracks.delete(String(index));
      $("library-play-selected").disabled = selectedTracks.size === 0;
    });
    const info = document.createElement("div"); info.className = "song";
    const title = songTitle(document.createElement("p"), song); info.append(title);
    const length = document.createElement("small"); length.className = "song-length";
    length.textContent = song.duration ? duration(song.duration) : t("m0097");
    const remove = libraryButton("m0004", () => libraryChange(list.id, {action:"remove", index}));
    remove.setAttribute("aria-label", t("m0194") + song.title);
    row.append(check, imageElement(song.thumbnail), info, length, remove); $("library-list").append(row);
  });
  $("library-empty").hidden = list.tracks.length !== 0;
}
async function libraryChange(id, data, method = "PATCH", suffix = "") {
  const epoch = generation, revision = libraryData.revision;
  const result = await api("/api/library/" + encodeURIComponent(id) + suffix, method, {...data, revision});
  if (epoch !== generation) return;
  libraryData = result; libraryRender(); favoriteRender(); notice(result.message || t("m0195"));
}
async function libraryPlay(list, chosen) {
  if (!selected || !connected) throw new Error(t("m0196"));
  const guild = selected, epoch = generation;
  const data = {revision: libraryData.revision};
  if (chosen !== undefined) data.selected_items = chosen;
  const result = await api("/api/guilds/" + guild + "/library/" + encodeURIComponent(list.id) + "/play", "POST", data);
  if (epoch !== generation || guild !== selected) return;
  render(result.state, true); notice(result.message, result.skipped > 0);
}
async function librarySave(song, favorite = false) {
  if (!safeURL(song?.url)) throw new Error(t("m0197"));
  if (!await libraryLoad()) return;
  const track = libraryTrack(song);
  if (favorite) return libraryChange("favorites", {track}, "POST", "/tracks");
  libraryPendingSong = track;
  $("playlist-picker").replaceChildren();
  for (const list of libraryData.playlists) {
    const option = document.createElement("option"); option.value = list.id; option.textContent = playlistName(list);
    $("playlist-picker").append(option);
  }
  $("library-save-dialog").showModal();
}
function librarySaveButton(song) {
  const button = libraryButton("m0198", () => librarySave(song));
  button.className = "save-to-library"; return button;
}
$("nav-play").addEventListener("click", () => libraryView("play"));
$("nav-library").addEventListener("click", () => libraryRun($("nav-library"), async () => {
  libraryView("library"); await libraryLoad();
}));
$("library-back").addEventListener("click", () => {
  libraryDetailOpen = false; libraryRender();
  const active = $("library-playlists").querySelector('[aria-current="true"]');
  active?.focus();
});
$("library-refresh").addEventListener("click", () => libraryRun($("library-refresh"), libraryLoad));
$("library-create").addEventListener("submit", event => {
  event.preventDefault();
  return libraryRun($("library-create-button"), async () => {
    const epoch = generation;
    const result = await api("/api/library", "POST", {name: $("library-new-name").value});
    if (epoch !== generation) return;
    libraryData = result; libraryActive = result.playlists.at(-1).id; libraryDetailOpen = true;
    $("library-new-name").value = ""; libraryRender();
  });
});
$("library-rename").addEventListener("click", () => libraryRun($("library-rename"), () => libraryChange(libraryActive, {name: $("library-name").value})));
$("library-delete").addEventListener("click", () => {
  if (!window.confirm(t("m0199"))) return;
  return libraryRun($("library-delete"), () => libraryChange(libraryActive, {}, "DELETE"));
});
function favoriteRender() {
  const button = $("favorite"), key = songIdentity(state?.current?.url);
  const saved = !!key && !!libraryData?.playlists[0]?.tracks.some(t => songIdentity(t.url) === key);
  button.setAttribute("aria-pressed", String(saved));
  button.title = saved ? t("m0200") : t("m0201");
  button.textContent = saved ? "♥" : "♡";
  button.setAttribute("aria-label", button.title);
  button.classList.toggle("is-favorite", saved);
  if (button.dataset.loading === "1") button.disabled = true;
}
$("favorite").addEventListener("click", () => libraryRun($("favorite"), async () => {
  const song = state?.current, epoch = generation;
  if (!song || !await libraryLoad() || epoch !== generation) return;
  const key = songIdentity(song.url);
  const saved = libraryData.playlists[0].tracks.some(t => songIdentity(t.url) === key);
  await libraryChange("favorites", saved ? {action:"remove_url",url:song.url}
    : {track:libraryTrack(song)}, saved ? "PATCH" : "POST", saved ? "" : "/tracks");
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
function libraryImportElement(tag, key, id) {
  const element = document.createElement(tag);
  if (key) { element.dataset.i18n = key; element.textContent = t(key); }
  if (id) element.id = id;
  return element;
}
function libraryInitImports() {
  const hint = libraryButton("m0202", async () => {
    libraryView("play"); $("query").focus();
  });
  hint.className = "subtle library-import-hint";
  $("library-import-hint").append(hint);
  const sync = libraryButton("m0203", librarySync); sync.hidden = true;
  const origin = libraryImportElement("p", "m0204", "library-source"); origin.hidden = true;
  $("library-sync-slot").append(origin, sync);
  libraryImportUI = {sync, origin};
}
function libraryImportRender(list) {
  if (!libraryImportUI) return;
  libraryImportUI.sync.hidden = libraryImportUI.origin.hidden = !list?.source_url;
  libraryImportUI.origin.textContent = list?.source_url ? t("m0204") : "";
}
async function librarySavePreview(song, selectedItems, name, button) {
  return libraryRun(button, async () => {
    const epoch = generation;
    const result = await api("/api/library/import", "POST", {
      preview_id: song.preview_id, revision: song.save_revision,
      name, selected_items: [...selectedItems]});
    if (epoch !== generation) return;
    libraryData = result; libraryActive = result.playlists.at(-1).id; libraryDetailOpen = true;
    clearPreview(); libraryView("library"); libraryRender(); notice(result.message);
  });
}
async function librarySync() {
  if (!selected) throw new Error(t("m0205"));
  const epoch = generation, guild = selected, pid = libraryActive, revision = libraryData.revision;
  const value = await api("/api/guilds/" + guild + "/library/" + encodeURIComponent(pid) + "/sync/preview", "POST", {revision});
  if (epoch !== generation || guild !== selected || pid !== libraryActive) return;
  const text = t("m0206") + value.diff.added + t("m0207") + value.diff.removed + t("m0208")
    + value.warning + t("m0209");
  if (!window.confirm(text)) return;
  const result = await api("/api/library/" + encodeURIComponent(pid) + "/sync", "POST", {preview_id: value.preview_id, revision: value.revision});
  if (epoch !== generation || guild !== selected) return;
  libraryData = result; libraryRender(); notice(result.message);
}
libraryInitImports();
