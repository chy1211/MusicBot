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
  replaceChildren(...items) {
    this.children = [];
    if (this.tag === "select") this.value = "";
    this.append(...items);
  }
  setAttribute(name, value) { this.attributes[name] = value; }
  getAttribute(name) { return this.attributes[name] || null; }
  removeAttribute(name) { delete this.attributes[name]; }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  setPointerCapture(id) { this.capture = id; }
  hasPointerCapture(id) { return this.capture === id; }
  releasePointerCapture() { this.capture = null; }
  closest(selector = "") {
    if (selector.includes("input, select")) {
      if (["input", "select", "textarea"].includes(this.tag) || this.isContentEditable ||
          ["textbox", "combobox", "menu", "menuitem"].includes(this.attributes.role)) return this;
      return this.parent?.closest(selector);
    }
    if (selector === "button, a, summary") return ["button", "a", "summary"].includes(this.tag) ? this : this.parent?.closest(selector);
    return this.tag === "li" ? this : this.parent?.closest(selector);
  }
  getBoundingClientRect() {
    if (!this.layout) return {height: 110};
    const index = this.parent?.children.indexOf(this) || 0;
    const shift = parseFloat((this.style.transform || "").replace("translateY(", "")) || 0;
    return {height: 74, top: 200 + index * 74 + shift, bottom: 274 + index * 74 + shift};
  }
  click() { if (!this.disabled) return this.listeners.click?.(); }
  showModal() { this.open = true; }
  close() { this.open = false; }
  scrollIntoView(options) { this.scrolled = options; }
  focus() { this.focused = true; }
  animate(frames, options) { this.animations.push({frames, options}); }
  set src(value) { this.attributes.src = value; }
  get src() { return this.attributes.src; }
  set innerHTML(value) { throw new Error("Untrusted content must use textContent"); }
}
const flush = () => new Promise((resolve) => setImmediate(resolve));
const clone = (value) => JSON.parse(JSON.stringify(value));
function initial(id) {
  return {guild_id: String(id), status: "playing",
    capabilities: {pause: true, resume: true, skip: true, seek: true},
    current: {title: id === 1 ? "First" : "Second", duration: 180, seekable: true, thumbnail: ""},
    progress: 30, volume: 15, repeat: "off", revision: "revision-" + id,
    queue: [{title: "<img onerror=evil>", position: 1, duration: 60},
            {title: "Two", position: 2, duration: 120}]};
}
async function setup(options = {}) {
  const elements = new Map();
  const document = {activeElement: null, hidden: false, body: new Element("body"), listeners: {},
    addEventListener(name, fn) { this.listeners[name] = fn; },
    elementFromPoint() { return this.hit; },
    querySelector(selector) {
      if (selector.startsWith("dialog[open]")) return [...elements.entries()]
        .find(([id, el]) => id.endsWith("-dialog") && el.open)?.[1] || null;
      return new Element();
    },
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
      walk(this.getElementById(selector.includes("preview") ? "preview-results" : selector.includes("history") ? "history-list" : selector.includes("recommendation") ? "recommendation-list" : "queue"));
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
    else if (url.endsWith("/admin/empty-queue")) body = {empty_queue:"autoplaylist",radio_min_seconds:0,radio_max_seconds:0};
    else if (url.endsWith("/admin/maintenance")) body = {cookie:{status:"unused"},host_status:{status:"missing"},viewers:1};
    else if (url === "api/guilds") body = {guilds: [{id: "1", name: "First Guild"}, {id: "2", name: "Second Guild"}]};
    else {
      const match = url.match(/^api\/guilds\/(\d+)\/(.+)$/);
      const state = states[match[1]], action = match[2], data = options.body && JSON.parse(options.body);
      if (action === "state") body = clone(state);
      else if (action === "history") body = {history: []};
      else if (action === "spotify") body = {url: "https://open.spotify.com/track/Fake0001", mode: "track"};
      else if (action.startsWith("lyrics")) body = {status: "not_found", title: state.current?.title || "", lines: []};
      else if (action === "resolve") body = {results: [{title: "Selected", kind: "track",
        url: "https://example.test/selected", duration: 125, thumbnail: "", allowed: true, preview_id: "preview-one"}]};
      else {
        if (action === "pause") state.status = "paused";
        if (action === "resume") state.status = "playing";
        if (action === "volume") state.volume = data.volume;
        if (action === "seek") state.progress = data.position;
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
  const streams = [];
  class FakeEventSource {
    constructor(url) { this.url = url; this.listeners = {}; this.closed = false; streams.push(this); }
    addEventListener(name, handler) { this.listeners[name] = handler; }
    close() { this.closed = true; }
    emit(name, data) { return this.listeners[name]?.({data: JSON.stringify(data)}); }
  }
  const context = vm.createContext({document, fetch, URL, AbortController,
    EventSource: options.events ? FakeEventSource : undefined, window: {setTimeout: (...args) => timers.push(args), clearTimeout() {},
    requestAnimationFrame: (fn) => frames.push(fn), cancelAnimationFrame() {},
    matchMedia: (query) => ({matches: query.includes("reduced-motion") ? !!options.reducedMotion : !options.mobile}),
    innerHeight: 900, scrollBy: (...args) => scrolls.push(args)}});
  vm.runInContext(code, context);
  if (options.round7) for (const name of ["library.js", "admin.js", "permissions.js"])
    vm.runInContext(fs.readFileSync(path.join(__dirname, "../musicbot/web", name), "utf8"), context);
  await flush();
  return {document, elements, states, requests, context, timers, frames, scrolls, session, streams,
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
  assert.equal(app.element("toggle").textContent.includes("繼續"), true);
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
  assert.equal(app.element("toggle").textContent.includes("繼續"), true);
  release({ok: true, status: 200, json: async () => initial(1)});
  await old;
  assert.equal(app.element("toggle").textContent.includes("繼續"), true);
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
      {item_id: "1", url: "https://example.test/batch/1", title: "一", duration: 60, allowed: true},
      {item_id: "2", url: "https://example.test/batch/2", title: "二", duration: 600, allowed: false, reason: "超過歌長"},
      {item_id: "3", url: "https://example.test/batch/3", title: "三", duration: 60, allowed: true}]};
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
  assert.equal(button.textContent, "加入佇列（2 首）");
  await button.listeners.click();
  assert.deepEqual(app.requests.find((request) => request.url.endsWith("/play")).data, {
    query: "https://example.test/list", preview_id: "playlist-token", selected_items: ["1", "3"]});
});

test("playlist select none, select all and individual selection update the count and payload", async () => {
  const {app, tools, list, button} = await playlistApp();
  tools.children[1].listeners.click();
  assert.equal(button.textContent, "加入佇列（0 首）");
  assert.equal(button.disabled, true);
  await button.listeners.click();
  assert.equal(app.requests.some((request) => request.url.endsWith("/play")), false);
  tools.children[0].listeners.click();
  const first = list.children[0].children[0].children[0];
  first.checked = false; first.listeners.change();
  assert.equal(button.textContent, "加入佇列（1 首）");
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
  for (const slogan of ["你的音樂空間", "此刻，聽點喜歡的", "私人音樂室", "讓旋律接下去", "再聽一次，也很好", "跟著旋律，讀一句"])
    assert.ok(!html.includes(slogan) && !code.includes(slogan), slogan);
  assert.ok(!html.includes("owner-badge") && !code.includes("owner-badge"));
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


test("both seek sliders preview a drag across polling and post only on release", async () => {
  for (const id of ["progress", "hero-progress"]) {
    const app = await setup(), slider = app.element(id);
    slider.listeners.pointerdown(pointer());
    slider.value = "105"; slider.listeners.input();
    await slider.listeners.change();
    app.states[1].progress = 31;
    await app.run("refresh()");
    assert.equal(app.element("progress").value, 105);
    assert.equal(app.element("hero-progress").value, 105);
    assert.equal(app.element("elapsed").textContent, "1:45");
    assert.equal(app.element("hero-elapsed").textContent, "1:45");
    assert.equal(app.requests.filter((request) => request.url.endsWith("/seek")).length, 0);
    await app.document.listeners.pointerup(pointer());
    await slider.listeners.change();
    assert.deepEqual(app.requests.filter((request) => request.url.endsWith("/seek")).map((request) => request.data),
      [{position: 105}]);
    assert.equal(app.element("progress").value, 105);
  }
});

test("touch seek and keyboard repeated arrows commit once at the end of interaction", async () => {
  const app = await setup(), slider = app.element("progress");
  slider.listeners.pointerdown(pointer("touch"));
  slider.value = "55"; slider.listeners.input();
  await app.document.listeners.pointerup(pointer("touch"));
  assert.deepEqual(app.requests.filter((request) => request.url.endsWith("/seek")).map((request) => request.data),
    [{position: 55}]);
  slider.listeners.keydown({key: "ArrowRight"});
  slider.value = "56"; slider.listeners.input(); await slider.listeners.change();
  slider.listeners.keydown({key: "ArrowRight", repeat: true});
  slider.value = "57"; slider.listeners.input(); await slider.listeners.change();
  assert.equal(app.requests.filter((request) => request.url.endsWith("/seek")).length, 1);
  await slider.listeners.keyup({key: "ArrowRight"});
  await slider.listeners.keyup({key: "ArrowRight"});
  assert.deepEqual(app.requests.filter((request) => request.url.endsWith("/seek")).map((request) => request.data),
    [{position: 55}, {position: 57}]);
});

test("assistive input/change commits once and cancelled seek restores actual time", async () => {
  const app = await setup(), slider = app.element("hero-progress");
  slider.value = "75"; slider.listeners.input(); await slider.listeners.change();
  assert.deepEqual(app.requests.find((request) => request.url.endsWith("/seek")).data, {position: 75});
  slider.listeners.pointerdown(pointer("touch"));
  slider.value = "95"; slider.listeners.input(); app.document.listeners.pointercancel(pointer("touch"));
  assert.equal(slider.value, 75);
  assert.equal(app.run("seekDrag"), null);
  slider.listeners.keydown({key: "ArrowLeft"});
  slider.value = "50"; slider.listeners.input(); slider.listeners.keydown({key: "Escape"});
  await slider.listeners.keyup({key: "ArrowLeft"});
  assert.equal(app.requests.filter((request) => request.url.endsWith("/seek")).length, 1);
});

test("track and guild changes cancel seek so release cannot target a new song", async () => {
  const app = await setup(), slider = app.element("progress");
  slider.listeners.pointerdown(pointer()); slider.value = "95"; slider.listeners.input();
  app.states[1].current.title = "New track"; app.states[1].progress = 0;
  await app.run("refresh()");
  await app.document.listeners.pointerup(pointer());
  assert.equal(slider.value, 0);
  assert.equal(app.requests.some((request) => request.url.endsWith("/seek")), false);
  slider.listeners.pointerdown(pointer()); slider.value = "45"; slider.listeners.input();
  app.element("guild").value = "2"; await app.element("guild").listeners.change();
  await app.document.listeners.pointerup(pointer());
  assert.equal(slider.value, 30);
  assert.equal(app.requests.some((request) => request.url.endsWith("/seek")), false);
});

test("live, empty and disconnected players disable seek and backend rejection reconciles", async () => {
  const app = await setup();
  app.states[1].current.seekable = false; await app.run("refresh()");
  assert.equal(app.element("progress").disabled, true);
  app.states[1].current.seekable = true;
  app.states[1].current.duration = 0; await app.run("refresh()");
  assert.equal(app.element("progress").disabled, true);
  assert.equal(app.element("hero-progress").disabled, true);
  app.element("progress").listeners.pointerdown(pointer());
  assert.equal(app.run("seekDrag"), null);
  app.states[1].current.duration = 180; await app.run("refresh()");
  app.hook((url) => url.endsWith("/seek") ? errorResponse(403, "請加入機器人所在的語音頻道。") : null);
  const slider = app.element("progress");
  slider.listeners.pointerdown(pointer()); slider.value = "95"; slider.listeners.input();
  await app.document.listeners.pointerup(pointer());
  assert.equal(slider.value, 30);
  assert.match(app.element("notice").textContent, /語音頻道/);
  app.states[1].current = null; await app.run("refresh()");
  assert.equal(app.element("progress").disabled, true);
  assert.equal(app.element("lyrics-toggle").disabled, true);
});

test("single preview has separate playnext confirmation using the same scoped token", async () => {
  const app = await setup();
  app.element("query").value = "song"; await app.run("resolveQuery()");
  const card = app.element("preview-results").children[0];
  assert.equal(card.children[2].textContent, "加入佇列");
  assert.equal(card.children[3].textContent, "下一首播放");
  await card.children[3].listeners.click();
  assert.deepEqual(app.requests.find((request) => request.url.endsWith("/playnext")).data,
    {query: "https://example.test/selected", preview_id: "preview-one"});
  assert.equal(app.requests.some((request) => request.url.endsWith("/play")), false);
});

test("playnext-only users can query with playnext permission and receive actual command denial", async () => {
  const app = await setup();
  app.element("request-action").value = "playnext";
  app.element("query").value = "song"; await app.run("resolveQuery()");
  assert.equal(app.requests.find((request) => request.url.endsWith("/resolve")).data.action, "playnext");
  const card = app.element("preview-results").children[0];
  assert.equal(card.children[2].textContent, "下一首播放");
  assert.equal(card.children[3].textContent, "加入佇列");
  app.hook((url) => url.endsWith("/play") ? errorResponse(403, "你沒有使用 play 指令的權限。") : null);
  await card.children[3].listeners.click();
  assert.match(app.element("notice").textContent, /play/);
  assert.equal(app.element("preview-panel").hidden, false);
  await card.children[2].listeners.click();
  assert.equal(app.requests.filter((request) => request.url.endsWith("/playnext")).length, 1);
});

test("playlist preview retains ordered selection and offers no batch playnext control", async () => {
  const {card, button} = await playlistApp();
  assert.equal(card.children.length, 3);
  assert.match(card.children[1].children.at(-3).textContent, /下一首播放目前只提供單曲/);
  assert.match(button.textContent, /加入佇列/);
});

function historyReply(count = 1) {
  return {history: Array.from({length: count}, (_, i) => ({title: i ? "Track " + i : "<script>history</script>",
    duration: 125, thumbnail: "https://example.test/cover", url: "https://example.test/replay-" + i,
    requester: {name: i ? "好友" : "<img>朋友", avatar: "https://example.test/avatar"},
    played_at: Math.floor(Date.now() / 1000) - 180})), source: "dashboard", resets_on_restart: true};
}
test("history renders at most fifty safe songs, requesters, times and source links", async () => {
  const app = await setup();
  app.hook((url) => url.endsWith("/history") ? Promise.resolve({ok: true, status: 200, json: async () => historyReply(53)}) : null);
  await app.run("refreshHistory()");
  const rows = app.element("history-list").children;
  assert.equal(rows.length, 50);
  assert.equal(rows[0].children[1].children[0].textContent, "<script>history</script>");
  assert.match(rows[0].children[1].children[1].textContent, /點播：<img>朋友/);
  assert.match(rows[0].children[1].children[1].textContent, /3 分鐘前/);
  const link = rows[0].children[2].children[1];
  assert.equal(link.href, "https://example.test/replay-0");
  assert.equal(link.rel, "noopener noreferrer");
  assert.equal(app.run("playedTime(null)"), "播放時間未知");
  assert.match(app.run("playedTime(1)"), /08:00/);
});

test("history replay only opens a play-permission preview until separately confirmed", async () => {
  const app = await setup();
  app.hook((url) => url.endsWith("/history") ? Promise.resolve({ok: true, status: 200, json: async () => historyReply()}) : null);
  await app.run("refreshHistory()");
  await app.element("history-list").children[0].children[2].children[0].listeners.click();
  const resolve = app.requests.find((request) => request.url.endsWith("/resolve"));
  assert.deepEqual(resolve.data, {query: "https://example.test/replay-0", action: "play"});
  assert.equal(app.requests.some((request) => request.url.endsWith("/play")), false);
  assert.equal(app.element("preview-panel").hidden, false);
});

test("history failures are isolated and late guild response cannot restore old records", async () => {
  const app = await setup();
  app.hook((url) => url.endsWith("/history") ? errorResponse(403, "你不是這個伺服器的成員。") : null);
  await app.run("refreshHistory()");
  assert.match(app.element("history-status").textContent, /成員/);
  assert.equal(app.element("toggle").disabled, false);
  let release;
  app.hook((url) => url === "api/guilds/1/history" ? new Promise((resolve) => { release = resolve; }) : null);
  const pending = app.run("refreshHistory()");
  app.element("guild").value = "2"; await app.element("guild").listeners.change();
  release({ok: true, status: 200, json: async () => historyReply()}); await pending;
  assert.equal(app.element("history-list").children.length, 0);
  assert.equal(app.element("title").textContent, "Second");
});

function lyricsResponse(body) { return Promise.resolve({ok: true, status: 200, json: async () => body}); }
const syncedLyrics = {status: "synced", title: "First", artist: "Artist", track_key: "first",
  lines: [{time: 0, text: "前奏"}, {time: 20, text: "<script>第一句</script>"}, {time: 45, text: "下一句"}]};
test("synced lyrics highlight and scroll the current line as playback advances", async () => {
  const app = await setup();
  app.hook((url) => url.endsWith("/lyrics") ? lyricsResponse(syncedLyrics) : null);
  await app.element("lyrics-toggle").listeners.click();
  assert.equal(app.element("lyrics-panel").hidden, false);
  assert.equal(app.element("lyrics-toggle").getAttribute("aria-expanded"), "true");
  const rows = app.element("lyrics-content").children;
  assert.equal(rows[1].textContent, "<script>第一句</script>");
  assert.equal(rows[1].getAttribute("aria-current"), "true");
  assert.equal(rows[1].scrolled.behavior, "smooth");
  app.states[1].progress = 50; await app.run("refresh()");
  assert.equal(rows[1].getAttribute("aria-current"), null);
  assert.equal(rows[2].getAttribute("aria-current"), "true");
});

test("lyrics are not fetched every poll or on reopen and reduced motion scrolls instantly", async () => {
  const app = await setup({reducedMotion: true});
  app.hook((url) => url.endsWith("/lyrics") ? lyricsResponse(syncedLyrics) : null);
  await app.element("lyrics-toggle").listeners.click();
  await app.run("refresh()"); await app.run("refresh()");
  app.element("lyrics-close").listeners.click();
  await app.element("lyrics-toggle").listeners.click();
  assert.equal(app.requests.filter((request) => request.url.endsWith("/lyrics")).length, 1);
  assert.equal(app.element("lyrics-content").children[1].scrolled.behavior, "auto");
});

test("plain lyrics render as safe text and missing lyrics expose a same-origin manual search", async () => {
  const app = await setup();
  app.hook((url) => url.includes("/lyrics") ? lyricsResponse({status: "plain", title: "First", plain_lyrics: "<img>\n第二行"}) : null);
  await app.element("lyrics-toggle").listeners.click();
  assert.equal(app.element("lyrics-content").textContent, "<img>\n第二行");
  assert.equal(app.element("lyrics-content").classes.has("plain-lyrics"), true);
  app.hook((url) => url.includes("/lyrics") ? lyricsResponse({status: "not_found"}) : null);
  await app.run("loadLyrics()");
  assert.equal(app.element("lyrics-status").textContent, "找不到歌詞");
  assert.equal(app.element("lyrics-search-form").hidden, false);
  app.element("lyrics-query").value = "歌名 Artist";
  await app.element("lyrics-search-form").listeners.submit({preventDefault() {}});
  assert.ok(app.requests.some((request) => request.url === "api/guilds/1/lyrics?query=" + encodeURIComponent("歌名 Artist")));
  assert.equal(app.requests.every((request) => !/^https?:\/\//.test(request.url)), true);
});

test("lyrics service errors and rate limits leave playback usable with manual retry", async () => {
  const app = await setup();
  app.hook((url) => url.includes("/lyrics") ? lyricsResponse({status: "unavailable"}) : null);
  await app.element("lyrics-toggle").listeners.click();
  assert.match(app.element("lyrics-status").textContent, /暫時無法使用/);
  assert.equal(app.element("toggle").disabled, false);
  app.hook((url) => url.includes("/lyrics") ? errorResponse(429, "歌詞查詢太頻繁，請稍後再試。") : null);
  await app.run("loadLyrics()");
  assert.match(app.element("lyrics-status").textContent, /太頻繁/);
  assert.equal(app.element("lyrics-search-form").hidden, false);
  await app.element("toggle").listeners.click();
  assert.equal(app.element("play-status").textContent, "已暫停");
});

test("late lyrics cannot overwrite a different track, different guild or expired session", async () => {
  const app = await setup({session: discordSession()});
  let release;
  app.hook((url) => url.includes("/lyrics") ? new Promise((resolve) => { release = resolve; }) : null);
  const pending = app.element("lyrics-toggle").listeners.click();
  app.states[1].current.title = "New song";
  app.hook((url) => url.includes("/lyrics") ? lyricsResponse({status: "plain", title: "New song", plain_lyrics: "new lyrics"}) : null);
  await app.run("refresh()"); await flush();
  release({ok: true, status: 200, json: async () => syncedLyrics}); await pending;
  assert.equal(app.element("lyrics-content").textContent, "new lyrics");
  app.hook((url) => url.includes("/lyrics") ? new Promise((resolve) => { release = resolve; }) : null);
  const oldGuild = app.run("loadLyrics()");
  app.element("guild").value = "2"; await app.element("guild").listeners.change();
  release({ok: true, status: 200, json: async () => syncedLyrics}); await oldGuild;
  assert.equal(app.element("lyrics-panel").hidden, true);
  assert.equal(app.element("lyrics-content").textContent, "");
  const expired = app.run("loadLyrics()");
  app.run("signedOut()");
  release({ok: true, status: 200, json: async () => syncedLyrics}); await expired;
  assert.equal(app.element("lyrics-content").textContent, "");
  assert.equal(app.element("dashboard").hidden, true);
});

test("manual lyrics query rejects an older slower response for the same track", async () => {
  const app = await setup();
  let release;
  app.hook((url) => url.endsWith("/lyrics") ? new Promise((resolve) => { release = resolve; })
    : url.includes("/lyrics?") ? lyricsResponse({status: "plain", title: "Manual", plain_lyrics: "manual result"}) : null);
  const older = app.element("lyrics-toggle").listeners.click();
  await app.run('loadLyrics("manual")');
  release({ok: true, status: 200, json: async () => syncedLyrics}); await older;
  assert.equal(app.element("lyrics-content").textContent, "manual result");
});

test("seek controls remain native keyboard/touch ranges and lyrics use no external script", () => {
  const html = fs.readFileSync(path.join(__dirname, "../musicbot/web/index.html"), "utf8");
  const css = fs.readFileSync(path.join(__dirname, "../musicbot/web/dashboard.css"), "utf8");
  for (const id of ["progress", "hero-progress"])
    assert.match(html, new RegExp('id="' + id + '"[^>]*type="range"[^>]*step="1"[^>]*aria-label='));
  assert.match(html, /id="lyrics-toggle"[^>]*aria-controls="lyrics-panel"/);
  assert.match(css, /progress-row input\[type=range\].*min-height:44px/);
  assert.match(css, /@media\(prefers-reduced-motion:reduce\)/);
  assert.ok(!html.includes("lrclib") && !code.includes("https://lrclib"));
});


test("seek sends the captured track token and reconciles a backend stale-track rejection", async () => {
  const app = await setup(), slider = app.element("progress");
  app.states[1].current.track_token = "track-at-drag-start"; await app.run("refresh()");
  slider.listeners.pointerdown(pointer()); slider.value = "110"; slider.listeners.input();
  assert.equal(app.run("seekDrag.trackToken"), "track-at-drag-start");
  // A new playback instance can have identical metadata while the client has not polled.
  app.states[1].current.track_token = "next-playback-instance";
  app.states[1].progress = 4;
  app.hook((url, options) => url.endsWith("/seek") ? (
    assert.equal(JSON.parse(options.body).track_token, "track-at-drag-start"),
    errorResponse(409, "歌曲已更換，請重新調整進度。")) : null);
  await app.document.listeners.pointerup(pointer());
  const requests = app.requests.filter((request) => request.url.endsWith("/seek"));
  assert.equal(requests.length, 1);
  assert.deepEqual(requests[0].data, {position: 110, track_token: "track-at-drag-start"});
  assert.equal(slider.value, 4);
  assert.equal(app.states[1].progress, 4);
  assert.match(app.element("notice").textContent, /歌曲已更換/);
});

test("a changed track token cancels seek even when title URL and duration are unchanged", async () => {
  const app = await setup(), slider = app.element("hero-progress");
  app.states[1].current.track_token = "first-instance"; await app.run("refresh()");
  slider.listeners.pointerdown(pointer()); slider.value = "90"; slider.listeners.input();
  app.states[1].current.track_token = "second-instance"; app.states[1].progress = 2;
  await app.run("refresh()");
  await app.document.listeners.pointerup(pointer());
  assert.equal(app.run("seekDrag"), null);
  assert.equal(slider.value, 2);
  assert.equal(app.requests.some((request) => request.url.endsWith("/seek")), false);
});


test("a blocked single-song preview disables both command confirmation buttons", async () => {
  const app = await setup();
  app.hook((url) => url.endsWith("/resolve") ? lyricsResponse({results: [{
    title: "Too long", kind: "track", url: "https://example.test/long", duration: 99999,
    allowed: false, reason: "超過歌曲長度限制。", preview_id: "blocked-preview"}]}) : null);
  app.element("query").value = "blocked"; await app.run("resolveQuery()");
  const card = app.element("preview-results").children[0];
  assert.equal(card.children[2].disabled, true);
  assert.equal(card.children[3].disabled, true);
  await card.children[2].listeners.click(); await card.children[3].listeners.click();
  assert.equal(app.requests.some((request) => /\/(?:play|playnext)$/.test(request.url)), false);
});


test("native range lost capture preserves preview until document pointerup commits once", async () => {
  const app = await setup(), slider = app.element("progress");
  slider.listeners.pointerdown(pointer());
  slider.value = "120"; slider.listeners.input();
  // Chrome's native range can report lost capture during a legitimate drag.
  slider.listeners.lostpointercapture?.(pointer());
  await app.run("refresh()");
  assert.equal(app.run("seekDrag.position"), 120);
  assert.equal(slider.value, 120);
  assert.equal(slider.capture, undefined);
  assert.equal(app.requests.some((request) => request.url.endsWith("/seek")), false);
  await app.document.listeners.pointerup(pointer("mouse", {pointerId: 99}));
  assert.equal(app.run("seekDrag.position"), 120);
  await app.document.listeners.pointerup(pointer());
  await app.document.listeners.pointerup(pointer());
  assert.equal(app.requests.filter((request) => request.url.endsWith("/seek")).length, 1);
  assert.deepEqual(app.requests.find((request) => request.url.endsWith("/seek")).data, {position: 120});
});

test("blurring a pointer seek cancels safely while keyboard blur commits its final preview", async () => {
  const app = await setup(), slider = app.element("hero-progress");
  slider.listeners.pointerdown(pointer()); slider.value = "100"; slider.listeners.input();
  slider.listeners.blur(); await app.document.listeners.pointerup(pointer());
  assert.equal(slider.value, 30);
  assert.equal(app.requests.some((request) => request.url.endsWith("/seek")), false);
  slider.listeners.keydown({key: "End"}); slider.value = "180"; slider.listeners.input();
  await slider.listeners.blur();
  assert.deepEqual(app.requests.find((request) => request.url.endsWith("/seek")).data, {position: 180});
});

test("queue estimates add current remainder and previous durations", async () => {
  const app = await setup();
  assert.equal(app.run("queueSchedule(state,30).total"), "共 0 小時 3 分");
  assert.equal(app.run("queueSchedule(state,30).times.get(1)"), "約 3 分鐘後");
  assert.equal(app.run("queueSchedule(state,30).times.get(2)"), "約 4 分鐘後");
  assert.equal(app.element("queue").children[0].children[2].children[2].textContent, "約 3 分鐘後");
});

test("unknown duration makes subsequent estimates undetermined", async () => {
  const app = await setup();
  app.states[1].queue[0].duration = 0;
  await app.run("refresh()");
  assert.match(app.run("queueSchedule(state).total"), /已知.*含長度未知/);
  assert.match(app.run("queueSchedule(state).times.get(1)"), /分鐘/);
  assert.equal(app.run("queueSchedule(state).times.get(2)"), "時間未定");
  app.states[1].current.duration = 0;
  await app.run("refresh()");
  assert.equal(app.run("queueSchedule(state).times.get(1)"), "時間未定");
});

test("paused stopped and single repeat never invent start times", async () => {
  const app = await setup();
  for (const [status,repeat,expected] of [
    ["paused","off","暫停中，時間順延"],["stopped","off","時間未定"],
    ["playing","song","單曲重複中，時間未定"]]) {
    app.states[1].status = status; app.states[1].repeat = repeat;
    await app.run("refresh()");
    assert.equal(app.run("queueSchedule(state).times.get(1)"), expected);
  }
});

test("queue repeat shows first traversal and rounds long totals", async () => {
  const app = await setup();
  app.states[1].repeat = "all"; app.states[1].queue[0].duration = 3661;
  await app.run("refresh()");
  assert.equal(app.run("queueSchedule(state).total"), "共 1 小時 4 分");
  assert.match(app.element("queue-timing-note").textContent,/本輪/);
  assert.match(app.run("queueSchedule(state).times.get(1)"),/分鐘/);
});

test("local progress advances only playing and caps at duration", async () => {
  const app = await setup();
  app.run("stateAt = Date.now() - 10000");
  assert.ok(app.run("localProgress()") >= 40);
  app.run('state.status = "paused"');
  assert.equal(app.run("localProgress()"),30);
  app.run('state.status = "playing"; stateAt = Date.now()-999999');
  assert.equal(app.run("localProgress()"),180);
  app.run("connected = false");
  assert.equal(app.run("localProgress()"),30);
});

test("my queue filter uses full positions for move and delete", async () => {
  const app = await setup();
  app.states[1].queue[1].mine = true;
  await app.run("refresh()");
  await app.element("queue-mine").listeners.click();
  const row = app.element("queue").children[0];
  assert.equal(row.dataset.position,"2");
  assert.equal(app.element("queue").children.length,1);
  assert.equal(app.element("queue-count").textContent,"2");
  assert.equal(row.children[4].children[0].disabled,true);
  assert.equal(app.element("shuffle").disabled,true);
  await row.children[4].children[1].listeners.click();
  assert.deepEqual(app.requests.find(r=>r.url.endsWith("queue/move")).data,
    {from:2,to:1,revision:"revision-1"});
  await app.element("queue").children[0].children[4].children[3].listeners.click();
  assert.equal(app.requests.find(r=>r.method==="DELETE").url,"api/guilds/1/queue/1");
});

test("my filter disables pointer sorting and reports empty selection", async () => {
  const app = await setup();
  app.states[1].queue[0].mine = true;
  await app.run("refresh()");
  await app.element("queue-mine").listeners.click();
  const handle = app.element("queue").children[0].children[4].children[0];
  handle.listeners.pointerdown({button:0,isPrimary:true,pointerId:1,pointerType:"mouse"});
  assert.equal(app.run("drag"),null);
  app.states[1].queue[0].mine = false;
  await app.run("refresh()");
  assert.equal(app.element("queue").children.length,0);
  assert.match(app.element("queue-empty").textContent,/沒有你點播/);
  await app.element("queue-all").listeners.click();
  assert.equal(app.element("queue").children.length,2);
});

test("listeners fold above eight and render names as text", async () => {
  const app = await setup();
  app.states[1].listeners = {connected:true,channel:"Music",members:
    Array.from({length:11},(_,i)=>({name:i===0?"<script>unsafe</script>":"Member "+i,avatar:"javascript:evil"}))};
  await app.run("refresh()");
  const list = app.element("listeners-list");
  assert.equal(list.children.length,9);
  assert.equal(list.children[0].children[1].textContent,"<script>unsafe</script>");
  assert.equal(list.children[0].children[0].src,undefined);
  assert.equal(list.children[8].tag,"details");
  assert.match(list.children[8].children[0].textContent,/3/);
  delete app.states[1].listeners;
  await app.run("refresh()");
  assert.match(app.element("listeners-status").textContent,/目前不在語音頻道/);
});

test("activity displays Taiwan time source result and safe song text", async () => {
  const app = await setup();
  app.states[1].activity = {activity:[{actor:"Friend",detail:"點歌：<script>",source:"discord_slash",
    result:"成功",time:Date.UTC(2026,0,1,1,2,3)/1000}]};
  await app.run("refresh()");
  const row = app.element("activity-list").children[0];
  assert.equal(row.children[0].textContent,"Friend・點歌：<script>");
  assert.match(row.children[1].textContent,/09:02:03.*Discord 斜線.*成功/);
});

const snapshot = (state) => ({state:clone(state),history:{history:[]}});
test("SSE connects without headers and supersedes periodic fetches", async () => {
  const app = await setup({events:true});
  assert.equal(app.streams[0].url,"/api/guilds/1/events");
  app.streams[0].emit("snapshot",snapshot(app.states[1]));
  const count = app.requests.length;
  await app.run("poll()");
  assert.equal(app.requests.length,count);
  assert.equal(app.run("fallbackPolling"),false);
  assert.equal(app.element("connection").textContent,"連線狀態");
});

test("SSE pushes community and history without optional REST polling", async () => {
  const app = await setup({events:true});
  app.states[1].volume = 72;
  app.states[1].activity = {activity:[{actor:"Friend",detail:"暫停",source:"web",result:"成功",time:1}]};
  const count = app.requests.length;
  app.streams[0].emit("snapshot",snapshot(app.states[1]));
  assert.equal(app.element("volume").value,72);
  assert.equal(app.element("activity-list").children.length,1);
  assert.equal(app.requests.length,count);
});

test("SSE reconnect backoff and repeated failure polling fallback", async () => {
  const app = await setup({events:true});
  app.streams[0].emit("snapshot",snapshot(app.states[1]));
  const delays = [];
  for (let i=0;i<4;i++) {
    const old = app.streams.at(-1), before = app.timers.length;
    await old.onerror();
    assert.equal(old.closed,true);
    const retry = app.timers.slice(before).at(-1);
    delays.push(retry[1]);
    assert.equal(app.run("fallbackPolling"),true);
    const count = app.requests.length;
    await app.run("poll()");
    assert.ok(app.requests.length>count);
    retry[0]();
  }
  assert.deepEqual(delays,[1000,2000,4000,60000]);
  app.streams.at(-1).emit("snapshot",snapshot(app.states[1]));
  assert.equal(app.run("eventFailures"),0);
  assert.equal(app.run("fallbackPolling"),false);
});

test("SSE switch guild closes old stream ignores stale callbacks", async () => {
  const app = await setup({events:true});
  const old = app.streams[0];
  app.element("guild").value = "2";
  await app.element("guild").listeners.change();
  assert.equal(old.closed,true);
  assert.equal(app.streams.at(-1).url,"/api/guilds/2/events");
  old.emit("snapshot",snapshot(app.states[1]));
  assert.equal(app.element("title").textContent,"Second");
  app.streams.at(-1).emit("snapshot",snapshot(app.states[2]));
  assert.equal(app.element("connection").textContent,"連線狀態");
});

test("SSE hiding tab closes stream and showing resumes", async () => {
  const app = await setup({events:true});
  const old = app.streams[0];
  old.emit("snapshot",snapshot(app.states[1]));
  app.document.hidden = true;
  await app.document.listeners.visibilitychange();
  assert.equal(old.closed,true);
  const count = app.requests.length;
  await app.run("poll()");
  assert.equal(app.requests.length,count);
  app.document.hidden = false;
  await app.document.listeners.visibilitychange();
  assert.equal(app.streams.length,2);
});

test("SSE expiry clears all private UI and closes connection", async () => {
  const app = await setup({events:true,session:{auth_mode:"discord",authenticated:true,
    user:{id:"43",name:"Friend",avatar:""}}});
  const stream = app.streams[0];
  stream.emit("snapshot",snapshot(app.states[1]));
  stream.emit("access",{status:401});
  assert.equal(stream.closed,true);
  assert.equal(app.run("authenticated"),false);
  assert.equal(app.element("queue").children.length,0);
  assert.equal(app.element("activity-list").children.length,0);
  assert.equal(app.element("dashboard").hidden,true);
});

test("SSE construction timeout and absent support retain polling", async () => {
  const app = await setup({events:true});
  const timeout = app.timers.find(timer=>timer[1]===20000);
  assert.ok(timeout);
  await timeout[0]();
  assert.equal(app.streams[0].closed,true);
  assert.equal(app.run("fallbackPolling"),true);
  const plain = await setup();
  assert.equal(plain.run("fallbackPolling"),true);
});

test("legacy shared secret never enters EventSource URL", async () => {
  const app = await setup({events:true});
  app.element("secret").value = "fixture-secret";
  app.element("auth-form").listeners.submit({preventDefault(){}});
  await flush();
  assert.equal(app.streams.length,1);
  assert.equal(app.streams[0].closed,true);
  assert.equal(app.run("fallbackPolling"),true);
  assert.ok(app.streams.every(s=>!s.url.includes("fixture-secret")));
});

test("SSE wrong-guild data closes and reconnects safely", async () => {
  const app = await setup({events:true});
  app.streams[0].emit("snapshot",snapshot(app.states[2]));
  await flush();
  assert.equal(app.streams[0].closed,true);
  assert.equal(app.element("title").textContent,"First");
});

function libraryFixture(owner = false) {
  const lib = {version:1,revision:"library-v1",owner,playlists:[
    {id:"favorites",name:"收藏",tracks:[{title:"<img onerror=evil>",url:"https://example.test/one",duration:90}]},
    {id:"custom",name:"Study",tracks:[{title:"First",url:"https://example.test/a",duration:120},
      {title:"Second",url:"https://example.test/b",duration:null}]}]};
  const perms = {groups:[{name:"Default",editable:["MaxSongs","AllowPlaylists"],
    values:{MaxSongs:3,AllowPlaylists:false,UserList:["未知成員"]}}],
    limits:{MaxSongs:10000,AllowPlaylists:null},activity:[]};
  const apl = {revision:"apl-v1",total:2,matched:2,page:1,page_size:50,
    tracks:[{index:0,url:"https://example.test/one",title:"Song"}]};
  const reply=body=>({ok:true,status:200,json:async()=>clone(body)});
  const hook=(url,options)=>{
    if (url.includes("/admin/permissions")) {
      if (options.method==="PATCH") {const v=JSON.parse(options.body);perms.groups[0].values[v.field]=v.value;}
      return reply({...perms,message:"updated"});
    }
    if (url.includes("/admin/autoplaylist")) return reply(apl);
    if (url.startsWith("/api/library")) {
      if (url.includes("/tracks")&&options.method==="POST") {
        lib.playlists.find(p=>url.includes("/"+p.id+"/")).tracks.push(JSON.parse(options.body).track);
      }
      return reply(lib);
    }
    if (/\/library\/.*\/play$/.test(url)) return reply({added:1,skipped:1,message:"已加入 1 首，被拒 1 首。",results:[],state:initial(1)});
  };
  return {lib,perms,apl,hook};
}
test("round7 general member sees playlists and no management entry", async()=>{
  const fixture=libraryFixture(false),app=await setup({round7:true,hook:fixture.hook});
  await flush();assert.equal(app.element("nav-admin").hidden,true);
  await app.element("nav-library").listeners.click();
  assert.equal(app.element("play-view").hidden,true);assert.equal(app.element("library-panel").hidden,false);
  assert.equal(app.element("library-list").children[0].children[1].textContent.startsWith("<img"),true);
  assert.equal(app.element("library-rename").disabled,true);assert.equal(app.element("library-delete").disabled,true);
});
test("round7 owner capability reveals management and current-track action",async()=>{
  const fixture=libraryFixture(true),app=await setup({round7:true,hook:fixture.hook});
  await flush();assert.equal(app.element("nav-admin").hidden,false);
  assert.equal(app.element("autoplaylist-current").hidden,false);
  await app.element("nav-admin").listeners.click();
  assert.equal(app.element("admin-panel").hidden,false);
  assert.equal(app.element("admin-apl-list").children.length,1);
  assert.equal(app.element("admin-permissions").children[1].children[0].textContent,"Default");
});
test("round7 favorite sends only track metadata with revision",async()=>{
  const fixture=libraryFixture(),app=await setup({round7:true,hook:fixture.hook});
  await app.run('librarySave({title:"Saved",url:"https://example.test/saved",duration:12,requester:{id:"never-save"}},true)');
  const request=app.requests.find(r=>r.url==="/api/library/favorites/tracks");
  assert.deepEqual(request.data,{revision:"library-v1",track:{title:"Saved",url:"https://example.test/saved",duration:12}});
  assert.equal(request.headers["X-MusicBot-Dashboard"],"1");
});
test("round7 playlist picker selects custom list and closes after save",async()=>{
  const fixture=libraryFixture(),app=await setup({round7:true,hook:fixture.hook});
  await app.run('librarySave({title:"Saved",url:"https://example.test/saved",duration:null})');
  assert.equal(app.element("library-save-dialog").open,true);
  app.element("playlist-picker").value="custom";
  await app.element("library-save-confirm").listeners.click();
  assert.ok(app.requests.some(r=>r.url==="/api/library/custom/tracks"));
  assert.equal(app.element("library-save-dialog").open,false);
});
test("round7 up down remove and rename send observed library revision",async()=>{
  const fixture=libraryFixture(),app=await setup({round7:true,hook:fixture.hook});
  await app.element("nav-library").listeners.click();
  app.element("library-select").value="custom";app.element("library-select").listeners.change();
  const row=app.element("library-list").children[0],actions=row.children[2].children;
  assert.equal(actions[0].disabled,true);
  await actions[1].listeners.click();
  const change=app.requests.find(r=>r.method==="PATCH");
  assert.equal(change.data.action,"move");assert.equal(change.data.index,0);assert.equal(change.data.to,1);
  assert.equal(change.data.revision,"library-v1");
  app.element("library-name").value="New name";await app.element("library-rename").listeners.click();
  assert.ok(app.requests.some(r=>r.data?.name==="New name"));
});
test("round7 checked enqueue uses target guild and displays partial rejection",async()=>{
  const fixture=libraryFixture(),app=await setup({round7:true,hook:fixture.hook});
  await app.element("nav-library").listeners.click();
  app.element("library-select").value="custom";app.element("library-select").listeners.change();
  const check=app.element("library-list").children[1].children[0];check.checked=true;check.listeners.change();
  assert.equal(app.element("library-play-selected").disabled,false);
  await app.element("library-play-selected").onclick();
  const request=app.requests.find(r=>r.url==="/api/guilds/1/library/custom/play");
  assert.deepEqual(request.data,{revision:"library-v1",selected_items:["1"]});
  assert.equal(app.element("notice").textContent,"已加入 1 首，被拒 1 首。");
  assert.ok(app.element("notice").classes.has("error"));
});
test("round7 enqueue all omits selection and empty checked selection stays disabled",async()=>{
  const fixture=libraryFixture(),app=await setup({round7:true,hook:fixture.hook});
  await app.element("nav-library").listeners.click();
  assert.equal(app.element("library-play-selected").disabled,true);
  await app.element("library-play-all").onclick();
  const request=app.requests.find(r=>r.url==="/api/guilds/1/library/favorites/play");
  assert.deepEqual(request.data,{revision:"library-v1"});
});
test("round7 permissions require old/new confirmation before PATCH",async()=>{
  const fixture=libraryFixture(true),app=await setup({round7:true,hook:fixture.hook});
  await flush();await app.element("nav-admin").listeners.click();
  const row=app.element("admin-permissions").children[1].children[1];
  row.children[1].value="8";await row.children[2].listeners.click();
  assert.equal(app.element("permission-confirm-dialog").open,true);
  assert.ok(app.element("permission-confirm-text").textContent.includes("3 → 8"));
  assert.equal(app.requests.filter(r=>r.method==="PATCH").length,0);
  await app.element("permission-confirm").listeners.click();
  const request=app.requests.find(r=>r.method==="PATCH");
  assert.deepEqual(request.data,{group:"Default",field:"MaxSongs",old_value:3,value:8});
});
test("round7 permissions cancel invalid values and guild changes send no edit",async()=>{
  const fixture=libraryFixture(true),app=await setup({round7:true,hook:fixture.hook});
  await flush();await app.element("nav-admin").listeners.click();
  const row=app.element("admin-permissions").children[1].children[1];
  row.children[1].value="-1";await row.children[2].listeners.click();
  assert.equal(app.element("permission-confirm-dialog").open,undefined);
  row.children[1].value="4";await row.children[2].listeners.click();
  await app.element("permission-cancel").listeners.click();
  assert.equal(app.element("permission-confirm-dialog").open,false);
  await row.children[2].listeners.click();app.run('generation++');
  await app.element("permission-confirm").listeners.click();
  assert.equal(app.requests.filter(r=>r.method==="PATCH").length,0);
});
test("round7 logout clears private playlists and owner management",async()=>{
  const fixture=libraryFixture(true),app=await setup({round7:true,hook:fixture.hook});
  await flush();await app.element("nav-library").listeners.click();
  assert.ok(app.element("library-list").children.length);
  app.run('signedOut()');
  assert.equal(app.element("library-list").children.length,0);
  assert.equal(app.element("nav-admin").hidden,true);
  assert.equal(app.element("admin-apl-list").children.length,0);
});

function shortcutEvent(app, key, extra = {}) {
  const event = {key, target: app.document.body, prevented: false,
    preventDefault() { this.prevented = true; }, ...extra};
  return {event, result: app.document.listeners.keydown(event)};
}
test("round8 shortcuts reuse playback buttons, seek tokens and request focus", async () => {
  const app = await setup();
  app.states[1].current.track_token = "observed"; await app.run("refresh()");
  await shortcutEvent(app, " ").result; await shortcutEvent(app, " ").result;
  await shortcutEvent(app, "N").result;
  await shortcutEvent(app, "ArrowRight").result;
  const seek = app.requests.find(r => r.url.endsWith("/seek"));
  assert.ok(seek.data.position >= 40 && seek.data.position < 41);
  assert.equal(seek.data.track_token, "observed");
  app.states[1].progress = 5; await app.run("refresh()");
  await shortcutEvent(app, "ArrowLeft").result;
  assert.equal(app.requests.filter(r => r.url.endsWith("/seek")).at(-1).data.position, 0);
  shortcutEvent(app, "/");
  assert.equal(app.element("query").focused, true);
  assert.deepEqual(app.requests.filter(r => ["/pause","/resume","/skip"].some(s => r.url.endsWith(s))).map(r => r.url),
    ["api/guilds/1/pause","api/guilds/1/resume","api/guilds/1/skip"]);
});
test("round8 shortcuts ignore input select textarea editable ancestors and menu", async () => {
  const app = await setup();
  const before = app.requests.length;
  for (const tag of ["input", "select", "textarea", "editable", "menu"]) {
    const target = new Element(tag);
    if (tag === "editable") target.isContentEditable = true;
    if (tag === "menu") target.setAttribute("role", "menu");
    const child = new Element("span"); target.append(child);
    for (const key of [" ", "n", "ArrowLeft", "ArrowRight", "/", "?"])
      await shortcutEvent(app, key, {target: child}).result;
    app.document.activeElement = target;
    await shortcutEvent(app, "n").result;
    app.document.activeElement = null;
  }
  assert.equal(app.requests.length, before);
  assert.notEqual(app.element("shortcuts-dialog").open, true);
});
test("round8 shortcuts ignore modifiers composing repeats and every open dialog", async () => {
  const app = await setup(), before = app.requests.length;
  for (const flag of ["ctrlKey", "altKey", "metaKey", "isComposing", "repeat", "defaultPrevented"])
    for (const key of [" ", "N", "ArrowRight", "/", "?"])
      await shortcutEvent(app, key, {[flag]: true}).result;
  for (const id of ["library-save-dialog", "permission-confirm-dialog"]) {
    app.element(id).showModal();
    for (const key of [" ", "n", "ArrowLeft", "/", "?"]) await shortcutEvent(app, key).result;
    assert.notEqual(app.element("shortcuts-dialog").open, true);
    app.element(id).close();
  }
  assert.equal(app.requests.length, before);
});
test("round8 disabled capabilities stopped tracks busy disconnected and mobile do nothing", async () => {
  const app = await setup();
  app.states[1].capabilities = {pause:false,resume:false,skip:false,seek:false};
  await app.run("refresh()");
  for (const id of ["toggle", "skip", "progress"]) assert.equal(app.element(id).disabled, true);
  const before = app.requests.length;
  for (const key of [" ", "n", "ArrowRight"]) await shortcutEvent(app, key).result;
  assert.equal(app.requests.length, before);
  app.states[1].capabilities = {pause:true,resume:true,skip:true,seek:true};
  for (const status of ["stopped", "disconnected"]) {
    app.states[1].status = status; await app.run("refresh()");
    const count = app.requests.length;
    for (const key of [" ", "n", "ArrowRight"]) await shortcutEvent(app, key).result;
    assert.equal(app.requests.length, count);
  }
  const mobile = await setup({mobile:true}), count = mobile.requests.length;
  for (const key of [" ", "n", "?", "/"]) await shortcutEvent(mobile,key).result;
  assert.equal(mobile.requests.length,count);
  assert.notEqual(mobile.element("shortcuts-dialog").open,true);
});
test("round8 help opens from question mark or button and closes with Esc or close", async () => {
  const app = await setup(), before = app.requests.length;
  assert.equal(shortcutEvent(app, "?").event.prevented, true);
  assert.equal(app.element("shortcuts-dialog").open,true);
  await shortcutEvent(app, "n").result;
  assert.equal(app.requests.length,before);
  shortcutEvent(app, "Escape"); assert.equal(app.element("shortcuts-dialog").open,false);
  app.element("shortcuts-help").click(); assert.equal(app.element("shortcuts-dialog").open,true);
  app.element("shortcuts-close").click(); assert.equal(app.element("shortcuts-dialog").open,false);
  const css = fs.readFileSync(path.join(__dirname,"../musicbot/web/dashboard.css"),"utf8");
  assert.match(css,/\.desktop-shortcuts\{display:none\}/);
});

test("round8 queue search matches title or requester without case and combines with mine", async () => {
  const app = await setup();
  app.states[1].queue = [
    {title:"Alpha",position:1,mine:false,requester:{name:"BoB"},duration:60},
    {title:"Beta",position:2,mine:true,requester:{name:"Alice"},duration:60},
    {title:"ALPHA live",position:3,mine:true,requester:{name:"Bob"},duration:60},
    {title:"Delta",position:4,mine:true,requester:{name:"Alice"},duration:60}];
  await app.run("refresh()");
  const search = text => { app.element("queue-search").value=text;app.element("queue-search").listeners.input(); };
  search("  bOB ");
  assert.deepEqual(app.element("queue").children.map(r=>r.dataset.position),["1","3"]);
  app.element("queue-mine").click();
  assert.deepEqual(app.element("queue").children.map(r=>r.dataset.position),["3"]);
  assert.equal(app.element("queue-match-count").textContent,"顯示 1／4 首");
  const actions=app.element("queue").children[0].children[4].children;
  await actions[1].listeners.click();
  const move=app.requests.find(r=>r.url.endsWith("/queue/move"));
  assert.deepEqual(move.data,{from:3,to:2,revision:"revision-1"});
  // The same original song is now at complete-queue position 2.
  await app.element("queue").children[0].children[4].children[3].listeners.click();
  assert.equal(app.requests.find(r=>r.method==="DELETE").url,"api/guilds/1/queue/2");
  search("missing");assert.equal(app.element("queue-empty").hidden,false);
  search(""); app.element("queue-all").click();
  assert.equal(app.element("queue").children.length,3);
  assert.equal(app.element("shuffle").disabled,false);
});
test("round8 any search disables dragging and shuffle with a reason then restores", async () => {
  const app=await setup();
  app.element("queue-search").value="Two";app.element("queue-search").listeners.input();
  const row=app.element("queue").children[0],handle=row.children[4].children[0];
  assert.equal(handle.disabled,true);assert.equal(app.element("shuffle").disabled,true);
  assert.match(app.element("drag-help").textContent,/搜尋篩選中.*停用拖曳與洗牌/);
  handle.listeners.pointerdown({button:0,pointerId:1,pointerType:"mouse",clientX:40,clientY:210});
  assert.equal(app.run("drag"),null);
  const before=app.requests.length; await app.element("shuffle").listeners.click();
  assert.equal(app.requests.length,before);
  app.element("queue-search").value="";app.element("queue-search").listeners.input();
  assert.equal(app.element("shuffle").disabled,false);
  assert.equal(app.element("queue").children[0].children[4].children[0].disabled,false);
  app.element("queue-search").value="Two";app.element("queue-search").listeners.input();
  app.element("guild").value="2"; await app.element("guild").listeners.change();
  assert.equal(app.element("queue-search").value,"");assert.equal(app.run("queueSearch"),"");
});

test("round8 empty recommendations deduplicate skip current unsafe and cap at five", async () => {
  const app=await setup();
  app.states[1].queue=[];app.states[1].current.url="https://www.youtube.com/watch?v=AbcDeFg1234";
  await app.run("refresh()");
  const rows=[
    {title:"Current",url:"https://youtu.be/AbcDeFg1234?t=2"},
    {title:"One",url:"https://example.test/one"},
    {title:"One again",url:"https://EXAMPLE.test/one/#ignored"},
    {title:"Unsafe",url:"javascript:alert(1)"},
    ...Array.from({length:7},(_,i)=>({title:"Song "+i,url:"https://example.test/song/"+i}))];
  app.context.historyFixture=rows;
  app.run("applyHistory({history: historyFixture})");
  assert.equal(app.element("queue-recommendations").hidden,false);
  assert.deepEqual(app.element("recommendation-list").children.map(r=>r.children[1].children[0].textContent),
    ["One","Song 0","Song 1","Song 2","Song 3"]);
  app.states[1].queue=[{title:"Other",position:1}];await app.run("refresh()");
  app.element("queue-search").value="missing";app.element("queue-search").listeners.input();
  assert.equal(app.element("queue-recommendations").hidden,true); // True empty only, not filtered empty.
  app.states[1].queue=[];await app.run("refresh()");app.run("applyHistory({history: []})");
  assert.equal(app.element("queue-recommendations").hidden,true);
});
test("round8 recommendation add resolves and requires normal preview confirmation", async () => {
  const app=await setup();
  app.states[1].queue=[];await app.run("refresh()");
  app.run('applyHistory({history:[{title:"Recent",url:"https://example.test/selected"}]})');
  await app.element("recommendation-list").children[0].children[2].click();
  const resolve=app.requests.find(r=>r.url.endsWith("/resolve"));
  assert.deepEqual(resolve.data,{query:"https://example.test/selected",action:"play"});
  assert.equal(app.requests.filter(r=>r.url.endsWith("/play")).length,0);
  await app.element("preview-results").children[0].children[2].click();
  assert.deepEqual(app.requests.find(r=>r.url.endsWith("/play")).data,
    {query:"https://example.test/selected",preview_id:"preview-one"});
});
test("round8 recommendation rejection and stale guild button preserve existing boundaries", async () => {
  const app=await setup();
  app.states[1].queue=[];await app.run("refresh()");
  app.run('applyHistory({history:[{title:"Recent",url:"https://example.test/selected"}]})');
  const add=app.element("recommendation-list").children[0].children[2];
  app.hook(url=>url.endsWith("/resolve")?Promise.resolve({ok:false,status:403,json:async()=>({error:"權限拒絕"})}):null);
  await add.click();assert.equal(app.element("notice").textContent,"權限拒絕");
  assert.equal(app.requests.filter(r=>r.url.endsWith("/play")).length,0);
  app.element("guild").value="2";await app.element("guild").listeners.change();
  const count=app.requests.length;await add.listeners.click();
  assert.equal(app.requests.length,count);assert.equal(app.element("queue-recommendations").hidden,true);
});

test("round8 YouTube identities unify watch short embed shorts live mobile and music links", async () => {
  const app=await setup();
  const urls=[
    "https://www.youtube.com/watch?v=AbcDeFg1234&list=PLdemo&t=42",
    "https://youtu.be/AbcDeFg1234?si=sharing",
    "https://m.youtube.com/watch?feature=share&v=AbcDeFg1234",
    "https://music.youtube.com/watch?v=AbcDeFg1234&list=RDdemo",
    "https://www.youtube.com/shorts/AbcDeFg1234",
    "https://www.youtube.com/embed/AbcDeFg1234?start=10",
    "https://www.youtube-nocookie.com/embed/AbcDeFg1234",
    "https://youtube.com/live/AbcDeFg1234?feature=share",
    "http://youtube.com/v/AbcDeFg1234#t=1"];
  for(const url of urls) {
    app.context.testURL=url;assert.equal(app.run("songIdentity(testURL)"),"youtube:AbcDeFg1234",url);
  }
  assert.notEqual(app.run('songIdentity("https://youtube.com/watch?v=abcdefg1234")'),"youtube:AbcDeFg1234");
  assert.notEqual(app.run('songIdentity("https://youtube.com.evil.test/watch?v=AbcDeFg1234")'),"youtube:AbcDeFg1234");
  assert.equal(app.run('songIdentity("javascript:alert(1)")'),"");
});
test("round8 non YouTube normalization removes fragments tracking slash and orders query", async () => {
  const app=await setup();
  assert.equal(app.run('songIdentity(" HTTPS://EXAMPLE.test:443/song/?b=2&a=1&utm_source=share#fragment ")'),
    app.run('songIdentity("https://example.test/song?a=1&b=2&fbclid=ignored")'));
  assert.notEqual(app.run('songIdentity("https://example.test/song?a=2")'),
    app.run('songIdentity("https://example.test/song?a=1")'));
  assert.notEqual(app.run('songIdentity("https://example.test/Song")'),
    app.run('songIdentity("https://example.test/song")'));
  assert.equal(app.run('songIdentity("https://user:pass@example.test/song")'),"");
});
test("round8 track duplicate warning is adjacent remains confirmable and follows live positions", async () => {
  const app=await setup();
  app.states[1].queue[1].url="https://youtu.be/AbcDeFg1234";
  await app.run("refresh()");
  app.hook(url=>url.endsWith("/resolve")?Promise.resolve({ok:true,status:200,json:async()=>({results:[
    {title:"Duplicate",kind:"track",url:"https://music.youtube.com/watch?v=AbcDeFg1234",allowed:true,preview_id:"duplicate"}
  ]})}):null);
  app.element("query").value="duplicate"; await app.run("resolveQuery()");
  const card=app.element("preview-results").children[0],note=card.children.at(-1),button=card.children[2];
  assert.equal(note.textContent,"這首已經在佇列第 2 首");
  assert.equal(note.hidden,false);assert.equal(button.disabled,false);
  app.states[1].queue[1].position=1;await app.run("refresh()");
  assert.equal(note.textContent,"這首已經在佇列第 1 首");
  await button.click();
  assert.equal(app.requests.find(r=>r.url.endsWith("/play")).data.preview_id,"duplicate");
});
test("round8 currently playing reminder and removed duplicate update without rebuilding preview", async () => {
  const app=await setup();
  app.states[1].current.url="https://EXAMPLE.test:443/selected/#old";await app.run("refresh()");
  app.element("query").value="song";await app.run("resolveQuery()");
  const card=app.element("preview-results").children[0],note=card.children.at(-1);
  assert.equal(note.textContent,"這首目前正在播放");
  app.states[1].current.url="https://example.test/other";await app.run("refresh()");
  assert.equal(note.hidden,true);assert.equal(app.element("preview-results").children[0],card);
});
test("round8 playlist duplicate tags never change selected items and follow queue updates", async () => {
  const {app,card,button}=await playlistApp();
  const list=card.children[1].children.at(-1);
  const first=list.children[0].children[0], third=list.children[2].children[0];
  app.context.batchURL=app.run("previewResults[0].entries[0].url");
  app.states[1].queue[0].url=app.context.batchURL;
  await app.run("refresh()");
  assert.equal(first.children.at(-1).textContent,"已在佇列");
  assert.equal(first.children[0].checked,true);
  const selected=button.textContent;
  app.states[1].queue[0].url="https://example.test/other";await app.run("refresh()");
  assert.equal(first.children.at(-1).hidden,true);assert.equal(button.textContent,selected);
  assert.equal(third.children[0].checked,true);
  await button.click();
  assert.ok(app.requests.find(r=>r.url.endsWith("/play")).data.selected_items.includes("1"));
});

test("round8 shortcuts respect busy disconnected and signed out control states", async () => {
  const app=await setup();
  for(const expression of ["busy=true;controls()","busy=false;connected=false;controls()","connected=true;signedOut()"]) {
    app.run(expression);const before=app.requests.length;
    for(const key of [" ","n","ArrowLeft","/"]) await shortcutEvent(app,key).result;
    assert.equal(app.requests.length,before);
  }
});


test("round10 mobile volume, selection locks and connection states", async () => {
  const app = await setup({mobile:true});
  assert.equal(app.element("toggle").textContent,"暫停");
  app.run('connectionStatus("即時連線重試中")');
  assert.equal(app.element("connection").textContent,"連線狀態");
  assert.equal(app.element("connection").dataset.state,"reconnecting");
  await app.element("hero-volume").listeners.pointerdown({});
  assert.ok(app.document.body.classes.has("no-selection"));
  app.document.listeners.pointercancel({pointerId:99});
  assert.ok(!app.document.body.classes.has("no-selection"));
  app.run('noSelection("queue",true); noSelection("seek",true); cancelDrag(); cancelSeek()');
  assert.ok(!app.document.body.classes.has("no-selection"));
  const html=fs.readFileSync(path.join(__dirname,"../musicbot/web/index.html"),"utf8");
  assert.match(html,/class="sr-only seek-hint"/);
  assert.match(html,/id="drag-help" class="sr-only"/);
  assert.doesNotMatch(html,/[⏸⏭]/);
  const css=fs.readFileSync(path.join(__dirname,"../musicbot/web/dashboard.css"),"utf8");
  assert.match(css,/playback-bar>\.volume-row\{display:none\}/);
  assert.match(css,/-webkit-touch-callout:none/);
});


test("round10 favorite toggles pressed state and normalized identities", async () => {
  const fixture=libraryFixture(), app=await setup({round7:true,hook:fixture.hook});
  await flush();
  app.run('libraryData.playlists[0].tracks=[{url:"https://youtu.be/video000001?t=3"}]; state.current.url="https://music.youtube.com/watch?v=video000001";favoriteRender()');
  assert.equal(app.element("favorite").attributes["aria-pressed"],"true");
  assert.match(app.element("favorite").textContent,/♥/);
  app.run('libraryData.playlists[0].tracks=[];favoriteRender()');
  assert.equal(app.element("favorite").attributes["aria-pressed"],"false");
  app.element("favorite").dataset.loading="1"; app.run("controls()");
  assert.equal(app.element("favorite").disabled,true);
});


test("round10 song links canonicalize YouTube, reject scripts and suppress drag clicks",async()=>{
  const app=await setup();
  assert.equal(app.run('songLinkURL("https://youtu.be/video000001?t=3")'),"https://www.youtube.com/watch?v=video000001");
  for(const bad of ["javascript:evil","data:text/html,x","file:///tmp/x","https://u:p@example.test/"])
    assert.equal(app.run("songLinkURL("+JSON.stringify(bad)+")"),"");
  app.run('state.queue[0].url="https://music.youtube.com/watch?v=video000001";queueRevision=null;renderQueue()');
  const link=app.element("queue").children[0].children[2].children[0].children[0];
  assert.equal(link.target,"_blank");assert.equal(link.rel,"noopener noreferrer");
  let prevented=false;
  app.run("suppressSongLinksUntil=Date.now()+1000");
  link.listeners.click({preventDefault(){prevented=true;}});
  assert.equal(prevented,true);
  app.run("suppressSongLinksUntil=0");
  prevented=false;link.listeners.click({preventDefault(){prevented=true;}});
  assert.equal(prevented,false);
});


test("Spotify prefetch enables a real href without opening a popup", async () => {
  const app = await setup();
  const link = app.element("spotify-link");
  assert.equal(link.getAttribute("href"), "https://open.spotify.com/track/Fake0001");
  assert.equal(link.getAttribute("aria-disabled"), "false");
  assert.equal(link.classes.has("is-loading"), false);
});
test("Spotify ignores stale replies and disables clicks while loading", async () => {
  const app = await setup();
  const pending = [];
  app.hook(url => url.endsWith("/spotify") ? new Promise(resolve => pending.push(resolve)) : null);
  app.run('spotifyPrefetch()');
  assert.equal(app.element("spotify-link").getAttribute("href"), null);
  let prevented = false;
  app.element("spotify-link").listeners.click({preventDefault() { prevented = true; }});
  assert.equal(prevented, true);
  app.run('state.current = {title:"Another"}; spotifyPrefetch()');
  pending[1]({ok:true,status:200,json:async()=>({url:"https://open.spotify.com/track/New"})});
  await flush();
  pending[0]({ok:true,status:200,json:async()=>({url:"https://open.spotify.com/track/Old"})});
  await flush();
  assert.equal(app.element("spotify-link").getAttribute("href"), "https://open.spotify.com/track/New");
  app.run('state.current = null; spotifyPrefetch()');
  assert.equal(app.element("spotify-link").hidden, true);
  assert.equal(app.element("spotify-link").getAttribute("href"), null);
});
test("Spotify lookup failure offers an encoded search URL", async () => {
  const app = await setup();
  app.hook(url => url.endsWith("/spotify") ? Promise.resolve({ok:false,status:503,json:async()=>({error:"稍後再試"})}) : null);
  await app.run('spotifyPrefetch()');
  assert.equal(app.element("spotify-link").getAttribute("href"), "https://open.spotify.com/search/First");
});


test("maintenance renders owner metadata safely and discards stale replies", async () => {
  const app=await setup({round7:true});
  app.run('adminOwner=true');
  app.hook(url=>url.endsWith("/admin/maintenance")?Promise.resolve({ok:true,status:200,json:async()=>({
    cookie:{status:"ok",earliest_expiry:"2026-10-20T00:00:00Z",remaining_days:3,warning:true,cookies:[]},
    versions:{"yt-dlp":"2026.10.17"},host_status:{status:"missing"},viewers:2})}):null);
  await app.run('adminMaintenanceLoad()');
  const rows=app.element("maintenance-details").children;
  assert.ok(rows.some(row=>row.textContent.includes("剩餘 3 天")&&row.classes.has("maintenance-warning")));
  assert.ok(rows.some(row=>row.textContent==="2 人（最近 45 秒）"));
  app.run('adminClear()');
  assert.equal(app.element("maintenance-details").children.length,0);
});

test("owner empty-queue settings use guild-scoped JSON and validate ranges",async()=>{
  const app=await setup({round7:true});
  app.run('adminOwner=true');
  await app.run('adminEmptyQueueLoad()');
  assert.equal(app.element("empty-queue-mode").value,"autoplaylist");
  app.element("empty-queue-mode").value="radio";
  app.element("radio-min-seconds").value="60";app.element("radio-max-seconds").value="600";
  await app.element("empty-queue-form").listeners.submit({preventDefault(){}});
  const request=app.requests.find(r=>r.url.endsWith("/admin/empty-queue")&&r.method==="POST");
  assert.deepEqual(request.data,{empty_queue:"radio",radio_min_seconds:60,radio_max_seconds:600});
  const count=app.requests.length;
  app.element("radio-min-seconds").value="-1";
  await app.element("empty-queue-form").listeners.submit({preventDefault(){}});
  assert.equal(app.requests.length,count);
});
