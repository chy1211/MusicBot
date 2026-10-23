"use strict";
const {session, setup} = require("./dashboard_round31_auth_fixture.cjs");
async function streamSetup(page, value = session, available = true) {
  await setup(page, value);
  await page.clock.install({time: new Date("2026-01-01T00:00:00Z")});
  await page.addInitScript(available => {
    window.__streams = []; window.__stateReads = [];
    const fetch = window.fetch.bind(window);
    window.fetch = (url, init) => {
      if (/\/state$/.test(String(url))) window.__stateReads.push({url: String(url), time: Date.now()});
      return fetch(url, init);
    };
    class Stream {
      constructor(url, options) { this.url = url; this.options = options; this.listeners = {}; this.closed = false; window.__streams.push(this); }
      addEventListener(type, callback) { (this.listeners[type] ||= []).push(callback); }
      close() { this.closed = true; }
      emit(type, value) { for (const listener of this.listeners[type] || []) listener(new MessageEvent(type, {data: JSON.stringify(value)})); }
      fail() { this.onerror?.(new Event("error")); }
    }
    window.EventSource = available ? Stream : undefined;
  }, available);
}
module.exports = {streamSetup};
