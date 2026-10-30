# Seasonal Home events

Halloween runs annually on October 28–31 using the browser's local calendar.
The existing Home layout, movie artwork, recommendations and controls stay intact.
A locally bundled photograph of storm clouds sits behind the whole Home view,
including the rails far below the Hero. No newly drawn ornaments or lightning bolts.
The scene grows darker each day; it disappears automatically on November 1.

The photograph is licensed for use in apps. Source, photographer and license are
recorded in `web/assets/events/CREDITS.md`. It is 178 KB with no external requests.
No image is downloaded when events are disabled or outside the event dates.

A single 280 ms light impulse animates opacity behind the content. It first fires
1.8 seconds after activation, then every ten seconds while Home is visible.
Scrolling past the Hero does not stop it. Hidden browser tabs, leaving Home,
disabling events and reduced-motion preferences cancel all pending flashes.
Reduced motion retains the static dark background without any weather animation.
No rendering loop, particles, canvas, animated filters or continuously moving layers.

The switch is under **Settings → Operation & setup → Home page events**.
It saves immediately to `seasonal_events_enabled` in the existing settings file.
Events are enabled by default. `GET/POST /api/ui/events` and `/api/v1/ui/events`
read and save the boolean preference for both German and English users.
One midnight timer is scheduled while Home is visible. Returning to Home or the
browser checks the date again. Leaving Home disposes all timers and listeners
and removes the background and flash layers.

Tests cover calendar boundaries, subsequent years, settings persistence and failed
saves, stale and cancelled reads, all four stages, mobile/desktop layout invariance,
local image loading, pointer transparency, full-viewport positioning after scrolling,
regular flashes below the Hero, hidden-tab/reduced-motion cancellation and midnight cleanup.

## Decorations that build up each day

Existing transparent PNG artwork is anchored to the edges of the Hero and selected
series/gems/new-title rails. Nothing is drawn with HTML, CSS shapes, inline SVG or
canvas. Sources, authors, CC0 license and preparation are in the asset credits.

- October 28: one corner web on the Hero.
- October 29: three placements, adding a bat flock and a web on the series rail.
- October 30: five placements, adding an illuminated pumpkin and bats at the gems rail.
- October 31: nine placements, with a pumpkin pair, the opposite Hero web, a pumpkin
  at the gems rail and a web at the new-title rail.

Images are absolutely positioned and pointer-transparent. Mobile uses smaller Hero
motifs above the copy and moves the gems pumpkin to the right-hand edge. No image
animations or new timers; the full-page background flashes retain their existing
cadence. The nine final placements reuse three local PNGs totaling 217 KB.
Later-stage files are not requested before their day. Disabling events, leaving
Home or reaching November 1 removes every decoration as well as the background.
Refreshing is idempotent and changing to an earlier date removes later motifs.
