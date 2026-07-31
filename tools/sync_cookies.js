#!/usr/bin/env node
// Syncs YouTube/Google auth cookies from a live, already-logged-in Chrome/
// Chromium session (reached via the Chrome DevTools Protocol) into a
// Netscape cookies.txt file that yt-dlp/MusicBot can read.
//
// This does NOT perform any login of its own -- it only reads whatever
// session already exists in the browser, so it never triggers Google's
// automated-login/new-device checks. Writes atomically and never overwrites
// a good cookie file with an empty/failed extraction.
//
// Prerequisite: a Chrome/Chromium instance already running and logged into
// a Google/YouTube account, started with --remote-debugging-port (and
// ideally --remote-debugging-address=127.0.0.1 to keep it off the network).
//
// Usage:
//   CDP_PORT=9224 OUTPUT_PATH=/path/to/cookies.txt node sync_cookies.js
//   node sync_cookies.js /path/to/cookies.txt   (positional arg also works)

const http = require('http');
const fs = require('fs');
const WebSocket = require('ws');

const CDP_HOST = process.env.CDP_HOST || '127.0.0.1';
const CDP_PORT = Number(process.env.CDP_PORT || 9224);
const OUTPUT_PATH = process.argv[2] || process.env.OUTPUT_PATH || './cookies.txt';

function httpJson(reqPath, method = 'GET') {
  return new Promise((resolve, reject) => {
    const req = http.request({ host: CDP_HOST, port: CDP_PORT, path: reqPath, method }, (res) => {
      let data = '';
      res.on('data', (c) => (data += c));
      res.on('end', () => {
        try {
          resolve(JSON.parse(data));
        } catch (e) {
          reject(new Error(`Bad JSON from CDP ${reqPath}: ${data.slice(0, 200)}`));
        }
      });
    });
    req.on('error', reject);
    req.end();
  });
}

function cdp(wsUrl, messages) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    const results = {};
    let idx = 0;
    const timer = setTimeout(() => {
      ws.terminate();
      reject(new Error('CDP timeout'));
    }, 15000);
    ws.on('open', () => {
      ws.send(JSON.stringify({ id: messages[idx].id, method: messages[idx].method, params: messages[idx].params || {} }));
    });
    ws.on('message', (data) => {
      const msg = JSON.parse(data);
      if (msg.id === messages[idx].id) {
        results[messages[idx].method] = msg.result;
        idx++;
        if (idx >= messages.length) {
          clearTimeout(timer);
          ws.close();
          resolve(results);
        } else {
          ws.send(JSON.stringify({ id: messages[idx].id, method: messages[idx].method, params: messages[idx].params || {} }));
        }
      }
    });
    ws.on('error', (e) => {
      clearTimeout(timer);
      reject(e);
    });
  });
}

function toNetscape(cookies) {
  const lines = ['# Netscape HTTP Cookie File'];
  for (const c of cookies) {
    const domain = c.domain;
    const includeSub = domain.startsWith('.') ? 'TRUE' : 'FALSE';
    const cpath = c.path || '/';
    const secure = c.secure ? 'TRUE' : 'FALSE';
    const expiry = c.expires && c.expires > 0 ? Math.floor(c.expires) : 0;
    lines.push([domain, includeSub, cpath, secure, expiry, c.name, c.value].join('\t'));
  }
  return lines.join('\n') + '\n';
}

async function main() {
  let targetId;
  try {
    const created = await httpJson('/json/new?about:blank', 'PUT');
    targetId = created.id;

    const results = await cdp(created.webSocketDebuggerUrl, [
      { id: 1, method: 'Network.enable' },
      { id: 2, method: 'Network.getAllCookies' },
    ]);

    const cookies = results['Network.getAllCookies'].cookies || [];
    const relevant = cookies.filter(
      (c) => c.domain.includes('youtube.com') || c.domain.includes('google.com')
    );

    const requiredNames = ['SID', 'SAPISID', 'LOGIN_INFO'];
    const haveNames = new Set(relevant.map((c) => c.name));
    const missing = requiredNames.filter((n) => !haveNames.has(n));
    if (relevant.length < 10 || missing.length > 0) {
      throw new Error(
        `Extraction looks incomplete (got ${relevant.length} cookies, missing: ${missing.join(',') || 'none'}). ` +
        `Not touching existing cookies.txt. Is the browser still logged in?`
      );
    }

    const content = toNetscape(relevant);
    const tmpPath = OUTPUT_PATH + '.tmp';
    fs.writeFileSync(tmpPath, content, { mode: 0o600 });
    fs.renameSync(tmpPath, OUTPUT_PATH);
    fs.chmodSync(OUTPUT_PATH, 0o600);

    console.log(`OK: wrote ${relevant.length} cookies to ${OUTPUT_PATH}`);
  } finally {
    if (targetId) {
      await httpJson(`/json/close/${targetId}`).catch(() => {});
    }
  }
}

main().catch((e) => {
  console.error('FAILED:', e.message);
  process.exit(1);
});
