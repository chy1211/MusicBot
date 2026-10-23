<template>
  <aside class="sidebar">
    <a class="brand" href="/" aria-label="Music dashboard home" data-i18n-aria-label="m0228"><span class="brand-icon" aria-hidden="true">♫</span><span class="brand-label"><span data-i18n="m0223">Music dashboard</span></span></a>
    <label for="guild"><span data-i18n="m0229">Switch server</span></label><select id="guild" aria-label="Switch server" data-i18n-aria-label="m0229"></select>
    <nav class="page-tabs" aria-label="Pages" data-i18n-aria-label="m0230"><button id="nav-play" type="button" aria-pressed="true"><span data-i18n="m0231">Play</span></button><button id="nav-library" type="button"><span data-i18n="m0232">My playlists</span></button><button id="nav-popular" type="button"><span data-i18n="m0233">Popular</span></button><button id="nav-admin" type="button" hidden><span data-i18n="m0234">Admin</span></button></nav>
    <button id="shortcuts-help" class="desktop-shortcuts subtle" type="button"><span data-i18n="m0235">Keyboard shortcuts ?</span></button>
    <button id="pwa-refresh" type="button" hidden><span data-i18n="m0236">Refresh to update</span></button>
    <span id="connection" class="badge" role="status"><span data-i18n="m0125">Connecting</span></span>
    <details id="auth" class="auth">
      <summary><span data-i18n="m0237">Connection settings</span></summary>
      <form id="auth-form"><label for="secret"><span data-i18n="m0238">Shared secret</span></label>
        <input id="secret" type="password" autocomplete="off" maxlength="1024">
        <button type="submit"><span data-i18n="m0239">Reconnect</span></button><button id="forget" type="button" class="subtle"><span data-i18n="m0240">Clear</span></button>
        <p class="hint"><span data-i18n="m0241">Kept only in this browser tab&#x27;s memory.</span></p>
      </form>
    </details>
  </aside>

</template>
