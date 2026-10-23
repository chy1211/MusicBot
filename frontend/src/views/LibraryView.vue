<template>
<section id="library-panel" class="card" hidden aria-labelledby="library-heading">
<div class="section-top"><h2 id="library-heading"><span data-i18n="m0232">My playlists</span></h2><button id="library-refresh" type="button"><span data-i18n="m0269">Refresh</span></button></div>
<div class="library-workspace">
<aside class="library-sidebar" aria-label="Your playlists" data-i18n-aria-label="m0275">
<details class="library-create-menu"><summary><span data-i18n="m0276">New playlist</span></summary>
<form id="library-create"><label for="library-new-name"><span data-i18n="m0277">Playlist name</span></label><input id="library-new-name" maxlength="60" required><button id="library-create-button" type="submit"><span data-i18n="m0278">Create</span></button></form></details>
<div id="library-import-hint"></div><ul id="library-playlists" class="library-playlists"></ul>
</aside>
<section id="library-detail" class="library-detail" aria-labelledby="library-detail-heading">
<button id="library-back" type="button" class="subtle"><span data-i18n="m0279">Back to playlists</span></button>
<h3 id="library-detail-heading" tabindex="-1"></h3><p id="library-meta" class="hint"></p>
<div class="library-toolbar">
<button id="library-play-all" class="primary" type="button"><span data-i18n="m0280">Play all</span></button>
<button id="library-play-selected" type="button" disabled><span data-i18n="m0281">Add selected tracks</span></button>
<details id="library-actions" class="library-actions"><summary aria-label="More playlist actions" data-i18n-aria-label="m0282">⋯</summary>
<div class="library-menu"><button id="library-enqueue-all" type="button"><span data-i18n="m0283">Queue entire playlist</span></button>
<div id="library-rename-form"><label for="library-name"><span data-i18n="m0284">Name</span></label><input id="library-name" maxlength="60"><button id="library-rename" type="button"><span data-i18n="m0285">Rename</span></button></div>
<div id="library-sync-slot"></div><button id="library-delete" class="danger" type="button"><span data-i18n="m0286">Delete playlist</span></button></div>
</details></div>
<p id="library-empty" class="hint"><span data-i18n="m0287">This playlist is empty. Add songs from search results or the player.</span></p><ol id="library-list" class="library-list"></ol>
</section></div>
</section>

</template>
