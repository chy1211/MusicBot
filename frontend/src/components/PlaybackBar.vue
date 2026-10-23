<template>
<section id="playback-bar" class="playback-bar" aria-label="Playback controls" data-i18n-aria-label="m0328">
<div class="bar-track"><div class="art mini-art"><span aria-hidden="true">♫</span><img id="bar-cover" alt="" hidden></div>
<div class="bar-copy"><button id="bar-title" type="button" aria-expanded="false" aria-controls="song-choices" aria-haspopup="true"><span data-i18n="m0110">Nothing playing</span></button><small id="bar-status"><span data-i18n="m0113">Pick a song</span></small>
<div id="song-choices" class="song-choices" role="group" aria-label="Open track" hidden data-i18n-aria-label="m0329">
<a id="source-link" target="_blank" rel="noopener noreferrer"><span data-i18n="m0106">Open on YouTube</span></a>
<a id="song-spotify" target="_blank" rel="noopener noreferrer"><span data-i18n="m0330">Open on Spotify</span></a></div></div>
<button id="favorite" class="player-control" type="button" aria-label="Save this track" aria-pressed="false" data-i18n-aria-label="m0201">♡</button></div>
<div class="bar-center"><div id="player-transport" class="transport">
<button id="toggle" class="primary player-control" aria-label="Play or pause" disabled data-i18n-aria-label="m0331"><span data-i18n="m0109">Resume</span></button><button id="skip" class="player-control" aria-label="Skip the current track" disabled data-i18n-aria-label="m0332"><span data-i18n="m0333">Skip</span></button>
<button id="repeat" class="repeat-control player-control" aria-label="Repeat: off" aria-pressed="false" disabled data-i18n-aria-label="m0334"><span data-i18n="m0114">Repeat</span></button></div>
<div class="progress-row"><span id="elapsed">0:00</span><input id="progress" type="range" min="0" max="1" step="1" value="0" aria-label="Player seek position" disabled data-i18n-aria-label="m0335"><span id="duration">0:00</span></div></div>
<p class="sr-only seek-hint"><span data-i18n="m0336">Drag or use the arrow keys. Release to seek.</span></p><div class="bar-right"><button id="lyrics-toggle" class="player-control" type="button" aria-expanded="false" aria-controls="lyrics-panel" disabled><span data-i18n="m0141">Lyrics</span></button>
<div class="volume-row"><label for="volume" class="sr-only"><span data-i18n="m0337">Volume</span></label><input id="volume" type="range" min="1" max="100" value="15" aria-label="Volume" disabled data-i18n-aria-label="m0337"><output id="volume-label" for="volume">15%</output></div></div>
</section>

</template>
