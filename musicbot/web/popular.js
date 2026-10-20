"use strict";
let popularRequest = 0;
function popularClear() {
  ++popularRequest;
  $("popular-list").replaceChildren();
  $("popular-status").textContent = t("m0216");
}
async function popularLoad() {
  const request = ++popularRequest, epoch = generation, guild = selected;
  if (!guild || !connected) { popularClear(); return; }
  const period = $("popular-period").value || "7";
  $("popular-status").textContent = t("m0217");
  try {
    const result = await api("/api/guilds/" + guild + "/popular?period=" + period);
    if (request !== popularRequest || epoch !== generation || guild !== selected) return;
    $("popular-list").replaceChildren();
    const tracks = (result.tracks || []).slice(0, 20);
    $("popular-status").textContent = tracks.length ? t("m0218") : t("m0219");
    tracks.forEach((song, index) => {
      const row = document.createElement("li"), rank = document.createElement("span");
      rank.className = "popular-rank"; rank.textContent = String(index + 1);
      const info = document.createElement("div"); info.className = "history-info";
      const title = songTitle(document.createElement("p"), song);
      const meta = document.createElement("small");
      meta.textContent = song.count + t("m0220") + (song.duration ? duration(song.duration) : t("m0097"));
      info.append(title, meta);
      const actions = document.createElement("div"); actions.className = "history-actions";
      const add = document.createElement("button"); add.type = "button"; buttonLabel(add, "m0612");
      add.setAttribute("aria-label", t("m0132") + song.title);
      add.disabled = !safeURL(song.url);
      add.addEventListener("click", async () => {
        if (add.disabled || busy || resolving || !connected || epoch !== generation || guild !== selected) return;
        buttonBusy(add, true);
        try {
          const result = await api("api/guilds/" + guild + "/resolve", "POST", {query:song.url, action:"play"});
          if (epoch !== generation || guild !== selected || !connected) return;
          const track = (result.results || []).find(item => item.kind === "track" && item.allowed && item.preview_id && safeURL(item.url));
          if (!track) throw new Error(result.results?.[0]?.reason || t("m0613"));
          if (busy) throw new Error(t("m0614"));
          await act("play", {query:track.url, preview_id:track.preview_id});
        } catch (error) {
          if (epoch === generation && guild === selected) notice(error.message || t("m0613"), true);
        } finally {
          buttonBusy(add, false);
          add.disabled = !safeURL(song.url) || epoch !== generation || guild !== selected;
        }
      });
      actions.append(add, librarySaveButton(song)); row.append(rank, info, actions);
      $("popular-list").append(row);
    });
  } catch (error) {
    if (request === popularRequest && epoch === generation && guild === selected)
      $("popular-status").textContent = error.message || t("m0221");
  }
}
$("nav-popular").addEventListener("click", () => { libraryView("popular"); return popularLoad(); });
$("popular-period").addEventListener("change", popularLoad);
$("popular-refresh").addEventListener("click", popularLoad);
