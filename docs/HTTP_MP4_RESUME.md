# Crash-safe direct HTTP/MP4 resume (phase 1)

This change adds narrowly scoped, persistent **byte-range continuation** for
direct MP4 responses that provide an exact full length and a **strong ETag**.

## Behavior

- A direct, static `.mp4` media URL is attempted by the existing HTTP download
  engine first. An existing valid HTTP checkpoint is also resumed first, even
  when the URL path does not end in `.mp4`. Other streams keep yt-dlp as first
  choice, retaining the existing HLS/DASH handling and fallback behavior.
- Each durable queue job writes its own private checkpoint at
  `<media directory>/.downloading/.http-resume/<job-key>/`. A fallback staging
  root is used if the preferred target directory is not writable.
- Metadata includes only format version, hashed logical job/output identity,
  hashed exact stream URL, strong ETag, and expected total bytes. It does not
  contain the source URL itself, headers, credentials, cookies or tokens.
- On process/container restart, the logical queue recovers as before. When the
  same HTTP source is resolved, the new attempt sends `Range: bytes=N-` and
  `If-Range: "<etag>"`.
- Appending only occurs if the server responds with HTTP **206**, a matching
  strong ETag, exact `Content-Range` offset and total, and consistent
  `Content-Length`. Invalid or changed responses trigger a clean new
  download, not concatenation of mismatched files.
- If a full checkpoint was written before a crash but not finalized, the
  existing media validation still runs on the recovered file.
- Fully downloaded bytes are moved to the ordinary isolated attempt staging
  location. Existing audio/video validation and collision-free atomic publish
  remain unchanged. Cancel removes checkpoint state; transient transfer errors
  may retain a resumable partial for a future retry.
- Week-old abandoned checkpoints are eligible for the ordinary bounded
  staging cleanup (with ownership markers and explicit file allowlist).

## Boundaries and rollout

- This is **not** arbitrary hoster resume. Signed/expiring URLs often change,
  and their previous checkpoints will not be reused with a different URL.
- HLS/DASH fragments and opaque yt-dlp downloads have no new persistent
  segment-recovery contract in phase 1. yt-dlp may have its own retry behavior,
  but per-attempt staging is still isolated.
- Servers without a strong ETag and a known byte length are downloaded
  normally without cross-restart byte reuse. Invalid responses are never
  appended, even if the file sizes happen to match.
- The new staging files occupy real disk space until successfully published,
  explicitly cancelled or safely expired. Keep sufficient media-volume
  headroom and existing backup/recovery policy.
- Phase 1 adds no web UI controls, no API changes, no provider selection
  changes and no changes to user media mounts.
- A controlled NAS test with a range-capable HTTP fixture is still needed
  before promotion to Stable.

Focused tests: `tests/test_http_resume.py`. The CI job has a short hard timeout
instead of bringing back the removed full Python coverage suite.
