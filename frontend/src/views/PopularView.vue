<template>
<section id="popular-panel" class="card" hidden aria-labelledby="popular-heading">
<div class="section-top"><h2 id="popular-heading"><span data-i18n="m0233">Popular</span></h2><button id="popular-refresh" type="button"><span data-i18n="m0269">Refresh</span></button></div>
<div class="request-mode"><label for="popular-period"><span data-i18n="m0271">Period</span></label><select id="popular-period"><option value="7" data-i18n="m0272">Last 7 days</option><option value="30" data-i18n="m0273">Last 30 days</option><option value="all" data-i18n="m0274">All (within 180 days)</option></select></div>
<p id="popular-status" class="hint" role="status" aria-live="polite"><span data-i18n="m0216">Select a server to view popular requests.</span></p><ol id="popular-list" class="history-list popular-list"></ol>
</section>

</template>
