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
    this.classList = {toggle() {}};
  }
  append(...items) {
    this.children.push(...items);
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
async function setup() {
  const elements = new Map();
  const document = {activeElement: null, hidden: false,
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, new Element(id === "guild" ? "select" : "div"));
      return elements.get(id);
    },
    createElement: (tag) => new Element(tag),
    querySelectorAll() {
      const result = [];
      function walk(element) {
        if (element.tag === "button") result.push(element);
        element.children.forEach(walk);
      }
      walk(this.getElementById("queue"));
      return result;
    }};
  const requests = [], timers = [], states = {1: initial(1), 2: initial(2)};
  let hook = null;
  async function fetch(url, options) {
    requests.push({url, ...options, data: options.body ? JSON.parse(options.body) : undefined});
    if (hook) {
      const intercepted = hook(url, options);
      if (intercepted) return intercepted;
    }
    let body, status = 200;
    if (url === "api/guilds") body = {guilds: [{id: "1", name: "First Guild"}, {id: "2", name: "Second Guild"}]};
    else {
      const match = url.match(/^api\/guilds\/(\d+)\/(.+)$/);
      const state = states[match[1]], action = match[2], data = options.body && JSON.parse(options.body);
      if (action === "state") body = clone(state);
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
  const context = vm.createContext({document, fetch, window: {setTimeout: (...args) => timers.push(args)}});
  vm.runInContext(code, context);
  await flush();
  return {document, elements, states, requests, context, timers,
    element: (id) => document.getElementById(id),
    run: (expression) => vm.runInContext(expression, context),
    hook: (value) => { hook = value; }};
}

test("renders current track, progress, queue and safe untrusted titles", async () => {
  const app = await setup();
  assert.equal(app.element("title").textContent, "First");
  assert.equal(app.element("progress").value, 30);
  assert.equal(app.element("queue-count").textContent, "2");
  assert.equal(app.element("queue").children[0].children[1].children[0].textContent, "<img onerror=evil>");
  assert.equal(app.element("enqueue").disabled, false);
  assert.equal(app.timers[0][1], 1000);
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
  const mutations = app.requests.filter((r) => r.method === "POST");
  assert.deepEqual(mutations.map((r) => r.url), [
    "api/guilds/1/pause", "api/guilds/1/volume", "api/guilds/1/repeat", "api/guilds/1/play"]);
  assert.equal(mutations[1].data.volume, 65);
  assert.equal(mutations[2].data.mode, "all");
  assert.equal(mutations[3].data.query, "search words");
  assert.equal(mutations[3].headers["X-MusicBot-Dashboard"], "1");
  assert.equal(app.element("query").value, "");
});

test("queue handlers retain observed revision and block invalid boundaries", async () => {
  const app = await setup();
  const actions = app.element("queue").children[0].children[2].children;
  assert.equal(actions[0].disabled, true);
  await actions[1].listeners.click();
  const move = app.requests.find((r) => r.url.endsWith("queue/move"));
  assert.deepEqual(move.data, {from: 1, to: 2, revision: "revision-1"});
  await app.element("queue").children[0].children[2].children[2].listeners.click();
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
  app.hook((url) => url.endsWith("/play") ? Promise.reject(new Error("network lost")) : null);
  await app.element("play-form").listeners.submit({preventDefault() {}});
  assert.equal(app.element("query").value, "keep this");
  assert.equal(app.element("notice").textContent, "network lost");
  app.hook(() => Promise.resolve({ok: false, status: 401, json: async () => ({error: "key required"})}));
  await app.run("connect()");
  assert.equal(app.element("auth").open, true);
  assert.equal(app.element("toggle").disabled, true);
});
