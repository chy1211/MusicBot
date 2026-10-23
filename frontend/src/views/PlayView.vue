<script setup lang="ts">
import NowPlaying from "../components/NowPlaying.vue"
</script>
<template>
    <div id="play-view">
<NowPlaying />
    <section class="card request" aria-labelledby="request-heading">
      <h2 id="request-heading"><span data-i18n="m0245">What would you like to hear next?</span></h2>
      <form id="play-form">
        <label class="sr-only" for="query"><span data-i18n="m0246">Song URL or search terms</span></label>
        <div class="input-row"><input id="query" type="text" maxlength="2000" placeholder="Paste a track / playlist URL or enter a song name" required data-i18n-placeholder="m0247">
          <button id="enqueue" class="primary" type="submit" disabled><span data-i18n="m0248">Search</span></button></div>
        <div class="request-mode"><label for="request-action"><span data-i18n="m0249">Add as</span></label><select id="request-action"><option value="play" data-i18n="m0090">Add to queue</option><option value="playnext" data-i18n="m0250">Play next (single track)</option></select></div>
      </form>
      <section id="preview-panel" hidden aria-label="Request preview" data-i18n-aria-label="m0251">
        <div class="section-top"><h3><span data-i18n="m0252">Review your selection</span></h3><button id="preview-close" class="subtle" type="button"><span data-i18n="m0253">Clear preview</span></button></div>
        <div id="preview-results"></div>
      </section>
    </section>
    <section class="card queue" aria-labelledby="queue-heading">
      <div class="section-top"><div><h2 id="queue-heading"><span data-i18n="m0254">Up next </span><span id="queue-count">0</span><span data-i18n="m0255"> tracks · </span><span id="queue-total"><span data-i18n="m0256">Total 0 hr 0 min</span></span></h2></div>
        <div class="queue-tools"><label for="queue-search"><span data-i18n="m0257">Search queue</span><input id="queue-search" type="search" maxlength="200" placeholder="Track or requester" data-i18n-placeholder="m0258"></label>
        <button id="shuffle" class="subtle" type="button" disabled><span data-i18n="m0259">⇄ Shuffle</span></button></div></div>
      <div class="queue-filters" role="group" aria-label="Filter requests" data-i18n-aria-label="m0260"><button id="queue-all" type="button" aria-pressed="true"><span data-i18n="m0261">All</span></button><button id="queue-mine" type="button" aria-pressed="false"><span data-i18n="m0170">My requests</span></button></div>
      <p id="queue-match-count" class="hint" role="status" aria-live="polite"></p>
      <p id="queue-timing-note" class="hint"></p>
      <p id="drag-help" class="sr-only"><span data-i18n="m0173">Drag ⋮⋮ to reorder; hold the handle on mobile. You can also use ↑ ↓. Press Esc to cancel.</span></p>
      <div class="queue-head" aria-hidden="true"><span>＃</span><span><span data-i18n="m0262">Track</span></span><span><span data-i18n="m0263">Duration</span></span></div>
      <ol id="queue" aria-describedby="drag-help"></ol>
      <section id="queue-recommendations" aria-labelledby="recommendation-heading" hidden>
        <h3 id="recommendation-heading"><span data-i18n="m0264">Recently played</span></h3><ol id="recommendation-list" class="history-list"></ol>
      </section>
      <p id="queue-empty" class="empty"><span data-i18n="m0265">The next song is up to you.</span><br><span><span data-i18n="m0266">Search above, review the preview and add it to the queue.</span></span></p>
    </section>
    <section class="card listeners" aria-labelledby="listeners-heading">
      <h2 id="listeners-heading"><span data-i18n="m0267">Who&#x27;s listening</span></h2>
      <p id="listeners-status" class="hint" role="status"><span data-i18n="m0178">The bot is not in a voice channel</span></p>
      <div id="listeners-list" class="listeners-list"></div>
    </section>
    <section class="card activity" aria-labelledby="activity-heading">
      <h2 id="activity-heading"><span data-i18n="m0268">Activity</span></h2><p id="activity-status" class="hint"><span data-i18n="m0181">No activity yet.</span></p>
      <ol id="activity-list" class="activity-list"></ol>
    </section>
    <section class="card history" aria-labelledby="history-heading">
      <div class="section-top"><div><h2 id="history-heading"><span data-i18n="m0264">Recently played</span></h2></div><button id="history-refresh" class="subtle" type="button" disabled><span data-i18n="m0269">Refresh</span></button></div>
      <p class="hint"><span data-i18n="m0270">The last 50 tracks played in this server.</span></p>
      <p id="history-status" class="hint" role="status"><span data-i18n="m0133">No listening history yet.</span></p>
      <ol id="history-list" class="history-list"></ol>
    </section>
    </div>

</template>
