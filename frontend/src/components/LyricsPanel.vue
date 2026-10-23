<template>
<section id="lyrics-panel" class="lyrics-panel" aria-labelledby="lyrics-heading" hidden>
<div class="section-top"><h2 id="lyrics-heading"><span data-i18n="m0141">Lyrics</span></h2><button id="lyrics-close" type="button" aria-label="Close lyrics" data-i18n-aria-label="m0321"><span data-i18n="m0118">Off</span></button></div>
<p id="lyrics-status" class="hint" role="status" aria-live="polite"></p>
<button id="lyrics-retry" type="button" hidden><span data-i18n="m0609">Retry lyrics</span></button>
<div id="lyrics-timing-controls" class="lyrics-timing-controls" hidden>
<button id="lyrics-timing-toggle" type="button" aria-expanded="false" aria-controls="lyrics-timing-menu"><span data-i18n="m0611">Timing adjustments</span> <span aria-hidden="true">▾</span></button>
<div id="lyrics-timing-menu" class="lyrics-timing-menu" role="group" aria-label="Timing adjustments" data-i18n-aria-label="m0611" hidden>
<button id="lyrics-minus" type="button"><span data-i18n="m0322">−0.5 s</span></button><button id="lyrics-plus" type="button"><span data-i18n="m0323">+0.5 s</span></button>
<button id="lyrics-sync" type="button"><span data-i18n="m0142">Sync</span></button><button id="lyrics-reset" type="button"><span data-i18n="m0324">Reset</span></button>
<p id="lyrics-sync-prompt" class="hint" hidden></p></div></div>
<div id="lyrics-content" class="lyrics-content" tabindex="0" aria-label="Lyrics content" data-i18n-aria-label="m0325"></div>
<form id="lyrics-search-form" class="lyrics-search" hidden><label for="lyrics-query"><span data-i18n="m0326">Track and artist</span></label><input id="lyrics-query" maxlength="200"><button id="lyrics-search"><span data-i18n="m0327">Search lyrics</span></button></form>
</section>

</template>
