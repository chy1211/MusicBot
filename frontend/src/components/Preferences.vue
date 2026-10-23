<template>
<div class="language-preference"><label for="dashboard-language" data-i18n="language">Language</label>
<select id="dashboard-language" aria-label="Language" data-i18n-aria-label="language">
<option value="en" data-i18n="language.en">English</option><option value="zh-TW" data-i18n="language.zh-TW">Traditional Chinese</option>
</select></div>
<svg class="glass-filter-defs" aria-hidden="true" width="0" height="0">
<defs><filter id="glass-edge" x="0" y="0" width="1" height="1" color-interpolation-filters="sRGB">
<femorphology in="SourceAlpha" operator="erode" radius="8" result="inside"></femorphology>
<fecomposite in="SourceAlpha" in2="inside" operator="xor" result="edge"></fecomposite>
<feturbulence type="fractalNoise" basefrequency=".025" numoctaves="1" seed="7" result="noise"></feturbulence>
<fedisplacementmap in="SourceGraphic" in2="noise" scale="5" xchannelselector="R" ychannelselector="G" result="bent"></fedisplacementmap>
<fecomposite in="bent" in2="edge" operator="in" result="rim"></fecomposite>
<fecomposite in="SourceGraphic" in2="edge" operator="out" result="center"></fecomposite>
<femerge><femergenode in="center"></femergenode><femergenode in="rim"></femergenode></femerge>
</filter></defs></svg>

</template>
