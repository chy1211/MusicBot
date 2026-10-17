"use strict";
let popularRequest = 0;
function popularClear() {
  ++popularRequest;
  $("popular-list").replaceChildren();
  $("popular-status").textContent = "選擇伺服器後查看熱門點播。";
}
async function popularLoad() {
  const request = ++popularRequest, epoch = generation, guild = selected;
  if (!guild || !connected) { popularClear(); return; }
  const period = $("popular-period").value || "7";
  $("popular-status").textContent = "正在讀取熱門點播…";
  try {
    const result = await api("/api/guilds/" + guild + "/popular?period=" + period);
    if (request !== popularRequest || epoch !== generation || guild !== selected) return;
    $("popular-list").replaceChildren();
    const tracks = (result.tracks || []).slice(0, 20);
    $("popular-status").textContent = tracks.length ? "僅統計成員點播；每次加入佇列計一次。" : "這段期間還沒有成員點播紀錄。";
    tracks.forEach((song, index) => {
      const row = document.createElement("li"), rank = document.createElement("span");
      rank.className = "popular-rank"; rank.textContent = String(index + 1);
      const info = document.createElement("div"); info.className = "history-info";
      const title = document.createElement("p"); title.textContent = song.title;
      const meta = document.createElement("small");
      meta.textContent = song.count + " 次 · " + (song.duration ? duration(song.duration) : "長度未知");
      info.append(title, meta);
      const actions = document.createElement("div"); actions.className = "history-actions";
      const add = document.createElement("button"); add.type = "button"; add.textContent = "加入";
      add.setAttribute("aria-label", "加入：" + song.title);
      add.disabled = !safeURL(song.url);
      add.addEventListener("click", async () => {
        if (epoch !== generation || guild !== selected) return;
        libraryView("play"); await previewHistorySong(song, guild, epoch);
      });
      actions.append(add, librarySaveButton(song)); row.append(rank, info, actions);
      $("popular-list").append(row);
    });
  } catch (error) {
    if (request === popularRequest && epoch === generation && guild === selected)
      $("popular-status").textContent = error.message || "暫時無法取得熱門點播。";
  }
}
$("nav-popular").addEventListener("click", () => { libraryView("popular"); return popularLoad(); });
$("popular-period").addEventListener("change", popularLoad);
$("popular-refresh").addEventListener("click", popularLoad);
