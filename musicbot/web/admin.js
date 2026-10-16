"use strict";
let adminOwner = false, adminApl = null, adminPage = 1, adminQuery = "", adminEpoch = 0;
function adminClear() {
  ++adminEpoch; adminOwner = false; adminApl = null;
  $("nav-admin").hidden = true; $("admin-panel").hidden = true;
  $("autoplaylist-current").hidden = true; $("admin-apl-list").replaceChildren();
  $("admin-permissions")?.replaceChildren();
  if (typeof pendingPermission !== "undefined") pendingPermission = null;
  $("permission-confirm-dialog").close?.();
}
async function adminCapability() {
  const epoch = generation, token = ++adminEpoch;
  try {
    const value = await api("/api/library");
    if (epoch !== generation || token !== adminEpoch) return;
    adminOwner = value.owner === true;
    $("nav-admin").hidden = !adminOwner; $("autoplaylist-current").hidden = !adminOwner;
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
  libraryView("admin"); await adminAplLoad();
  if (typeof adminPermissionsLoad === "function") await adminPermissionsLoad();
}));
$("admin-apl-search").addEventListener("submit", event => {
  event.preventDefault(); adminPage = 1; adminQuery = $("admin-apl-query").value;
  return libraryRun($("admin-apl-search-button"), adminAplLoad);
});
for (const [id, delta] of [["admin-apl-prev", -1], ["admin-apl-next", 1]]) $(id).addEventListener("click", () => libraryRun($(id), async () => {
  adminPage += delta; await adminAplLoad();
}));
$("admin-apl-add").addEventListener("submit", event => {
  event.preventDefault();
  return libraryRun($("admin-apl-add-button"), async () => {
    await adminAplChange({url: $("admin-apl-url").value}); $("admin-apl-url").value = "";
  });
});
$("autoplaylist-current").addEventListener("click", () => libraryRun($("autoplaylist-current"), () => adminAplChange({current: true})));

if (connected) adminCapability();
