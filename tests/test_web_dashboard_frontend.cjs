"use strict";
// Frontend behavior tests in Node's VM. No browser, network, or new dependencies.
const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const code = fs.readFileSync(path.join(__dirname, "../musicbot/web/dashboard.js"), "utf8");

class Element {
  constructor(tag = "div") {
    this.tag = tag; this.children = []; this.listeners = {};
    this.attributes = {}; this.dataset = {}; this.value = "";
    this.textContent = ""; this.disabled = false; this.hidden = false;
    this.classes = new Set(); this.style = {}; this.animations = [];
    this.classList = {toggle: (name, on) => on ? this.classes.add(name) : this.classes.delete(name)};
  }
  append(...items) {
    this.children.push(...items);
    items.forEach((item) => { item.parent = this; });
    if (this.tag === "select" && !this.value && items.length) this.value = items[0].value;
  }
  replaceChildren() {
    this.children = [];
    if (this.tag === "select") this.value = "";
  }
  setAttribute(name, value) { this.attributes[name] = value; }
  getAttribute(name) { return this.attributes[name] || null; }
  removeAttribute(name) { delete this.attributes[name]; }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  setPointerCapture(id) { this.capture = id; }
  hasPointerCapture(id) { return this.capture === id; }
  releasePointerCapture() { this.capture = null; }
  closest() { return this.tag === "li" ? this : this.parent?.closest(); }
  getBoundingClientRect() {
    if (!this.layout) return {height: 110};
    const index = this.parent?.children.indexOf(this) || 0;
    const shift = parseFloat((this.style.transform || "").replace("translateY(", "")) || 0;
    return {height: 74, top: 200 + index * 74 + shift, bottom: 274 + index * 74 + shift};
  }
  animate(frames, options) { this.animations.push({frames, options}); }
  set src(value) { this.attributes.src = value; }
  get src() { return this.attributes.src; }
  set innerHTML(value) { throw new Error("Untrusted content must use textContent"); }
}
const flush = () => new Promise((resolve) => setImmediate(resolve));
const clone = (value) => JSON.parse(JSON.stringify(value));
function initial(id) {
  return {guild_id: String(id), status: "playing",
    current: {title: id === 1 ? "First" : "Second", duration: 180, thumbnail: ""},
    progress: 30, volume: 15, repeat: "off", revision: "revision-" + id,
    queue: [{title: "<img onerror=evil>", position: 1, duration: 60},
            {title: "Two", position: 2, duration: 120}]};
}
async function setup(options = {}) {
  const elements = new Map();
  const document = {activeElement: null, hidden: false, body: new Element("body"), listeners: {},
    addEventListener(name, fn) { this.listeners[name] = fn; },
    elementFromPoint() { return this.hit; },
    querySelector() { return new Element(); },
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, new Element(id === "guild" ? "select" : "div"));
      return elements.get(id);
    },
    createElement: (tag) => new Element(tag),
    querySelectorAll(selector) {
      const result = [];
      function walk(element) {
        if (element.tag === (selector.endsWith("input") ? "input" : "button")) result.push(element);
        element.children.forEach(walk);
      }
      walk(this.getElementById(selector.includes("preview") ? "preview-results" : "queue"));
      return result;
    }};
  const requests = [], timers = [], frames = [], scrolls = [], states = {1: initial(1), 2: initial(2)};
  const session = clone(options.session || {auth_mode: "owner", authenticated: true, user: null});
  let hook = options.hook || null;
  async function fetch(url, options) {
    requests.push({url, ...options, data: options.body ? JSON.parse(options.body) : undefined});
    if (hook) {
      const intercepted = hook(url, options);
      if (intercepted) return intercepted;
    }
    let body, status = 200;
    if (url === "/auth/session") body = clone(session);
    else if (url === "/auth/logout") { session.authenticated = false; session.user = null; body = {message: "signed out"}; }
    else if (url === "api/guilds") body = {guilds: [{id: "1", name: "First Guild"}, {id: "2", name: "Second Guild"}]};
    else {
      const match = url.match(/^api\/guilds\/(\d+)\/(.+)$/);
      const state = states[match[1]], action = match[2], data = options.body && JSON.parse(options.body);
      if (action === "state") body = clone(state);
      else if (action === "resolve") body = {results: [{title: "Selected", kind: "track",
        url: "https://example.test/selected", duration: 125, thumbnail: "", allowed: true, preview_id: "preview-one"}]};
      else {
        if (action === "pause") state.status = "paused";
        if (action === "resume") state.status = "playing";
        if (action === "volume") state.volume = data.volume;
        if (action === "repeat") state.repeat = data.mode;
        if (action === "queue/move") state.queue.splice(data.to - 1, 0, state.queue.splice(data.from - 1, 1)[0]);
        if (options.method === "DELETE") state.queue.splice(Number(action.split("/")[1]) - 1, 1);
        state.queue.forEach((song, i) => { song.position = i + 1; });
        state.revision += "x";
        body = {message: "done", state: clone(state)};
      }
    }
    return {ok: status === 200, status, json: async () => body};
  }
  const context = vm.createContext({document, fetch, URL, AbortController, window: {setTimeout: (...args) => timers.push(args), clearTimeout() {},
    requestAnimationFrame: (fn) => frames.push(fn), cancelAnimationFrame() {},
    matchMedia: () => ({matches: !!options.reducedMotion}),
    innerHeight: 900, scrollBy: (...args) => scrolls.push(args)}});
  vm.runInContext(code, context);
  await flush();
  return {document, elements, states, requests, context, timers, frames, scrolls, session,
    element: (id) => document.getElementById(id),
    run: (expression) => vm.runInContext(expression, context),
    hook: (value) => { hook = value; }};
}

test("renders current track, progress, queue and safe untrusted titles", async () => {
  const app = await setup();
  assert.equal(app.element("title").textContent, "First");
  assert.equal(app.element("progress").value, 30);
  assert.equal(app.element("queue-count").textContent, "2");
  assert.equal(app.element("queue").children[0].children[2].children[0].textContent, "<img onerror=evil>");
  assert.equal(app.element("enqueue").disabled, false);
  assert.ok(app.timers.some((timer) => timer[1] === 1000));
});

test("control handlers send correct methods, body, guild and headers", async () => {
  const app = await setup();
  await app.element("toggle").listeners.click();
  assert.equal(app.element("toggle").textContent.includes("播放"), true);
  app.element("volume").value = "65";
  await app.element("volume").listeners.change();
  app.element("repeat").value = "all";
  await app.element("repeat").listeners.change();
  app.element("query").value = "search words";
  await app.element("play-form").listeners.submit({preventDefault() {}});
  await app.element("preview-results").children[0].children[2].listeners.click();
  const mutations = app.requests.filter((r) => r.method === "POST");
  assert.deepEqual(mutations.map((r) => r.url), [
    "api/guilds/1/pause", "api/guilds/1/volume", "api/guilds/1/repeat", "api/guilds/1/resolve", "api/guilds/1/play"]);
  assert.equal(mutations[1].data.volume, 65);
  assert.equal(mutations[2].data.mode, "all");
  assert.equal(mutations[3].data.query, "search words");
  assert.equal(mutations[4].data.query, "https://example.test/selected");
  assert.equal(mutations[4].headers["X-MusicBot-Dashboard"], "1");
  assert.equal(app.element("query").value, "");
});

test("queue handlers retain observed revision and block invalid boundaries", async () => {
  const app = await setup();
  const actions = app.element("queue").children[0].children[4].children;
  assert.equal(actions[1].disabled, true);
  await actions[2].listeners.click();
  const move = app.requests.find((r) => r.url.endsWith("queue/move"));
  assert.deepEqual(move.data, {from: 1, to: 2, revision: "revision-1"});
  await app.element("queue").children[0].children[4].children[3].listeners.click();
  assert.equal(app.requests.find((r) => r.method === "DELETE").url, "api/guilds/1/queue/1");
  assert.equal(app.element("queue-count").textContent, "1");
});

test("failed focused volume control reconciles with actual server state", async () => {
  const app = await setup();
  app.document.activeElement = app.element("volume");
  app.element("volume").value = "99";
  app.hook((url) => url.endsWith("/volume")
    ? Promise.resolve({ok: false, status: 403, json: async () => ({error: "denied"})}) : null);
  await app.element("volume").listeners.change();
  assert.equal(app.element("volume").value, 15);
  assert.equal(app.element("notice").textContent, "denied");
  assert.equal(app.element("volume").disabled, false);
});

test("guild switching clears previous content and rejects stale response", async () => {
  const app = await setup();
  let release;
  app.hook((url) => url === "api/guilds/1/state"
    ? new Promise((resolve) => { release = resolve; }) : null);
  const old = app.run("refresh()");
  app.element("guild").value = "2";
  await app.element("guild").listeners.change();
  assert.equal(app.element("title").textContent, "Second");
  release({ok: true, status: 200, json: async () => initial(1)});
  await old;
  assert.equal(app.element("title").textContent, "Second");
  await app.element("skip").listeners.click();
  assert.equal(app.requests.find((r) => r.url.endsWith("/skip")).url, "api/guilds/2/skip");
});

test("failed guild switch clears old queue and disables controls", async () => {
  const app = await setup();
  app.hook((url) => url === "api/guilds/2/state" ? Promise.reject(new Error("offline")) : null);
  app.element("guild").value = "2";
  await app.element("guild").listeners.change();
  assert.notEqual(app.element("title").textContent, "First");
  assert.equal(app.element("queue").children.length, 0);
  assert.equal(app.element("toggle").disabled, true);
  assert.equal(app.element("enqueue").disabled, true);
});

test("secret stays in headers and memory; clearing removes authorization", async () => {
  const app = await setup();
  app.element("secret").value = "fake-fixture-secret";
  app.element("auth-form").listeners.submit({preventDefault() {}});
  await flush();
  assert.equal(app.requests.at(-1).headers.Authorization, "Bearer fake-fixture-secret");
  assert.ok(app.requests.every((r) => !r.url.includes("fake-fixture-secret")));
  app.element("forget").listeners.click();
  await flush();
  assert.equal(app.requests.at(-1).headers.Authorization, undefined);
  assert.equal(app.element("secret").value, "");
});

test("mutations block duplicate input and polling while in flight", async () => {
  const app = await setup();
  let release;
  app.hook((url) => url.endsWith("/pause") ? new Promise((resolve) => { release = resolve; }) : null);
  const operation = app.element("toggle").listeners.click();
  await flush();
  assert.equal(app.element("toggle").disabled, true);
  assert.equal(app.element("guild").disabled, true);
  const count = app.requests.length;
  await app.run("poll()");
  await app.run("act('skip')");
  assert.equal(app.requests.length, count);
  release({ok: true, status: 200, json: async () => ({message: "done", state: initial(1)})});
  await operation;
  assert.equal(app.element("toggle").disabled, false);
});

test("network errors preserve query and expose reconnect controls", async () => {
  const app = await setup();
  app.element("query").value = "keep this";
  app.hook((url) => url.endsWith("/resolve") ? Promise.reject(new Error("network lost")) : null);
  await app.element("play-form").listeners.submit({preventDefault() {}});
  assert.equal(app.element("query").value, "keep this");
  assert.equal(app.element("notice").textContent, "network lost");
  app.hook(() => Promise.resolve({ok: false, status: 401, json: async () => ({error: "key required"})}));
  await app.run("connect()");
  assert.equal(app.element("auth").open, true);
  assert.equal(app.element("toggle").disabled, true);
});

function pointer(type = "mouse", extra = {}) {
  return {button: 0, pointerId: 7, isPrimary: true, pointerType: type,
    clientX: 80, clientY: 220, preventDefault() {}, ...extra};
}
function handle(app, index = 0) { return app.element("queue").children[index].children[4].children[0]; }

test("desktop pointer drag sends move with the observed revision", async () => {
  const app = await setup(), grip = handle(app);
  app.document.hit = app.element("queue").children[1];
  grip.listeners.pointerdown(pointer());
  grip.listeners.pointermove(pointer("mouse", {clientY: 320}));
  assert.equal(app.run("drag.active"), true);
  await grip.listeners.pointerup(pointer());
  const move = app.requests.find((r) => r.url.endsWith("queue/move"));
  assert.deepEqual(move.data, {from: 1, to: 2, revision: "revision-1"});
  assert.equal(grip.hasPointerCapture(7), false);
});

test("touch drag requires long press and then uses the same move API", async () => {
  const app = await setup(), grip = handle(app);
  app.document.hit = app.element("queue").children[1];
  grip.listeners.pointerdown(pointer("touch"));
  assert.equal(app.run("drag.active"), false);
  const hold = app.timers.find((timer) => timer[1] === 420);
  hold[0]();
  grip.listeners.pointermove(pointer("touch", {clientY: 320}));
  await grip.listeners.pointerup(pointer("touch"));
  assert.deepEqual(app.requests.find((r) => r.url.endsWith("queue/move")).data,
    {from: 1, to: 2, revision: "revision-1"});
});

test("touch tap or movement before long press cancels without moving", async () => {
  const app = await setup(), grip = handle(app);
  grip.listeners.pointerdown(pointer("touch"));
  await grip.listeners.pointerup(pointer("touch"));
  grip.listeners.pointerdown(pointer("touch"));
  grip.listeners.pointermove(pointer("touch", {clientY: 300}));
  assert.equal(app.run("drag"), null);
  assert.equal(app.requests.some((r) => r.url.endsWith("queue/move")), false);
});

test("Escape, pointercancel, lost capture and same-position drop send no mutations", async () => {
  for (const reason of ["escape", "pointercancel", "lostpointercapture", "same"]) {
    const app = await setup(), grip = handle(app);
    app.document.hit = app.element("queue").children[0];
    grip.listeners.pointerdown(pointer());
    grip.listeners.pointermove(pointer("mouse", {clientY: 240}));
    if (reason === "escape") app.document.listeners.keydown({key: "Escape"});
    else if (reason === "same") await grip.listeners.pointerup(pointer());
    else grip.listeners[reason]();
    assert.equal(app.run("drag"), null);
    assert.equal(app.requests.some((r) => r.url.endsWith("queue/move")), false);
  }
});

test("changed queue revision cancels an active drag", async () => {
  const app = await setup(), grip = handle(app);
  grip.listeners.pointerdown(pointer());
  grip.listeners.pointermove(pointer("mouse", {clientY: 250}));
  app.states[1].revision = "updated-by-discord";
  await app.run("refresh()");
  assert.equal(app.run("drag"), null);
  assert.equal(app.element("notice").textContent.includes("取消拖曳"), true);
  await grip.listeners.pointerup(pointer());
  assert.equal(app.requests.some((r) => r.url.endsWith("queue/move")), false);
});

test("stale drag response 409 refreshes state and retains the error notice", async () => {
  const app = await setup(), grip = handle(app);
  app.document.hit = app.element("queue").children[1];
  app.hook((url) => url.endsWith("queue/move")
    ? Promise.resolve({ok: false, status: 409, json: async () => ({error: "stale queue"})}) : null);
  grip.listeners.pointerdown(pointer());
  grip.listeners.pointermove(pointer("mouse", {clientY: 320}));
  await grip.listeners.pointerup(pointer());
  assert.equal(app.element("notice").textContent, "stale queue");
  assert.equal(app.requests.at(-1).url, "api/guilds/1/state");
  assert.equal(handle(app).disabled, false);
});

test("lookup never plays until the selected result is explicitly confirmed", async () => {
  const app = await setup();
  app.element("query").value = "find this";
  await app.element("play-form").listeners.submit({preventDefault() {}});
  assert.equal(app.requests.some((r) => r.url.endsWith("/play")), false);
  assert.equal(app.element("preview-panel").hidden, false);
  assert.equal(app.element("preview-results").children[0].children[1].children[0].textContent, "Selected");
  await app.element("preview-results").children[0].children[2].listeners.click();
  assert.deepEqual(app.requests.find((r) => r.url.endsWith("/play")).data,
    {query: "https://example.test/selected", preview_id: "preview-one"});
  assert.equal(app.element("preview-panel").hidden, true);
});

test("denied results are visible with a disabled confirmation button", async () => {
  const app = await setup();
  app.hook((url) => url.endsWith("/resolve") ? Promise.resolve({ok: true, status: 200,
    json: async () => ({results: [{title: "Blocked", url: "https://example.test/blocked",
      allowed: false, reason: "blocked by policy", kind: "track"}]})}) : null);
  app.element("query").value = "blocked";
  await app.run("resolveQuery()");
  const card = app.element("preview-results").children[0];
  assert.equal(card.children[2].disabled, true);
  await card.children[2].listeners.click();
  assert.equal(app.requests.some((r) => r.url.endsWith("/play")), false);
});

test("slow resolve permits playback controls and prevents duplicate lookups", async () => {
  const app = await setup();
  let release;
  app.hook((url) => url.endsWith("/resolve") ? new Promise((resolve) => { release = resolve; }) : null);
  app.element("query").value = "song";
  const lookup = app.run("resolveQuery()");
  await flush();
  assert.equal(app.element("enqueue").disabled, true);
  assert.equal(app.element("toggle").disabled, false);
  await app.run("resolveQuery()");
  await app.element("toggle").listeners.click();
  assert.equal(app.requests.filter((r) => r.url.endsWith("/resolve")).length, 1);
  release({ok: true, status: 200, json: async () => ({results: []})});
  await lookup;
});

test("guild switching and clearing reject stale lookup responses", async () => {
  for (const action of ["switch", "clear"]) {
    const app = await setup();
    let release;
    app.hook((url) => url.endsWith("/resolve") ? new Promise((resolve) => { release = resolve; }) : null);
    app.element("query").value = "song";
    const lookup = app.run("resolveQuery()");
    await flush();
    if (action === "switch") {
      app.element("guild").value = "2"; await app.element("guild").listeners.change();
    } else app.element("preview-close").listeners.click();
    release({ok: true, status: 200, json: async () => ({results: [{title: "stale"}]})});
    await lookup;
    assert.equal(app.element("preview-panel").hidden, true);
    assert.equal(app.element("preview-results").children.length, 0);
  }
});

test("duplicate confirm clicks are blocked and failed replies retain the same token", async () => {
  const app = await setup();
  app.element("query").value = "song"; await app.run("resolveQuery()");
  const button = app.element("preview-results").children[0].children[2];
  let release;
  app.hook((url) => url.endsWith("/play") ? new Promise((resolve) => { release = resolve; }) : null);
  const first = button.listeners.click();
  await flush();
  await button.listeners.click();
  assert.equal(app.requests.filter((r) => r.url.endsWith("/play")).length, 1);
  release({ok: false, status: 502, json: async () => ({error: "reply lost"})});
  await first;
  assert.equal(app.element("preview-panel").hidden, false);
  assert.equal(button.disabled, false);
  app.hook(null);
  await button.listeners.click();
  const plays = app.requests.filter((r) => r.url.endsWith("/play"));
  assert.deepEqual(plays[0].data, plays[1].data);
});

test("edge dragging schedules scrolling and cancellation clears animation", async () => {
  const app = await setup(), grip = handle(app);
  grip.listeners.pointerdown(pointer());
  grip.listeners.pointermove(pointer("mouse", {clientY: 10}));
  app.frames.at(-1)();
  assert.deepEqual(app.scrolls.at(-1), [0, -10]);
  grip.listeners.pointercancel();
  assert.equal(app.run("drag"), null);
});

test("an old state poll cannot overwrite a completed mutation", async () => {
  const app = await setup();
  let release;
  app.hook((url) => url.endsWith("/state") ? new Promise((resolve) => { release = resolve; }) : null);
  const old = app.run("refresh()");
  await flush();
  app.hook(null);
  await app.element("toggle").listeners.click();
  assert.equal(app.element("toggle").textContent.includes("播放"), true);
  release({ok: true, status: 200, json: async () => initial(1)});
  await old;
  assert.equal(app.element("toggle").textContent.includes("播放"), true);
});


function discordSession(authenticated = true) {
  return {auth_mode: "discord", authenticated,
    user: authenticated ? {id: "123", name: "<img onerror=evil>", avatar: "https://cdn.discordapp.com/fake-avatar.png"} : null};
}
function errorResponse(status, error) {
  return Promise.resolve({ok: false, status, json: async () => ({error})});
}

test("logged-out Discord page reads no guild or song APIs, including subsequent polls", async () => {
  const app = await setup({session: discordSession(false)});
  assert.deepEqual(app.requests.map((request) => request.url), ["/auth/session"]);
  assert.equal(app.element("dashboard").hidden, true);
  assert.equal(app.element("login-screen").hidden, false);
  assert.equal(app.element("discord-login").hidden, false);
  assert.equal(app.element("auth").hidden, true);
  assert.equal(app.element("enqueue").disabled, true);
  await app.run("poll()"); await app.run("connect()"); await app.run("refresh()");
  assert.equal(app.requests.length, 1);
});

test("Discord session renders a safe profile and never sends shared-secret authorization", async () => {
  const app = await setup({session: discordSession()});
  assert.equal(app.requests[0].url, "/auth/session");
  assert.equal(app.requests[0].headers, undefined);
  assert.equal(app.requests[0].credentials, "same-origin");
  assert.equal(app.element("dashboard").hidden, false);
  assert.equal(app.element("login-screen").hidden, true);
  assert.equal(app.element("user-profile").hidden, false);
  assert.equal(app.element("user-name").textContent, "<img onerror=evil>");
  assert.equal(app.element("user-avatar").src, discordSession().user.avatar);
  assert.equal(app.element("auth").hidden, true);
  app.element("secret").value = "fake-fixture-secret";
  app.element("auth-form").listeners.submit({preventDefault() {}});
  await flush();
  assert.ok(app.requests.every((request) => request.headers?.Authorization === undefined));
  assert.ok(app.requests.filter((request) => request.url.startsWith("api/")).every(
    (request) => request.credentials === "same-origin"));
});

test("Discord API 401 erases songs, guilds, preview, profile and query before stopping polling", async () => {
  const app = await setup({session: discordSession()});
  app.element("query").value = "private song"; await app.run("resolveQuery()");
  app.hook((url) => url.endsWith("/state") ? errorResponse(401, "session expired") : null);
  await app.run("refresh()");
  assert.equal(app.element("dashboard").hidden, true);
  assert.equal(app.element("login-screen").hidden, false);
  assert.equal(app.element("login-status").textContent, "session expired");
  assert.equal(app.element("guild").children.length, 0);
  assert.equal(app.element("queue").children.length, 0);
  assert.equal(app.element("preview-results").children.length, 0);
  assert.equal(app.element("preview-panel").hidden, true);
  assert.equal(app.element("query").value, "");
  assert.equal(app.element("user-name").textContent, "");
  assert.equal(app.element("user-avatar").getAttribute("src"), null);
  assert.notEqual(app.element("title").textContent, "First");
  assert.notEqual(app.element("bar-title").textContent, "First");
  assert.equal(app.run("state"), null);
  assert.equal(app.run("selected"), "");
  const count = app.requests.length;
  await app.run("poll()"); await app.run("poll()");
  assert.equal(app.requests.length, count);
});

test("late state and lookup responses cannot restore content after session expiry", async () => {
  const app = await setup({session: discordSession()});
  let release;
  app.hook((url) => url.endsWith("/state") ? new Promise((resolve) => { release = resolve; }) : null);
  const stale = app.run("refresh()");
  await flush();
  app.hook((url) => url.endsWith("/resolve") ? errorResponse(401, "expired") : null);
  app.element("query").value = "song"; await app.run("resolveQuery()");
  release({ok: true, status: 200, json: async () => initial(1)});
  await stale;
  assert.equal(app.element("dashboard").hidden, true);
  assert.equal(app.run("state"), null);
  assert.equal(app.element("queue").children.length, 0);
  assert.equal(app.element("preview-results").children.length, 0);
});

test("mutation 401 stops reconciliation without exposing the old guild again", async () => {
  const app = await setup({session: discordSession()});
  app.hook((url) => url.endsWith("/skip") ? errorResponse(401, "expired") : null);
  await app.element("skip").listeners.click();
  assert.equal(app.requests.at(-1).url, "api/guilds/1/skip");
  assert.equal(app.element("dashboard").hidden, true);
  assert.equal(app.element("toggle").disabled, true);
});

test("permission 403 displays the bot reason while retaining the Discord session", async () => {
  const app = await setup({session: discordSession()});
  app.hook((url) => url.endsWith("/skip") ? errorResponse(403, "you must join the bot voice channel") : null);
  await app.element("skip").listeners.click();
  assert.equal(app.element("notice").textContent, "you must join the bot voice channel");
  assert.equal(app.element("dashboard").hidden, false);
  assert.equal(app.element("user-profile").hidden, false);
  assert.equal(app.run("authenticated"), true);
  assert.equal(app.element("toggle").disabled, false);
});

test("logout posts with the CSRF header, clears personal content and rejects a late lookup", async () => {
  const app = await setup({session: discordSession()});
  let release;
  app.hook((url) => url.endsWith("/resolve") ? new Promise((resolve) => { release = resolve; }) : null);
  app.element("query").value = "song";
  const lookup = app.run("resolveQuery()");
  await flush();
  await app.element("logout").listeners.click();
  const request = app.requests.at(-1);
  assert.equal(request.url, "/auth/logout");
  assert.equal(request.method, "POST");
  assert.equal(request.headers["X-MusicBot-Dashboard"], "1");
  assert.equal(request.credentials, "same-origin");
  assert.equal(request.headers.Authorization, undefined);
  assert.equal(app.element("user-name").textContent, "");
  assert.equal(app.element("guild").children.length, 0);
  assert.equal(app.element("queue").children.length, 0);
  release({ok: true, status: 200, json: async () => ({results: [{title: "late"}]})});
  await lookup;
  assert.equal(app.element("preview-results").children.length, 0);
  assert.equal(app.element("dashboard").hidden, true);
  const count = app.requests.length;
  await app.run("poll()");
  assert.equal(app.requests.length, count);
});

test("a rejected logout retains login and gives a retryable error", async () => {
  const app = await setup({session: discordSession()});
  app.hook((url) => url === "/auth/logout" ? errorResponse(502, "try logout again") : null);
  await app.element("logout").listeners.click();
  assert.equal(app.element("notice").textContent, "try logout again");
  assert.equal(app.element("dashboard").hidden, false);
  assert.equal(app.element("logout").disabled, false);
  assert.equal(app.run("authenticated"), true);
});

test("session bootstrap failure and malformed responses fail closed without API reads", async () => {
  for (const response of [errorResponse(503, "unavailable"),
      Promise.resolve({ok: true, status: 200, json: async () => ({})}),
      Promise.resolve({ok: true, status: 200, json: async () => ({auth_mode: "owner", authenticated: false})})]) {
    const app = await setup({hook: () => response});
    assert.deepEqual(app.requests.map((request) => request.url), ["/auth/session"]);
    assert.equal(app.element("dashboard").hidden, true);
    assert.equal(app.element("login-screen").hidden, false);
    assert.equal(app.run("authenticated"), false);
    await app.run("poll()");
    assert.equal(app.requests.length, 1);
  }
});

test("incomplete Discord identity is treated as logged out and unsafe avatar URLs are ignored", async () => {
  const incomplete = discordSession(); incomplete.user = null;
  const loggedOut = await setup({session: incomplete});
  assert.equal(loggedOut.requests.length, 1);
  assert.equal(loggedOut.element("dashboard").hidden, true);
  const unsafe = discordSession(); unsafe.user.avatar = "javascript:evil()";
  const loggedIn = await setup({session: unsafe});
  assert.equal(loggedIn.element("user-avatar").getAttribute("src"), null);
});

test("owner retains connection settings and uses no Discord profile", async () => {
  const app = await setup();
  assert.equal(app.element("auth").hidden, false);
  assert.equal(app.element("user-profile").hidden, true);
  assert.equal(app.element("owner-badge").hidden, false);
  const count = app.requests.length;
  await app.element("logout").listeners.click();
  assert.equal(app.requests.length, count);
});

test("initial HTML conceals the dashboard and provides a same-origin Discord login link", () => {
  const html = fs.readFileSync(path.join(__dirname, "../musicbot/web/index.html"), "utf8");
  assert.match(html, /<div id="dashboard" hidden>/);
  assert.match(html, /id="discord-login"[^>]*href="\/auth\/login"/);
  assert.match(html, /id="user-profile"[^>]*hidden/);
  assert.ok(html.indexOf('id="login-screen"') < html.indexOf('id="dashboard"'));
});


test("a non-JSON API 401 still clears the Discord session and stops polling", async () => {
  const app = await setup({session: discordSession()});
  app.hook((url) => url.endsWith("/state") ? Promise.resolve({ok: false, status: 401,
    json: async () => { throw new SyntaxError("HTML response"); }}) : null);
  await app.run("refresh()");
  assert.equal(app.element("dashboard").hidden, true);
  assert.equal(app.run("authenticated"), false);
  assert.equal(app.element("queue").children.length, 0);
  const count = app.requests.length;
  await app.run("poll()");
  assert.equal(app.requests.length, count);
});

test("resolve spinner disables only lookup and resets after a failed response", async () => {
  const app = await setup();
  let release;
  app.hook((url) => url.endsWith("/resolve") ? new Promise((resolve) => { release = resolve; }) : null);
  app.element("query").value = "spinner";
  const pending = app.run("resolveQuery()");
  await flush();
  assert.equal(app.element("enqueue").getAttribute("aria-busy"), "true");
  assert.equal(app.element("enqueue").classes.has("is-loading"), true);
  assert.equal(app.element("enqueue").disabled, true);
  assert.equal(app.element("toggle").disabled, false);
  release({ok: false, status: 504, json: async () => ({error: "逾時"})});
  await pending;
  assert.equal(app.element("enqueue").getAttribute("aria-busy"), "false");
  assert.equal(app.element("enqueue").classes.has("is-loading"), false);
  assert.equal(app.element("enqueue").disabled, false);
});

test("play spinner resets on client timeout and preserves its confirmation token", async () => {
  const app = await setup();
  app.element("query").value = "song"; await app.run("resolveQuery()");
  const button = app.element("preview-results").children[0].children[2];
  app.hook((url, options) => url.endsWith("/play") ? new Promise((_, reject) => {
    options.signal.addEventListener("abort", () => reject(Object.assign(new Error(), {name: "AbortError"})));
  }) : null);
  const pending = button.listeners.click();
  await flush();
  assert.equal(button.dataset.loading, "1");
  assert.equal(button.getAttribute("aria-busy"), "true");
  assert.equal(button.disabled, true);
  app.timers.filter((timer) => timer[1] === 30000).at(-1)[0]();
  await pending;
  assert.equal(button.dataset.loading, "0");
  assert.equal(button.disabled, false);
  assert.equal(app.element("preview-panel").hidden, false);
  assert.match(app.element("notice").textContent, /逾時/);
});

test("toast expires automatically and an old timer cannot erase a new error", async () => {
  const app = await setup();
  app.run('notice("成功")');
  const success = app.timers.at(-1);
  assert.equal(success[1], 4500);
  assert.equal(app.element("notice").classes.has("visible"), true);
  app.run('notice("拒絕", true)');
  const error = app.timers.at(-1);
  assert.equal(error[1], 10000);
  success[0]();
  assert.equal(app.element("notice").textContent, "拒絕");
  assert.equal(app.element("notice").classes.has("error"), true);
  error[0]();
  assert.equal(app.element("notice").textContent, "");
  assert.equal(app.element("notice").classes.has("visible"), false);
});

test("current source link only exposes HTTP links and requester display names", async () => {
  const app = await setup();
  app.states[1].current.requester = {name: "<script>點播者</script>", avatar: ""};
  app.states[1].queue[0].requester = {name: "好友", avatar: ""};
  app.states[1].current.url = "https://www.youtube.com/watch?v=abc";
  await app.run("refresh()");
  assert.equal(app.element("source-link").href, app.states[1].current.url);
  assert.equal(app.element("source-link").hidden, false);
  assert.match(app.element("source-link").textContent, /YouTube/);
  assert.equal(app.element("subtitle").textContent, "點播：<script>點播者</script>");
  assert.equal(app.element("queue").children[0].children[2].children[1].textContent, "點播：好友");
  for (const url of ["javascript:alert(1)", "file:///tmp/test", "https://u:p@example.test/song"]) {
    app.states[1].current.url = url;
    await app.run("refresh()");
    assert.equal(app.element("source-link").hidden, true);
  }
});

function playlistReply() {
  return {title: "Playlist", kind: "playlist", url: "https://example.test/list", allowed: true,
    count: 3, checked_count: 3, eligible_count: 2, preview_id: "playlist-token", entries: [
      {item_id: "1", title: "一", duration: 60, allowed: true},
      {item_id: "2", title: "二", duration: 600, allowed: false, reason: "超過歌長"},
      {item_id: "3", title: "三", duration: 60, allowed: true}]};
}
async function playlistApp() {
  const app = await setup();
  app.hook((url) => url.endsWith("/resolve") ? Promise.resolve({ok: true, status: 200,
    json: async () => ({results: [playlistReply()]})}) : null);
  app.element("query").value = "list"; await app.run("resolveQuery()");
  const card = app.element("preview-results").children[0], info = card.children[1];
  return {app, card, tools: info.children.at(-2), list: info.children.at(-1), button: card.children[2]};
}

test("playlist defaults to all eligible items and cannot select a blocked row", async () => {
  const {app, list, button} = await playlistApp();
  assert.equal(list.children.length, 3);
  assert.equal(list.children[0].children[0].children[0].checked, true);
  assert.equal(list.children[1].children[0].children[0].checked, false);
  assert.equal(list.children[1].children[0].children[0].disabled, true);
  assert.equal(button.textContent, "加入選取的 2 首");
  await button.listeners.click();
  assert.deepEqual(app.requests.find((request) => request.url.endsWith("/play")).data, {
    query: "https://example.test/list", preview_id: "playlist-token", selected_items: ["1", "3"]});
});

test("playlist select none, select all and individual selection update the count and payload", async () => {
  const {app, tools, list, button} = await playlistApp();
  tools.children[1].listeners.click();
  assert.equal(button.textContent, "加入選取的 0 首");
  assert.equal(button.disabled, true);
  await button.listeners.click();
  assert.equal(app.requests.some((request) => request.url.endsWith("/play")), false);
  tools.children[0].listeners.click();
  const first = list.children[0].children[0].children[0];
  first.checked = false; first.listeners.change();
  assert.equal(button.textContent, "加入選取的 1 首");
  await button.listeners.click();
  assert.deepEqual(app.requests.find((request) => request.url.endsWith("/play")).data.selected_items, ["3"]);
});

test("batch confirmation displays spinner, freezes selection and reports partial success toast", async () => {
  const {app, list, button} = await playlistApp();
  let release;
  app.hook((url) => url.endsWith("/play") ? new Promise((resolve) => { release = resolve; }) : null);
  const pending = button.listeners.click();
  await flush();
  assert.equal(button.getAttribute("aria-busy"), "true");
  assert.equal(list.children[0].children[0].children[0].disabled, true);
  assert.equal(button.disabled, true);
  release({ok: true, status: 200, json: async () => ({
    message: "已加入 1 首，略過 1 首。佇列額滿。", added: 1, skipped: 1, state: initial(1)})});
  await pending;
  assert.match(app.element("notice").textContent, /已加入 1 首/);
  assert.equal(app.element("notice").classes.has("visible"), true);
});

test("drag lifts the source, shifts neighbours, sends one move and animates rollback on 409", async () => {
  const app = await setup(), rows = app.element("queue").children, grip = handle(app);
  app.document.hit = rows[1];
  let release;
  app.hook((url) => url.endsWith("queue/move") ? new Promise((resolve) => { release = resolve; }) : null);
  grip.listeners.pointerdown(pointer());
  grip.listeners.pointermove(pointer("mouse", {clientY: 320}));
  assert.equal(rows[0].classes.has("dragging"), true);
  assert.match(rows[0].style.transform, /scale\(1.025\)/);
  assert.match(rows[1].style.transform, /translateY\(-110px\)/);
  const pending = grip.listeners.pointerup(pointer());
  await flush();
  assert.equal(rows[0].classes.has("settling"), true);
  assert.equal(app.requests.filter((request) => request.url.endsWith("queue/move")).length, 1);
  release({ok: false, status: 409, json: async () => ({error: "隊列已更新"})});
  await pending;
  assert.equal(rows[0].style.transform, "");
  assert.equal(rows[1].style.transform, "");
  assert.equal(app.run("dragVisual"), null);
  assert.equal(app.element("notice").textContent, "隊列已更新");
});

test("queue reorder uses FLIP frames and reduced motion skips transforms while retaining move", async () => {
  const app = await setup();
  for (const row of app.element("queue").children) row.layout = true;
  app.states[1].queue.reverse();
  app.states[1].queue.forEach((song, i) => { song.position = i + 1; });
  app.states[1].revision += "flip";
  // Newly created fake rows have no layout; use a deterministic position function.
  app.run('document.createElement = ((create) => (tag) => { const el = create(tag); el.layout = tag === "li"; return el; })(document.createElement)');
  await app.run("refresh()");
  assert.ok(app.element("queue").children.some((row) => row.animations.length > 0));
  const reduced = await setup({reducedMotion: true}), grip = handle(reduced);
  reduced.document.hit = reduced.element("queue").children[1];
  grip.listeners.pointerdown(pointer("touch"));
  reduced.timers.find((timer) => timer[1] === 420)[0]();
  grip.listeners.pointermove(pointer("touch", {clientY: 320}));
  assert.equal(reduced.element("queue").children[0].style.transform, undefined);
  await grip.listeners.pointerup(pointer("touch"));
  assert.equal(reduced.requests.filter((request) => request.url.endsWith("queue/move")).length, 1);
});

test("fixed accessible toast, safe source link and reduced motion CSS are present", () => {
  const html = fs.readFileSync(path.join(__dirname, "../musicbot/web/index.html"), "utf8");
  const css = fs.readFileSync(path.join(__dirname, "../musicbot/web/dashboard.css"), "utf8");
  assert.match(html, /id="notice"[^>]*role="status"[^>]*aria-live="polite"[^>]*aria-atomic="true"/);
  assert.match(html, /id="source-link"[^>]*target="_blank"[^>]*rel="noopener noreferrer"/);
  assert.match(css, /\.notice\{position:fixed/);
  assert.match(css, /prefers-reduced-motion:reduce/);
  assert.match(css, /\.is-loading::before\{display:none/);
  for (const slogan of ["讓音樂繼續陪你", "讓好歌", "接著發生。", "在 Discord 相聚，在這裡選歌。", "先看預覽，再加入佇列。搜尋結果可挑選一首。"])
    assert.ok(!html.includes(slogan) && !code.includes(slogan), slogan);
  assert.ok(!html.includes("sidebar-note"));
  assert.ok(html.includes("你的音樂空間") && html.includes("讓旋律接下去"));
});

test("drop displacement uses unequal row heights without changing the move payload", async () => {
  const app = await setup(), rows = app.element("queue").children, grip = handle(app);
  rows[0].offsetTop = 0; rows[0].offsetHeight = 120;
  rows[1].offsetTop = 120; rows[1].offsetHeight = 74;
  app.document.hit = rows[1];
  let release;
  app.hook((url) => url.endsWith("queue/move") ? new Promise((resolve) => { release = resolve; }) : null);
  grip.listeners.pointerdown(pointer());
  grip.listeners.pointermove(pointer("mouse", {clientY: 320}));
  const pending = grip.listeners.pointerup(pointer());
  await flush();
  assert.equal(rows[0].style.transform, "translateY(74px)");
  assert.equal(rows[1].style.transform, "translateY(-120px)");
  release({ok: true, status: 200, json: async () => ({message: "done", state: initial(1)})});
  await pending;
  assert.deepEqual(app.requests.find((request) => request.url.endsWith("queue/move")).data,
    {from: 1, to: 2, revision: "revision-1"});
});
