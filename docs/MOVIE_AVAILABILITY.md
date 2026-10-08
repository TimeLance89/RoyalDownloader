# Movie availability

The movie detail endpoint accepts `progressive=true`. The normal endpoint stays
compatible with older clients. A progressive request waits at most 0.8 seconds
for its shared detail job, then returns HTTP 202 with `availability.complete=false`
when the answer is still open. A provider timeout, failed request, cooldown or
exhausted admission limit cannot establish a definitive negative. An ambiguous
`None` from a provider detail parser stays unknown; a parsed detail without hosters
or a completed search without matching candidates can establish absence. Legacy clients
receive HTTP 503 / `movie_probe_pending` for an incomplete resolution, rather
than HTTP 404 / `movie_hoster_unavailable`.

Source checks use a bounded, fair scheduler: eight workers, at most one running
job per provider, 48 outstanding jobs and 512 retained entries. Four detail
workers admit at most 16 outstanding jobs; two independent language workers
admit eight. Closing a dialog stops only that view's polling, not shared provider
work. Scraper network timeouts bound running work; Python cannot forcibly stop
a running scraper thread.

The selected search provider gets a 150 ms head start. Remaining matching
providers then run concurrently. TMDB candidate searches and detail loads retain
late results across polls. Title/year matching and the concrete audio-language
policy still apply. Raw provider loads bypass language expansion to prevent
recursive scheduling inside source workers.

Positive source results expire after 180 seconds, empty results after 30 seconds
and errors after five seconds. Partial detail/language snapshots expire after
one second so polls can collect further answers. A cached result does not renew
the underlying source proof's timestamp. Keys distinguish the actual catalog
cache, configured providers, their order and enabled languages. A result cannot
publish across a settings change. Providers temporarily excluded by health
routing leave negative resolutions incomplete.

The dialog polls for at most 60 seconds, with individual HTTP requests limited
to five seconds. It renders the first valid source immediately while other
sources continue independently. Temporary transport failures retry twice with
backoff. A still-open check offers “Quellen erneut prüfen”; it does not declare
the movie unavailable. Download preparation uses the same mechanism and can
proceed as soon as a source is confirmed. Finding a Hoster on a provider page
does not prove stream playback; the download resolver validates the stream.

Regression coverage includes retained late answers, concurrent callers, bounded
admission, error/negative/positive TTLs, stale hosters, settings changes, provider
failover and browser polling on desktop and touch mobile.

Local Windows validation: 1,537 Python tests passed (11 skipped). Two existing
platform assumptions were excluded after reproducing both on the unchanged
baseline: Unix file mode `0600` and `/external` path separators. All 276 frontend
contract tests passed, as did catalog, people and progressive movie-detail browser
checks on desktop and touch mobile. Security scans and coverage thresholds passed.
