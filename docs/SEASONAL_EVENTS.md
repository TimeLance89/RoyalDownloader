# Seasonal Home events

Events decorate existing Home elements without adding a banner, changing
recommendations, moving cards or intercepting clicks.

Halloween runs annually on October 28–31, using the browser's local calendar:

- October 28: a fine web at the existing Hero corner and a warm frame accent.
- October 29: branches and bats at the Hero edge; small webs on the first cards.
- October 30: pumpkins beside the Hero controls.
- October 31: an additional corner web and a candle complete the decoration.

The switch is under **Settings → Operation & setup → Home page events**.
It saves immediately to `seasonal_events_enabled` in the existing settings file.
Events are enabled by default on existing installations. `GET/POST /api/ui/events`
and `/api/v1/ui/events` read and save the boolean preference without changing language.

The decoration uses five small local SVG files, six image nodes and one overlay.
There is no animation loop, particle engine, canvas or expensive blur filter.
Only one midnight timer is scheduled while Home is visible. Returning to Home
or the browser checks the date again; November 1 removes all decoration.
Leaving Home disposes listeners, cancels its timer and removes the overlay.

Tests cover calendar boundaries, subsequent years, real settings persistence,
failed saves, stale and cancelled reads, all four stages, mobile/desktop layout
invariance, image loading, pointer transparency and automatic removal at midnight.
