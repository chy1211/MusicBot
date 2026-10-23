"use strict";
const session = {auth_mode: "discord", authenticated: true, user: {id: "123", name: "<img onerror=evil>", avatar: ""}};
function snapshot(guild = "1") {
  return {guild_id: guild, status: "playing", current: {title: "Private current track", url: "https://example.test/current",
    duration: 180, requester: {name: "Requester"}, seekable: true, track_token: "track-" + guild},
    queue: [1, 2, 3, 4].map(i => ({title: "Private queue " + i, url: "https://example.test/" + i, duration: 120, position: i})),
    progress: 30, volume: 35, repeat: "off", revision: "revision-" + guild,
    capabilities: {pause: true, resume: true, skip: true, seek: true}, lyrics_available: true,
    listeners: {connected: true, channel: "Fixture Voice", members: []}, activity: {activity: []}};
}
function json(route, body, status = 200) { return route.fulfill({status, contentType: "application/json", body: JSON.stringify(body)}); }
async function setup(page, value = session, status = 200) {
  await page.addInitScript(() => {
    const native = window.fetch.bind(window);
    window.__authAudit = [];
    window.EventSource = class { addEventListener() {} close() {} };
    window.fetch = (input, init = {}) => {
      const headers = new Headers(init.headers || {});
      window.__authAudit.push({url: String(input), credentials: init.credentials,
        authorization: headers.get("Authorization"), dashboardHeader: headers.get("X-MusicBot-Dashboard")});
      return native(input, init);
    };
  });
  await page.route("**/api/**", route => json(route, {}));
  await page.route("**/auth/session", route => json(route, value, status));
  await page.route("**/auth/logout", route => json(route, {message: "logged out"}));
  await page.route("**/api/library", route => json(route, {revision: "library", owner: false,
    playlists: [{id: "favorites", name: "Favorites", tracks: []}]}));
  await page.route("**/api/guilds", route => json(route, {guilds: [{id: "1", name: "Fixture One"}, {id: "2", name: "Fixture Two"}]}));
  await page.route("**/api/guilds/*/state", route => json(route, snapshot(new URL(route.request().url()).pathname.split("/")[3])));
  await page.route("**/api/guilds/*/history", route => json(route, {history: []}));
  await page.route("**/api/guilds/*/popular?*", route => json(route, {tracks: []}));
  await page.route("**/api/guilds/*/resolve", route => json(route, {results: [{title: "Preview track", url: "https://example.test/preview",
    duration: 120, kind: "track", allowed: true, preview_id: "preview-token"}]}));
}
module.exports = {session, snapshot, json, setup};
