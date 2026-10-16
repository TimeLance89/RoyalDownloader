# Responsive browsing while background checks are slow

Slow NAS writes previously held session/subscription locks that some asynchronous
HTTP handlers and WebSocket checks acquired directly on Uvicorn's event loop.
Controlled reproductions delayed unrelated health replies by the entire storage
delay. Auth/profile routes now run as synchronous FastAPI worker endpoints;
subscription snapshots, personal context reads, session revalidation and initial
WebSocket snapshots also run outside the event loop. Live events are buffered in
the existing bounded connection queue while the initial snapshot is collected.

Interactive Jellyfin reads use four dedicated workers, with at most twelve
unfinished distinct requests. Matching overlapping requests share one result.
Overload returns an explicit temporary 503 rather than adding unlimited work to
the HTTP/auth/static-file worker pool. Ownership and stale/error semantics remain
unchanged; an unavailable check is never reported as confirmed absence.

Full series enrichment uses two workers and at most eight unfinished distinct
jobs across catalog, People and Monster detail entry points. Finished results
remain available for five seconds so retries can retrieve them. The web client
opts into `progressive: true`: after a two-second HTTP wait it receives
`series_details_pending`, waits one second and retrieves the same work. Closing
or switching the detail view aborts polling. Queue overload uses
`series_details_busy`. Callers that omit `progressive` keep waiting for their
completed response. Pending retries never cancel a result needed by another view.

Local inventory scans share four file-probe workers. Each scan submits at most
four files at a time. Concurrent validation of the same cache/path/size/mtime
shares a future, and changed file signatures still trigger fresh verification.
Existing content validation, ownership and download safety rules are retained.

These changes address reproducible blocking/resource-amplification paths. They
do not establish which path caused the reported production Cloudflare 502, nor
prove that its origin was not a process crash, OOM or upstream connection failure.
No NAS configuration or live deployment is part of this change.

Validation:

```text
python -m pytest -q tests/test_browse_responsiveness.py tests/test_series_detail_work.py tests/test_websocket_manager.py tests/test_api_auth_router.py tests/test_saved_media.py tests/test_watchlist_inbox_payload.py
node --test tests/frontend/detail-loader.test.mjs
node tests/frontend/series-inventory-retry-browser.cjs
```
