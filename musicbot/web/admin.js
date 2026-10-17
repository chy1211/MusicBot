"use strict";
let adminOwner = false, adminApl = null, adminPage = 1, adminQuery = "", adminEpoch = 0;
function adminClear() {
  ++adminEpoch; adminOwner = false; adminApl = null;
  $("nav-admin").hidden = true; $("admin-panel").hidden = true;
  $("admin-apl-list").replaceChildren();
  $("admin-permissions")?.replaceChildren();
  $("empty-queue-status").textContent = ""; $("radio-seeds").textContent = "";
  $("empty-queue-mode").value = "autoplaylist";
  $("admin-lyrics-status").textContent="";
  $("maintenance-details").replaceChildren(); $("maintenance-status").textContent = "";
  if (typeof pendingPermission !== "undefined") pendingPermission = null;
  $("permission-confirm-dialog").close?.();
}
async function adminCapability() {
  const epoch = generation, token = ++adminEpoch;
  try {
    const value = await api("/api/library");
    if (epoch !== generation || token !== adminEpoch) return;
    adminOwner = value.owner === true;
    $("nav-admin").hidden = !adminOwner;
  } catch { adminClear(); }
}
async function adminAplLoad() {
  if (!adminOwner || !selected) return;
  const guild = selected, epoch = generation;
  const value = await api("/api/guilds/" + guild + "/admin/autoplaylist?page=" + adminPage + "&q=" + encodeURIComponent(adminQuery));
  if (epoch !== generation || guild !== selected) return;
  adminApl = value; adminAplRender();
}
function adminAplRender() {
  $("admin-apl-count").textContent = "共 " + adminApl.total + " 首・符合 " + adminApl.matched + " 首・第 " + adminApl.page + " 頁";
  $("admin-apl-prev").disabled = adminPage <= 1;
  $("admin-apl-next").disabled = adminPage * adminApl.page_size >= adminApl.matched;
  $("admin-apl-list").replaceChildren();
  for (const track of adminApl.tracks) {
    const li = document.createElement("li"), label = document.createElement("span");
    label.textContent = track.url || track.title;
    const remove = libraryButton("刪除", async () => {
      if (!window.confirm("確定從自動播放清單刪除這首歌？")) return;
      await adminAplChange({index: track.index}, "DELETE");
    });
    li.append(label, remove); $("admin-apl-list").append(li);
  }
}
async function adminAplChange(data, method = "POST") {
  if (!adminOwner || !selected) return;
  if (!adminApl) await adminAplLoad();
  const guild = selected, epoch = generation;
  await api("/api/guilds/" + guild + "/admin/autoplaylist", method, {...data, revision: adminApl.revision});
  if (epoch !== generation || guild !== selected) return;
  await adminAplLoad(); notice("已更新自動播放清單。");
}
$("nav-admin").addEventListener("click", () => libraryRun($("nav-admin"), async () => {
  if (!adminOwner) return;
  libraryView("admin"); await adminMaintenanceLoad(); await adminEmptyQueueLoad(); await adminLyricsLoad(); await adminAplLoad();
  if (typeof adminPermissionsLoad === "function") await adminPermissionsLoad();
}));
$("admin-apl-search").addEventListener("submit", event => {
  event.preventDefault(); adminPage = 1; adminQuery = $("admin-apl-query").value;
  return libraryRun($("admin-apl-search-button"), adminAplLoad);
});
for (const [id, delta] of [["admin-apl-prev", -1], ["admin-apl-next", 1]]) $(id).addEventListener("click", () => libraryRun($(id), async () => {
  adminPage += delta; await adminAplLoad();
}));
if (connected) adminCapability();

function maintenanceDate(value) {
  const date = value ? new Date(value) : null;
  return date && Number.isFinite(date.getTime()) ? date.toLocaleString("zh-TW", {timeZone:"Asia/Taipei", hour12:false}) : "無資料";
}
async function adminMaintenanceLoad() {
  if (!adminOwner || !selected) return;
  const epoch = generation, guild = selected;
  $("maintenance-status").textContent = "讀取中…";
  const value = await api("/api/guilds/" + guild + "/admin/maintenance");
  if (epoch !== generation || guild !== selected || !adminOwner) return;
  const list = $("maintenance-details"); list.replaceChildren();
  function row(label, text, warning = false) {
    const key = document.createElement("dt"), detail = document.createElement("dd");
    key.textContent = label; detail.textContent = text; detail.classList.toggle("maintenance-warning", warning);
    list.append(key, detail);
  }
  const cookie = value.cookie || {};
  row("YouTube cookie", cookie.status === "unused" ? "未使用 cookie" : cookie.status !== "ok" ? "暫時無法讀取" :
    cookie.earliest_expiry ? maintenanceDate(cookie.earliest_expiry) + "・剩餘 " + cookie.remaining_days + " 天" : "沒有可判斷到期日的登入 cookie", cookie.warning);
  if (cookie.updated_at) row("cookie 更新時間", maintenanceDate(cookie.updated_at));
  for (const item of cookie.cookies || []) row(item.name, maintenanceDate(item.expires_at) + "・剩餘 " + item.remaining_days + " 天", item.remaining_days <= 7);
  for (const name of ["yt-dlp","yt-dlp-ejs"]) row(name, value.versions?.[name] || "未載入");
  row("本次啟動", maintenanceDate(value.started_at));
  row("上次停止", value.last_stop ? maintenanceDate(value.last_stop.time) + "・" + value.last_stop.classification : "無資料");
  row("控制台版本", value.dashboard_version || "無資料");
  row("連線中的網頁人數", String(value.viewers ?? 0) + " 人（最近 45 秒）");
  const host = value.host_status || {};
  if (host.status === "ok") {
    row("主機狀態更新", maintenanceDate(host.written_at));
    row("主機套件更新", maintenanceDate(host.ytdlp_update?.updated) + "・" + (host.ytdlp_update?.channel || "unknown"));
    for (const name of ["yt-dlp","yt-dlp-ejs","bgutil-plugin"]) if (host.ytdlp_update?.[name]) row("主機 " + name, host.ytdlp_update[name]);
    const result = {success:"成功",failure:"失敗",running:"執行中",unknown:"無資料"};
    row("cookie 同步", (result[host.cookie_sync?.result] || "無資料") + "・上次 " + maintenanceDate(host.cookie_sync?.last_run) + "・下次 " + maintenanceDate(host.cookie_sync?.next_run));
  } else if (host.status === "unavailable") row("主機狀態", "暫時無法讀取");
  $("maintenance-status").textContent = "";
}
$("maintenance-refresh").addEventListener("click", () =>
  libraryRun($("maintenance-refresh"), adminMaintenanceLoad));

function adminEmptyQueueRender(value) {
  $("radio-seeds").textContent = value.seed_count ? "目前種子：" + value.seed_titles[0] + " 等 " + value.seed_count + " 首" : "目前種子：尚無真人點播，會優先使用熱門點播。";
  $("empty-queue-mode").value = value.empty_queue;
  $("radio-min-seconds").value = value.radio_min_seconds;
  $("radio-max-seconds").value = value.radio_max_seconds;
  $("empty-queue-status").textContent = value.radio_suspended_seconds > 0 ?
    "電台連續失敗，暫停 " + value.radio_suspended_seconds + " 秒；期間使用自動播放清單。" : "";
}
async function adminEmptyQueueLoad() {
  if (!adminOwner || !selected) return;
  const guild = selected, epoch = generation;
  const value = await api("/api/guilds/" + guild + "/admin/empty-queue");
  if (epoch !== generation || guild !== selected || !adminOwner) return;
  adminEmptyQueueRender(value);
}
$("empty-queue-form").addEventListener("submit", event => {
  event.preventDefault();
  return libraryRun($("empty-queue-save"), async () => {
    if (!adminOwner || !selected) return;
    const guild = selected, epoch = generation;
    const data = {empty_queue:$("empty-queue-mode").value,
      radio_min_seconds:Number($("radio-min-seconds").value), radio_max_seconds:Number($("radio-max-seconds").value)};
    if (![data.radio_min_seconds,data.radio_max_seconds].every(value=>Number.isInteger(value)&&value>=0) ||
        (data.radio_max_seconds>0&&data.radio_min_seconds>data.radio_max_seconds)) throw new Error("電台秒數範圍不正確。");
    const value = await api("/api/guilds/" + guild + "/admin/empty-queue", "POST", data);
    if (epoch !== generation || guild !== selected || !adminOwner) return;
    adminEmptyQueueRender(value); notice("已儲存佇列空時設定。");
  });
});


async function adminLyricsLoad(){
 if(!adminOwner||!selected)return;
 const epoch=generation,guild=selected;
 const value=await api("/api/guilds/"+guild+"/admin/lyrics");
 if(epoch!==generation||guild!==selected||!adminOwner)return;
 $("admin-lyrics-enabled").value=String(value.enabled);$("admin-lyrics-status").textContent="";
}
$("admin-lyrics-form").addEventListener("submit",event=>{
 event.preventDefault();
 return libraryRun($("admin-lyrics-save"),async()=>{
   if(!adminOwner||!selected)return;
   const epoch=generation,guild=selected;
   const value=await api("/api/guilds/"+guild+"/admin/lyrics","POST",{enabled:$("admin-lyrics-enabled").value==="true"});
   if(epoch!==generation||guild!==selected||!adminOwner)return;
   $("admin-lyrics-status").textContent="已儲存歌詞設定。";
   if(state)state.lyrics_available=value.enabled;
   if(!value.enabled)toggleLyrics(false,false);
   await refresh();
 });
});
