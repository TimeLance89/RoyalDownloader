let hlsLibrary;

function loadHls(document) {
  if (document.defaultView.Hls) return Promise.resolve(document.defaultView.Hls);
  if (hlsLibrary) return hlsLibrary;
  hlsLibrary = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "/vendor/hls.js/hls.min.js";
    script.onload = () => resolve(document.defaultView.Hls);
    script.onerror = () => { script.remove(); hlsLibrary = null; reject(new Error("Videoplayer konnte nicht geladen werden.")); };
    document.head.append(script);
  });
  return hlsLibrary;
}

/** One Jellyfin timeline per item; seeking requests segments within that session. */
export function createMovieStream(video, { document, client, failed, prepared, starting = () => {}, positionReady = () => {} }) {
  let sequence = 0, seekSequence = 0, session, hls, target = 0, metadataListener, stallTimer, detachStall, pendingSeek = null, resumeAfterSeek = false, armStall, restartHls;

  let seekWrites = Promise.resolve();

  function release(value) {
    if (value) void client.delete(`/api/media-center/playback/${value.id}`, { keepalive: true }).catch(() => {});
  }

  function close() {
    sequence++;
    seekSequence++;
    pendingSeek = null;
    clearTimeout(stallTimer);
    stallTimer = null;
    detachStall?.();
    detachStall = null;
    hls?.destroy();
    hls = null;
    restartHls = null;
    if (metadataListener) video.removeEventListener("loadedmetadata", metadataListener);
    metadataListener = null;
    video.pause();
    video.removeAttribute("src");
    video.load();
    release(session);
    session = null;
  }

  async function open(params, seconds, autoplay, forceTranscode = false) {
    close();
    const current = sequence;
    target = seconds;
    starting(seconds);
    const recover = () => {
      if (current !== sequence) return;
      if (forceTranscode) { failed(); return; }
      const position = pendingSeek ?? (video.readyState > 0 && Number.isFinite(video.currentTime) ? video.currentTime : target);
      void open(params, position, autoplay || !video.paused, true);
    };
    const watch = () => {
      if (stallTimer) return;
      stallTimer = setTimeout(() => {
        stallTimer = null;
        if (current === sequence && (video.readyState < 3 || video.seeking)) recover();
      }, 60_000);
    };
    armStall = watch;
    const ready = () => { clearTimeout(stallTimer); stallTimer = null; };
    try {
      const result = await client.post(`/api/media-center/movies/session?${params}${forceTranscode ? "&force_transcode=true" : ""}`, {}, { timeoutMs: 25_000 });
      if (current !== sequence) { release(result); return; }
      session = result;
      prepared(result);
      video.preload = "auto";
      video.addEventListener("waiting", watch);
      video.addEventListener("seeking", watch);
      video.addEventListener("playing", ready);
      const mediaError = () => { if (!hls) recover(); };
      video.addEventListener("error", mediaError);
      detachStall = () => {
        video.removeEventListener("waiting", watch);
        video.removeEventListener("seeking", watch);
        video.removeEventListener("playing", ready);
        video.removeEventListener("error", mediaError);
      };
      const Hls = result.mode === "hls" ? await loadHls(document) : null;
      if (current !== sequence) return;
      if (result.mode === "hls" && !Hls?.isSupported() && !video.canPlayType("application/vnd.apple.mpegurl")) {
        throw new Error("Dieser Browser unterstützt das Videoformat nicht.");
      }
      if (Hls?.isSupported()) {
        restartHls = (position, resume) => {
          hls?.destroy();
          pendingSeek = position > 0 ? position : null;
          resumeAfterSeek = resume;
          hls = new Hls({ startPosition: Math.max(0, position - 18), maxBufferLength: 30, maxMaxBufferLength: 30, backBufferLength: Infinity, lowLatencyMode: false, enableWorker: true });
          const activeHls = hls;
          hls.on(Hls.Events.FRAG_BUFFERED, () => {
            if (current !== sequence || activeHls !== hls || pendingSeek === null) return;
            for (let i = 0; i < video.buffered.length; i++) {
              if (video.buffered.start(i) <= pendingSeek && video.buffered.end(i) > pendingSeek + 0.1) {
                const position = pendingSeek;
                pendingSeek = null;
                video.currentTime = position;
                positionReady(position);
                if (resumeAfterSeek) void video.play().catch(() => {});
                break;
              }
            }
          });
          let recovered = false;
          hls.on(Hls.Events.ERROR, (_event, data) => {
            if (current !== sequence || activeHls !== hls || !data.fatal) return;
            if (data.type === Hls.ErrorTypes.MEDIA_ERROR && !recovered) {
              recovered = true;
              hls.recoverMediaError();
            } else recover();
          });
          hls.loadSource(result.url);
          hls.attachMedia(video);
          if (resume && pendingSeek === null) void video.play().catch(() => {});
        };
        restartHls(target, autoplay);
      } else {
        metadataListener = () => {
          metadataListener = null;
          if (current === sequence && target > 0) video.currentTime = target;
        };
        video.addEventListener("loadedmetadata", metadataListener, { once: true });
        video.src = result.url;
        video.load();
      }
      if (autoplay) { watch(); if (pendingSeek === null) void video.play().catch(() => {}); }
    } catch {
      if (current === sequence) failed();
    }
  }

  return {
    open, close,
    get pendingPosition() { return pendingSeek; },
    get managesErrors() { return Boolean(session); },
    seek(seconds) {
      target = seconds;
      if (hls) {
        let buffered = false;
        for (let i = 0; i < video.buffered.length; i++) {
          if (video.buffered.start(i) <= seconds && video.buffered.end(i) > seconds + 0.1) buffered = true;
        }
        if (!buffered) {
          resumeAfterSeek = pendingSeek !== null ? resumeAfterSeek : !video.paused;
          pendingSeek = seconds;
          starting(seconds);
          video.pause();
          // Jellyfin's virtual playlist can change segment durations after encoding.
          // Refresh its timeline for an unbuffered seek while keeping the server session.
          const current = sequence, seekId = ++seekSequence, active = session;
          hls.stopLoad();
          clearTimeout(stallTimer);
          stallTimer = null;
          seekWrites = seekWrites.catch(() => {}).then(async () => {
            if (current !== sequence || seekId !== seekSequence) return;
            await client.post(`/api/media-center/playback/${active.id}/seek`, {}, { timeoutMs: 15_000 });
            if (current !== sequence || seekId !== seekSequence) return;
            restartHls(seconds, resumeAfterSeek);
            armStall?.();
          }).catch(() => { if (current === sequence && seekId === seekSequence) failed(); });
          return;
        }
      }
      pendingSeek = null;
      if (video.readyState > 0) video.currentTime = seconds;
    },
    heartbeat() {
      if (session) void client.post(`/api/media-center/playback/${session.id}/heartbeat`, {}, { timeoutMs: 5_000 }).catch(() => {});
    },
  };
}
