"use strict";
let adminPermissions = null, pendingPermission = null;
async function adminPermissionsLoad() {
  if (!adminOwner || !selected) return;
  const guild = selected, epoch = generation;
  await adminVoteSkipLoad();
  if (epoch !== generation || guild !== selected || !adminOwner) return;
  const value = await api("/api/guilds/" + guild + "/admin/permissions");
  if (epoch !== generation || guild !== selected || !adminOwner) return;
  adminPermissions = value; adminPermissionsRender();
}
function permissionText(value) {
  return typeof value === "boolean" ? value ? t("m0210") : t("m0211") : Array.isArray(value) ? value.join("、") || t("m0212") : String(value);
}
function adminPermissionsRender() {
  $("admin-permissions").replaceChildren();
  const heading = document.createElement("h3"); heading.textContent = t("m0213");
  $("admin-permissions").append(heading);
  for (const group of adminPermissions.groups) {
    const details = document.createElement("details"), summary = document.createElement("summary");
    summary.textContent = group.name; details.append(summary);
    for (const [field, value] of Object.entries(group.values)) {
      const row = document.createElement("div"); row.className = "permission-row";
      const label = document.createElement("span"); label.textContent = field;
      row.append(label);
      if (group.editable.includes(field)) {
        const input = document.createElement(field === "AllowPlaylists" ? "select" : "input");
        input.setAttribute("aria-label", group.name + " " + field);
        if (field === "AllowPlaylists") {
          for (const [label, v] of [[t("m0210"), "true"], [t("m0211"), "false"]]) {
            const option = document.createElement("option"); option.value = v; option.textContent = label; input.append(option);
          }
          input.value = String(value);
        } else {
          input.type = "number"; input.min = "0"; input.max = String(adminPermissions.limits[field]); input.step = "1"; input.value = String(value);
        }
        const confirm = libraryButton("m0214", async () => {
          const next = field === "AllowPlaylists" ? input.value === "true" : Number(input.value);
          if (field !== "AllowPlaylists" && (!/^\d+$/.test(input.value) || !Number.isSafeInteger(next) || next < 0 || next > adminPermissions.limits[field]))
            throw new Error(t("m0215"));
          if (value === next) return;
          pendingPermission = {guild: selected, epoch: generation, group: group.name, field, old_value: value, value: next};
          $("permission-confirm-text").textContent = group.name + "・" + field + "：" + permissionText(value) + " → " + permissionText(next);
          $("permission-confirm-dialog").showModal();
        });
        row.append(input, confirm);
      } else {
        const text = document.createElement("span"); text.textContent = permissionText(value); row.append(text);
      }
      details.append(row);
    }
    $("admin-permissions").append(details);
  }
  const history = document.createElement("ol"); history.className = "activity-list";
  for (const item of adminPermissions.activity) {
    const row = document.createElement("li"); row.textContent = item.detail; history.append(row);
  }
  $("admin-permissions").append(history);
}
$("permission-cancel").addEventListener("click", () => {
  pendingPermission = null; $("permission-confirm-dialog").close();
});
$("permission-confirm").addEventListener("click", () => libraryRun($("permission-confirm"), async () => {
  const value = pendingPermission;
  if (!value || !adminOwner || value.epoch !== generation || value.guild !== selected) {
    $("permission-confirm-dialog").close(); return;
  }
  const {guild, epoch, ...data} = value;
  const result = await api("/api/guilds/" + guild + "/admin/permissions", "PATCH", data);
  pendingPermission = null; $("permission-confirm-dialog").close();
  if (epoch !== generation || guild !== selected) return;
  adminPermissions = result; adminPermissionsRender(); notice(result.message);
}));

async function adminVoteSkipLoad() {
  if (!adminOwner || !selected) return;
  const guild = selected, epoch = generation;
  $("admin-vote-skip-enabled").disabled = true;
  $("admin-vote-skip-save").disabled = true;
  const value = await api("/api/guilds/" + guild + "/admin/vote-skip");
  if (epoch !== generation || guild !== selected || !adminOwner) return;
  $("admin-vote-skip-enabled").checked = value.enabled;
  $("admin-vote-skip-enabled").disabled = false;
  $("admin-vote-skip-save").disabled = false;
  $("admin-vote-skip-status").textContent = "";
}
$("admin-vote-skip-form").addEventListener("submit", event => {
  event.preventDefault();
  return libraryRun($("admin-vote-skip-save"), async () => {
    if (!adminOwner || !selected || $("admin-vote-skip-enabled").disabled) return;
    const guild = selected, epoch = generation;
    const value = await api("/api/guilds/" + guild + "/admin/vote-skip", "POST",
      {enabled:$("admin-vote-skip-enabled").checked});
    if (epoch !== generation || guild !== selected || !adminOwner) return;
    $("admin-vote-skip-enabled").checked = value.enabled;
    $("admin-vote-skip-status").textContent = t("vote_skip.saved");
  });
});
