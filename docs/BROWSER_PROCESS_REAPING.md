# Browser subprocess reaping — issue #590

## Findings and limits of attribution

The reported NAS snapshot contains 881 zombies parented by Royal's Python,
including 668 chromium and 186 chrome_crashpad processes. The original container
ran Python as PID 1 without Docker Init. A newly recreated container with
`init: true` showed no Royal zombies in a short observation; that is not yet a
long-duration verification.

Confirmed code defects:

- Both SerienStream cleanup paths killed a child after a wait timeout without a
  final wait, and could skip the second handle when signalling raised.
- VOE failed-start cleanup could close a nodriver event loop and discard its
  browser/thread references before stopping the partial browser. Startup timeout
  retries could overlap an owner that had not exited. Normal close also cleared
  ownership after a bounded join without checking whether the thread survived.
- nodriver 0.50.3 `Browser.stop()` schedules connection closure without awaiting
  it and terminates/kills without awaiting the subprocess. Royal's previous
  fallback had unbounded post-kill waits and incomplete startup coverage.
- Callback exceptions in a yt-dlp output loop could escape to the download
  result handler without waiting for its direct child. Normal yt-dlp completion
  already waited; updater/ffprobe/ffmpeg `subprocess.run` calls already benefit
  from the standard library's wait/timeout cleanup.
- Python PID 1 does not automatically reap detached Chromium/Crashpad descendants
  it did not create with Popen/asyncio. Fixing direct-child waits alone cannot
  solve that adoption problem.

These facts explain plausible accumulation paths. They do not identify the
individual source of every one of the 854 browser zombies in the snapshot.
`Popen.poll()` itself can reap an exited direct child; skipping a second wait
when poll returned an exit code was not evidence of a zombie on its own.

## Ownership and cleanup

`core.owned_process` implements bounded terminate/wait/kill/wait and async
cleanup, including already-exited children and signalling/wait failures. The
owner keeps a handle when cleanup cannot complete, so repeated close can retry
rather than silently losing ownership. Async browser pipes are drained in bounded
chunks and discarded, not retained or logged; an exited transport is closed.

Local browser/Xvfb and yt-dlp launches create private POSIX sessions. Group
signals require a marked, still-live child whose group ID equals its PID, and
never target Royal's own process group. No global name-based kills or global
`waitpid(-1)` reaper are installed. The nodriver asyncio proxy is module-local:
Royal's main loop, normal subprocess spawns and running downloads are unaffected.
Remote CDP adapters keep closing only their owned target; they never kill the
shared remote browser. Windows keeps direct-handle cleanup and the downloader's
existing task-tree cancellation behavior.

The VOE thread always executes cleanup in its own event loop, including partial
startup, token setup errors, cancellation and unexpected loop exit. Pool reuse
and delayed CDP startup recovery remain. A live cleanup owner cannot be replaced
by a retry. Waits are bounded (normally up to three seconds each, plus two seconds
for connection close and one second for task cancellation); the caller checks
the 15-second thread join and retains references on failure. Persistent OS-level
kill/wait failures remain visible rather than spawning additional browsers.

No routine delay is added to healthy extraction. Stops return immediately when
the child exits; no background process-table sweeps were added. Download
concurrency, local inventory's four probe workers, media validation and PR #589's
persistent Jellyfin coordinator remain unchanged. There is no demonstrated
ffprobe loop to justify throttling it.

## Init and updates

The image installs Debian's small `tini` package and uses
`ENTRYPOINT ["/usr/bin/tini", "-s", "--"]`. Thus normal image launches have an
init even when an older external Compose file omitted `init: true`. Subreaper
mode also works when an outer Docker Init is present. Docker Compose's existing
`init: true` remains, including the isolated browser service whose entrypoint is
overridden. Tini forwards signals and reaps adopted descendants; it does not
compete with Python for children that are still owned by Python.

This image change requires an image update and normal container recreation.
Updating only Python source inside an older image does not install Tini or change
that image's entrypoint. Existing settings, media mounts, secrets and update
layout stay intact. No live NAS was changed by this PR. Do not delete volumes,
run `compose down -v`, reset profiles or change productive data directories as a
cleanup workaround. Check the existing configuration/backups before the usual
operator-managed recreation. Zombie processes cannot be killed again; they must
be waited by their parent/init.

Native Linux installations rely on the host's init for adopted descendants;
Royal does not make its own Python process a global subreaper. Arbitrary custom
entrypoint overrides must retain a suitable init themselves.

## Aggregate diagnostics

The existing admin runtime diagnostics expose `owned_process_cleanup`:
`started`, `reaped`, `cleanup_errors`, `open_handles`. Counts are per Royal
process lifetime and include locally managed browser/Xvfb/yt-dlp handles, not
remote CDP tabs or all OS processes. They are not a census of live children:
`open_handles` also includes handles retained after failed cleanup. No new
command lines, PIDs, URLs, cookies or raw stderr are exposed by these counters.

## Tests

`tests/test_owned_process.py` covers terminate/wait/kill/wait, early exit,
exceptions, retained handles, repeated close, partial Xvfb/Chromium startup,
async timeout/cancellation, module-local launch interception, group ownership,
VOE startup/setup cancellation, pool reuse and thread/listener shutdown, failed
download callbacks, and sidecar signal cleanup. Existing SerienStream, remote
browser, download/queue, updater and Jellyfin tests run alongside it.

On Linux, a separate test supervisor adopts and explicitly waits only its known
fixture grandchildren; it never changes pytest/Royal's adoption policy. Twelve
synthetic browser-like trees mix same-group and detached descendants while a
foreign child stays alive. The image CI additionally runs the same offline probe
under the image's actual Tini **without** Docker `--init`, read-only and without
network access. Every owned descendant must disappear; repeated cycles cannot
leave a linearly growing zombie population. No external streaming site is used.

References: [Python subprocess waits and timeout handling](https://docs.python.org/3.12/library/subprocess.html),
[asyncio subprocess ownership and pipe handling](https://docs.python.org/3.12/library/asyncio-subprocess.html),
[Tini adoption/subreaper behavior](https://github.com/krallin/tini#subreaping).
