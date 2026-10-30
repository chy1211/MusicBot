# Dashboard styles

`index.css` is the only global stylesheet imported by `main.ts`.
Its import order preserves the existing cascade; file names describe their purpose.

| File | Responsibility |
| --- | --- |
| foundation.css | Shared tokens, element defaults and baseline component layouts |
| surfaces.css | Glass materials, themes and shared responsive refinements |
| dashboard-layout.css | Header search, now-playing information and up-next layout |
| mobile-player.css | Portrait spacing and the short landscape player layout |
| palettes.css | Fixed noir and iris palette tokens |
| dashboard-controls.css | Playlist dialog, compact queue, avatars and inline transport icons |
| navigation.css | Sidebar/bottom tabs and landscape player controls |
| notifications.css | Desktop/tablet notification position above the measured dock |

Keep component rules in their owning file. Add new files by feature, rather than
patch or round number, and import them here in the intended cascade order.
