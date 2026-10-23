"use strict";
function playlistCoverThumbnail(song) {
  const thumbnail = safeURL(song?.thumbnail || "");
  if (thumbnail) return thumbnail;
  const identity = songIdentity(song?.url || "");
  return identity.startsWith("youtube:") ? "https://i.ytimg.com/vi/" + identity.slice(8) + "/hqdefault.jpg" : "";
}
function playlistCoverSources(tracks) {
  const sources = [], seen = new Set();
  for (const song of Array.isArray(tracks) ? tracks : []) {
    const source = playlistCoverThumbnail(song);
    if (!source || seen.has(source)) continue;
    seen.add(source); sources.push(source);
    if (sources.length === 4) break;
  }
  return sources;
}
function playlistCoverElement(tracks, size = 48) {
  const sources = playlistCoverSources(tracks), cover = document.createElement("span");
  cover.className = "playlist-cover"; cover.setAttribute("aria-hidden", "true");
  cover.setAttribute("data-count", String(sources.length));
  Object.assign(cover.style, {display:"block",position:"relative",flex:"0 0 auto",width:size+"px",height:size+"px",
    aspectRatio:"1",overflow:"hidden",borderRadius:"10px",
    background:"radial-gradient(circle, #f2d98b 0 5%, #15151c 6% 10%, #55515b 11% 13%, #101016 14% 100%)"});
  const layouts = {1:[[0,0,100,100]],2:[[0,0,50,100],[50,0,50,100]],
    3:[[0,0,50,50],[50,0,50,50],[0,50,100,50]],
    4:[[0,0,50,50],[50,0,50,50],[0,50,50,50],[50,50,50,50]]}[sources.length] || [];
  let remaining=sources.length;
  sources.forEach((source,index)=>{
    const image=document.createElement("img"),[x,y,width,height]=layouts[index];
    image.className="playlist-cover-image";image.alt="";image.loading="lazy";image.referrerPolicy="no-referrer";
    Object.assign(image.style,{position:"absolute",left:x+"%",top:y+"%",width:width+"%",height:height+"%",objectFit:"cover"});
    image.onerror=()=>{image.hidden=true;image.style.display="none";remaining-=1;cover.classList.toggle("is-empty",remaining===0);};
    image.src=source; cover.append(image);
  });
  if(!sources.length) cover.classList.toggle("is-empty",true);
  return cover;
}
