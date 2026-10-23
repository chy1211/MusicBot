<template>
<section id="admin-panel" class="card" hidden aria-labelledby="admin-heading">
<h2 id="admin-heading"><span data-i18n="m0234">Admin</span></h2>
<section aria-labelledby="maintenance-heading">
<div class="section-top"><h3 id="maintenance-heading"><span data-i18n="m0303">Maintenance</span></h3><button id="maintenance-refresh" type="button"><span data-i18n="m0269">Refresh</span></button></div>
<p id="maintenance-status" role="status" aria-live="polite"></p>
<dl id="maintenance-details" class="maintenance-details"></dl>
</section>
<form id="admin-notify-form" class="selection-tools" aria-describedby="admin-notify-help">
<label for="admin-notify-channel"><span data-i18n="notify.label">Fallback notification channel</span></label>
<select id="admin-notify-channel" aria-describedby="admin-notify-warning"><option value="" data-i18n="notify.default">Not specified (use defaults)</option></select>
<button id="admin-notify-save" type="submit"><span data-i18n="notify.save">Save notification channel</span></button>
<p id="admin-notify-help" class="hint"><span data-i18n="notify.help">Used only when no request channel is available. Binding and speaking permissions still apply.</span></p>
<p id="admin-notify-warning" class="maintenance-warning" role="status" hidden><span data-i18n="notify.warning">The configured channel is deleted, inaccessible, or excluded by channel bindings. Notifications will use the default fallback order.</span></p>
<p id="admin-notify-status" role="status" aria-live="polite"></p>
</form>
<form id="admin-lyrics-form" class="selection-tools"><label for="admin-lyrics-enabled"><span data-i18n="m0304">Server lyrics</span></label><select id="admin-lyrics-enabled"><option value="true" data-i18n="m0305">Allow (off by default for everyone)</option><option value="false" data-i18n="m0306">Disable</option></select><button id="admin-lyrics-save" type="submit"><span data-i18n="m0307">Save lyrics settings</span></button><p id="admin-lyrics-status" class="hint"></p></form>
<form id="empty-queue-form" class="selection-tools">
<label for="empty-queue-mode"><span data-i18n="m0308">When the queue is empty</span></label>
<select id="empty-queue-mode"><option value="autoplaylist" data-i18n="m0309">Autoplaylist</option><option value="radio" data-i18n="m0310">Radio</option><option value="off" data-i18n="m0311">Stop</option></select>
<label for="radio-min-seconds"><span data-i18n="m0312">Radio minimum duration (seconds)</span></label><input id="radio-min-seconds" type="number" min="0" max="31536000" step="1" value="0">
<label for="radio-max-seconds"><span data-i18n="m0313">Radio maximum duration (0 = unlimited)</span></label><input id="radio-max-seconds" type="number" min="0" max="31536000" step="1" value="0">
<button id="empty-queue-save" type="submit"><span data-i18n="m0314">Save</span></button>
<p id="radio-seeds" class="hint"></p>
<p id="empty-queue-status" role="status" aria-live="polite"></p>
</form><h3><span data-i18n="m0309">Autoplaylist</span></h3>
<form id="admin-apl-search" class="input-row"><label for="admin-apl-query"><span data-i18n="m0315">Search URLs</span></label><input id="admin-apl-query" type="search" maxlength="100"><button id="admin-apl-search-button" type="submit"><span data-i18n="m0316">Search</span></button></form>
<p id="admin-apl-count" role="status"></p><ol id="admin-apl-list" class="admin-apl-list"></ol>
<div class="selection-tools"><button id="admin-apl-prev" type="button"><span data-i18n="m0317">Previous</span></button><button id="admin-apl-next" type="button"><span data-i18n="m0318">Next</span></button></div>

<h3><span data-i18n="vote_skip.heading">Server permissions</span></h3>
<form id="admin-vote-skip-form" class="selection-tools">
<label for="admin-vote-skip-enabled"><span data-i18n="vote_skip.label">Vote to skip</span></label>
<input id="admin-vote-skip-enabled" type="checkbox" role="switch" checked disabled aria-describedby="admin-vote-skip-help">
<button id="admin-vote-skip-save" type="submit" disabled><span data-i18n="vote_skip.save">Save skip settings</span></button>
<p id="admin-vote-skip-help" class="hint"><span data-i18n="vote_skip.help">Applies to this server. When disabled, anyone with Skip permission can skip immediately.</span></p>
<p id="admin-vote-skip-status" role="status" aria-live="polite"></p>
</form>
<div id="admin-permissions"></div></section>
<dialog id="permission-confirm-dialog"><h2><span data-i18n="m0319">Confirm permission change</span></h2><p id="permission-confirm-text"></p><div class="selection-tools"><button id="permission-confirm" type="button"><span data-i18n="m0320">Confirm change</span></button><button id="permission-cancel" type="button"><span data-i18n="m0302">Cancel</span></button></div></dialog>

</template>
