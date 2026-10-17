"use strict";
let adminOwner = false, adminApl = null, adminPage = 1, adminQuery = "", adminEpoch = 0;
function adminClear() {
  ++adminEpoch; adminOwner = false; adminApl = null;
  $("nav-admin").hidden = true; $("admin-panel").hidden = true;
  $("admin-apl-list").replaceChildren();
  $("admin-permissions")?.replaceChildren();
  $("admin-vote-skip-enabled").checked = true;
  $("admin-vote-skip-enabled").disabled = true;
  $("admin-vote-skip-save").disabled = true;
  $("admin-vote-skip-status").textContent = "";
  $("empty-queue-status").textContent = ""; $("radio-seeds").textContent = "";
  $("empty-queue-mode").value = "autoplaylist";
  $("admin-lyrics-status").textContent="";
  $("admin-notify-channel").replaceChildren();
  $("admin-notify-warning").hidden = true;
  $("admin-notify-status").textContent = "";
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
  $("admin-apl-count").textContent = t("m0000") + adminApl.total + t("m0001") + adminApl.matched + t("m0002") + adminApl.page + t("m0003");
  $("admin-apl-prev").disabled = adminPage <= 1;
  $("admin-apl-next").disabled = adminPage * adminApl.page_size >= adminApl.matched;
  $("admin-apl-list").replaceChildren();
  for (const track of adminApl.tracks) {
    const li = document.createElement("li"), label = document.createElement("span");
    label.textContent = track.url || track.title;
    const remove = libraryButton("m0004", async () => {
      if (!window.confirm(t("m0005"))) return;
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
  await adminAplLoad(); notice(t("m0006"));
}
$("nav-admin").addEventListener("click", () => libraryRun($("nav-admin"), async () => {
  if (!adminOwner) return;
  libraryView("admin"); await adminNotifyLoad(); await adminMaintenanceLoad(); await adminEmptyQueueLoad(); await adminLyricsLoad(); await adminAplLoad();
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
  return date && Number.isFinite(date.getTime()) ? date.toLocaleString(dashboardLocale(), {timeZone:dashboardTimeZone(), hour12:false}) : t("m0007");
}
async function adminMaintenanceLoad() {
  if (!adminOwner || !selected) return;
  const epoch = generation, guild = selected;
  $("maintenance-status").textContent = t("m0008");
  const value = await api("/api/guilds/" + guild + "/admin/maintenance");
  if (epoch !== generation || guild !== selected || !adminOwner) return;
  const list = $("maintenance-details"); list.replaceChildren();
  function row(label, text, warning = false) {
    const key = document.createElement("dt"), detail = document.createElement("dd");
    key.textContent = label; detail.textContent = text; detail.classList.toggle("maintenance-warning", warning);
    list.append(key, detail);
  }
  const cookie = value.cookie || {};
  row("YouTube cookie", cookie.status === "unused" ? t("m0009") : cookie.status !== "ok" ? t("m0010") :
    cookie.earliest_expiry ? maintenanceDate(cookie.earliest_expiry) + t("m0011") + cookie.remaining_days + t("m0012") : t("m0013"), cookie.warning);
  if (cookie.updated_at) row(t("m0014"), maintenanceDate(cookie.updated_at));
  for (const item of cookie.cookies || []) row(item.name, maintenanceDate(item.expires_at) + t("m0011") + item.remaining_days + t("m0012"), item.remaining_days <= 7);
  for (const name of ["yt-dlp","yt-dlp-ejs"]) row(name, value.versions?.[name] || t("m0015"));
  row(t("m0016"), maintenanceDate(value.started_at));
  row(t("m0017"), value.last_stop ? maintenanceDate(value.last_stop.time) + "・" + value.last_stop.classification : t("m0007"));
  row(t("m0018"), value.dashboard_version || t("m0007"));
  row(t("m0019"), String(value.viewers ?? 0) + t("m0020"));
  const host = value.host_status || {};
  if (host.status === "ok") {
    row(t("m0021"), maintenanceDate(host.written_at));
    row(t("m0022"), maintenanceDate(host.ytdlp_update?.updated) + "・" + (host.ytdlp_update?.channel || "unknown"));
    for (const name of ["yt-dlp","yt-dlp-ejs","bgutil-plugin"]) if (host.ytdlp_update?.[name]) row(t("m0023") + name, host.ytdlp_update[name]);
    const result = {success:t("m0024"),failure:t("m0025"),running:t("m0026"),unknown:t("m0007")};
    row(t("m0027"), (result[host.cookie_sync?.result] || t("m0007")) + t("m0028") + maintenanceDate(host.cookie_sync?.last_run) + t("m0029") + maintenanceDate(host.cookie_sync?.next_run));
  } else if (host.status === "unavailable") row(t("m0030"), t("m0010"));
  $("maintenance-status").textContent = "";
}
$("maintenance-refresh").addEventListener("click", () =>
  libraryRun($("maintenance-refresh"), adminMaintenanceLoad));

function adminEmptyQueueRender(value) {
  $("radio-seeds").textContent = value.seed_count ? t("m0031") + value.seed_titles[0] + t("m0032") + value.seed_count + t("m0033") : t("m0034");
  $("empty-queue-mode").value = value.empty_queue;
  $("radio-min-seconds").value = value.radio_min_seconds;
  $("radio-max-seconds").value = value.radio_max_seconds;
  $("empty-queue-status").textContent = value.radio_suspended_seconds > 0 ?
    t("m0035") + value.radio_suspended_seconds + t("m0036") : "";
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
        (data.radio_max_seconds>0&&data.radio_min_seconds>data.radio_max_seconds)) throw new Error(t("m0037"));
    const value = await api("/api/guilds/" + guild + "/admin/empty-queue", "POST", data);
    if (epoch !== generation || guild !== selected || !adminOwner) return;
    adminEmptyQueueRender(value); notice(t("m0038"));
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
   $("admin-lyrics-status").textContent=t("m0039");
   if(state)state.lyrics_available=value.enabled;
   if(!value.enabled)toggleLyrics(false,false);
   await refresh();
 });
});


function adminNotifyRender(value) {
  const select = $("admin-notify-channel");
  const option = (id, name, key = "") => {
    const node = document.createElement("option");
    node.value = id; node.textContent = name;
    if (key) node.dataset.i18n = key;
    return node;
  };
  select.replaceChildren(option("", t("notify.default"), "notify.default"));
  for (const channel of value.channels) select.append(option(channel.id, "#" + channel.name));
  if (value.channel_id && !value.channels.some(channel => channel.id === value.channel_id)) {
    const missing = option(value.channel_id, t("notify.unavailable"), "notify.unavailable");
    missing.disabled = true; select.append(missing);
  }
  select.value = value.channel_id || "";
  $("admin-notify-warning").hidden = !value.unavailable;
}
async function adminNotifyLoad() {
  if (!adminOwner || !selected) return;
  const guild = selected, epoch = generation, token = adminEpoch;
  const value = await api("/api/guilds/" + guild + "/admin/notification-channel");
  if (epoch !== generation || guild !== selected || token !== adminEpoch || !adminOwner) return;
  adminNotifyRender(value); $("admin-notify-status").textContent = "";
}
$("admin-notify-form").addEventListener("submit", event => {
  event.preventDefault();
  return libraryRun($("admin-notify-save"), async () => {
    if (!adminOwner || !selected) return;
    const guild = selected, epoch = generation, token = adminEpoch;
    const value = await api("/api/guilds/" + guild + "/admin/notification-channel", "POST",
      {channel_id: $("admin-notify-channel").value || null});
    if (epoch !== generation || guild !== selected || token !== adminEpoch || !adminOwner) return;
    adminNotifyRender(value); $("admin-notify-status").textContent = t("notify.saved");
  });
});
