# Dashboard languages

The dashboard ships with English (`en`) and Traditional Chinese (`zh-TW`).
Choose a language in the language selector, available on the login page and in
the dashboard. The preference is saved in localStorage as `musicbot-language`.
Precedence is saved choice, the first supported entry in `navigator.languages`,
then `DefaultLanguage` from `web_dashboard.ini` (default `en`).
Changing it reloads the page so dynamic content and live updates use it too.
The document's `lang` attribute and accessible labels follow the choice.

`TimeZone` in the same ini is an IANA time zone, default `UTC`.
Dates use the selected locale and this server time zone through Intl.
`GET /ui-config` exposes only those two public preferences.

## Architecture

Both frontend and backend use `musicbot/web/i18n/*.json`. Translation keys are
stable identifiers, with named `{p0}`, `{p1}` slots for dynamic values.
Frontend content uses `t(key, params)`; static HTML uses `data-i18n` or
`data-i18n-aria-label`, `data-i18n-title` and `data-i18n-placeholder`.
Translations are assigned with textContent, never parsed as HTML.

The backend chooses catalog strings per request using the validated
`X-Dashboard-Language` header, then Accept-Language, then the server default.
EventSource uses a validated `lang` query option because it cannot send headers.
A ContextVar isolates concurrent requests. Errors keep their HTTP status and
safe, translated messages; arbitrary exception text is never returned.
Discord notifications remain in MusicBot's existing gettext catalog and follow
the guild's language, independently of the web preference. The summon dashboard
URL is also a gettext message; its URL comes from PublicURL.

Activity records store translation keys and safe parameters, so existing
records can be rendered in the current language. Song titles, account names,
server names, lyrics and source metadata remain as supplied by their authors.

## Add a language

1. Copy `en.json` to a locale file such as `fr.json`. Translate every value,
   preserving keys and parameter slots. Do not translate user content.
2. Add the locale to `SUPPORTED` / `language_tag` in
   `web_dashboard_i18n.py`, `DASHBOARD_LANGUAGES` / `supportedLanguage` in
   `web/i18n.js`, the config validation and language-catalog route in
   `web_dashboard.py`, and the selector in `web/index.html`.
3. Add its JSON URL to the static service-worker list. Update its cache version
   and the HTML asset `?v=` values.
4. Extend `tools/check_dashboard_i18n.py` and the frontend language tests for
   the new catalog. Run `python -m tools.check_dashboard_i18n` and
   `node --test tests/test_web_dashboard_i18n.cjs`, then check both login and
   signed-in screens at phone and desktop widths.
