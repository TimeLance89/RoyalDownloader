# Seasonal Home events

Halloween runs annually on October 28–31 using the browser's local calendar.
The existing Home layout, movie artwork, recommendations and controls stay intact.
A locally bundled photograph of storm clouds sits behind the whole Home view,
including the rails far below the Hero. No hand-drawn ornaments or lightning bolts.
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
