"""Hoster extraction and cross-provider source resolution services."""
# Runtime service publication is intentionally invisible to static name resolution.
# ruff: noqa: F821

from application_services.runtime import (
    import_backend_namespace,
    publish_service,
)

globals().update(import_backend_namespace())


class _HosterResult:
    """Ergebnis eines Hoster-Extraktionsversuchs für genau einen Movie/Episode."""
    __slots__ = (
        "stream_info", "hoster_used", "hoster_url_used", "source_hoster_url",
        "referer", "origin", "gated", "provider", "content_language", "quality",
        "resolved_from_cache",
    )

    def __init__(self):
        self.stream_info = None
        self.hoster_used = ""
        self.hoster_url_used = ""
        self.source_hoster_url = ""
        self.referer = "https://filmpalast.to/"
        self.origin = ""
        self.gated = False   # serienstream Captcha-Gate war aktiv
        self.provider = ""
        self.content_language = ""
        self.quality = ""
        self.resolved_from_cache = False


def _extract_from_movie(
    movie: FilmpalastMovie,
    unsupported_domains: set,
    excluded_hoster_urls: Optional[set] = None,
    barren_hoster_urls: Optional[set] = None,
) -> _HosterResult:
    """Probiert der Reihe nach die Hoster eines Movies (nach hoster_intel-Ranking)
    durch, löst serienstream-Redirects lazy auf und liefert den ersten nutzbaren
    Stream. Funktioniert für alle konfigurierten Katalogquellen, da Nicht-s.to-
    Hoster einfach ihre direkte URL verwenden."""
    res = _HosterResult()
    res.provider = _movie_provider(movie)
    if (
        res.provider == "serienstream"
        and not state.provider_health.request_allowed("serienstream")
    ):
        # Direkte/cached Hoster duerfen weiterlaufen. Falls sie scheitern, muss
        # der logische Job aber bis zur Provider-Probe vorgemerkt bleiben.
        res.gated = True
    res.content_language = _movie_content_language(movie)
    session = state.fp_scraper.session._curl if state.fp_scraper else None
    excluded_hoster_urls = excluded_hoster_urls or set()
    # Ergebnislose Extraktionen dieses Laufs. Ein Embed, das schon einmal die
    # komplette Browser-Kette ohne Stream-URL durchlaufen hat, liefert Sekunden
    # später dasselbe Nichts – kostet aber erneut die volle Wartezeit.
    if barren_hoster_urls is None:
        barren_hoster_urls = set()

    ranked_hosters = state.hoster_intel.rank(movie.hosters)
    preferred_quality_value = getattr(movie, "_preferred_quality", None)
    if preferred_quality_value is not None:
        preferred_quality = str(preferred_quality_value or "").strip().casefold()
        ranked_hosters.sort(
            key=lambda hoster: str(hoster.quality or "").strip().casefold() != preferred_quality
        )
    for hoster in ranked_hosters:
        if not hoster.url:
            continue
        if hoster.url in excluded_hoster_urls:
            log(f"  Überspringe {hoster.name}: Download zuvor fehlgeschlagen", "warn")
            continue
        if hoster.url in barren_hoster_urls:
            log(f"  Überspringe {hoster.name}: lieferte zuvor keine Stream-URL", "warn")
            continue
        name = hoster.name.lower()
        if hoster.url in unsupported_domains:
            log(f"  Überspringe {hoster.name}: Link nicht unterstützt", "warn")
            continue
        cooldown, _reason = state.hoster_intel.cooldown(
            hoster.url, hoster_name=hoster.name,
        )
        if cooldown:
            minutes = max(1, (cooldown + 59) // 60)
            log(
                f"  Überspringe {hoster.name}: nach Ausfällen noch "
                f"{minutes} Min. pausiert",
                "warn",
            )
            continue
        res.hoster_used = hoster.name
        res.quality = str(getattr(hoster, "quality", "") or "").strip()
        res.source_hoster_url = hoster.url
        res.content_language = _movie_content_language(
            movie,
            str(getattr(hoster, "language", "") or ""),
        )
        log(f"  Versuche Hoster: {hoster.name}")

        # serienstream.to liefert Hoster als lazy /r?t=-Redirect. Erst JETZT,
        # für genau diesen Versuch, zur echten Embed-URL auflösen. So bleibt
        # die Zahl der s.to-Requests minimal (meist genau 1) und das Captcha
        # wird gar nicht erst provoziert. Fällt ein Hoster durch, wird nur der
        # nächste aufgelöst.
        was_sto = SerienstreamScraper.is_redirect_url(hoster.url)
        play_url = hoster.url
        resolved_by_provider = False
        if was_sto:
            cached_target = state.resolved_link_cache.get(hoster.url)
            if cached_target:
                play_url = cached_target
                res.resolved_from_cache = True
                # Der bekannte Ziel-Link ist weiterhin nutzbar, obwohl keine
                # neue Provider-Anfrage erlaubt ist. Merken, dass ein spaeterer
                # Fehlschlag trotzdem bis zur naechsten Probe warten muss.
                if not state.provider_health.request_allowed("serienstream"):
                    res.gated = True
                log(f"  {hoster.name}: bereits aufgelösten Hoster-Link verwenden")
            else:
                # Ein Cache-Treffer benötigt keinen Provider-Request und darf
                # deshalb auch im Cooldown weiter zum Hoster. Nur Cache-Misses
                # durchlaufen den Circuit-Breaker.
                if not state.provider_health.request_allowed("serienstream"):
                    res.gated = True
                    break
                sto = get_sto_scraper()
                with state.sto_lock:
                    # Double-check nach dem Lock: Ein paralleler Worker kann
                    # denselben Redirect inzwischen bereits aufgeloest haben.
                    locked_target = state.resolved_link_cache.get(hoster.url)
                    if locked_target:
                        play_url = locked_target
                        res.resolved_from_cache = True
                    else:
                        # Zwischen Statusprüfung und Lock kann eine andere
                        # Anfrage das Gate erkannt haben. Vor dem Redirect
                        # deshalb atomar noch einmal prüfen.
                        if not state.provider_health.request_allowed("serienstream"):
                            res.gated = True
                            break
                        # Ist das Captcha-Gate aktiv, sind ALLE Hoster blockiert
                        # – nicht weiter hämmern, sondern sofort abbrechen.
                        if sto.gated:
                            _mark_serienstream_blocked(
                                sto.last_block_reason or "captcha_gate",
                                "SerienStream-Gate ist bereits aktiv",
                            )
                            res.gated = True
                            break
                        play_url = sto.resolve_play_url(hoster.url, referer=movie.url)
                        if play_url:
                            resolved_by_provider = True
                            state.resolved_link_cache.put(hoster.url, play_url)
                if not play_url:
                    if sto.gated:
                        _mark_serienstream_blocked(
                            sto.last_block_reason or "captcha_gate",
                            "SerienStream-Redirect-Gate blockiert",
                        )
                        res.gated = True
                        break
                    log(f"  {hoster.name}: S.to-Link nicht auflösbar – nächster Hoster", "warn")
                    continue
                if (
                    resolved_by_provider
                    and state.provider_health.status("serienstream")["failure_count"]
                ):
                    state.provider_health.mark_success("serienstream")
            name = _canonical_hoster_name(hoster.name, play_url)
            if play_url in unsupported_domains:
                log(f"  Überspringe {hoster.name}: Link nicht unterstützt", "warn")
                continue
            if play_url in barren_hoster_urls:
                # s.to rotiert die Redirect-URLs, das Embed-Ziel bleibt gleich.
                log(f"  Überspringe {hoster.name}: lieferte zuvor keine Stream-URL", "warn")
                continue
        name = _canonical_hoster_name(hoster.name, play_url)
        res.hoster_url_used = play_url
        cooldown, _reason = state.hoster_intel.cooldown(
            play_url, hoster_name=hoster.name,
        )
        if cooldown:
            minutes = max(1, (cooldown + 59) // 60)
            log(
                f"  Überspringe {hoster.name}: Zielhost noch "
                f"{minutes} Min. pausiert",
                "warn",
            )
            continue

        if name == "voe":
            if state.voe_pool is None:
                log("Starte Browser-Pool für VOE-Fallback …")
                try:
                    state.voe_pool = VOEBrowserPool(log_cb=log)
                except Exception as exc:
                    log(f"Browser-Pool konnte nicht starten: {exc}", "warn")
                    state.voe_pool = None
                    continue
            check = pre_check_voe(play_url, session=session)
            if check == VOE_NOT_FOUND:
                log("  VOE 404 – nächster Hoster", "warn")
                continue
            try:
                res.stream_info = extract_stream_url(
                    play_url, session=session, log_cb=log, pool=state.voe_pool,
                )
            except Exception as exc:
                log(f"  VOE-Extraktion fehlgeschlagen: {exc}", "warn")
                res.stream_info = None
            parsed = urlparse(play_url)
            res.referer = play_url
            res.origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else "https://voe.sx"
        elif (
            name.startswith("filmfrei24")
            or provider_for_value(movie.url) == "filmfrei24"
        ):
            # Eigener öffentlicher VOD-HLS-Stream; kein Embed- oder
            # Browser-Extraktor nötig. Der Scraper liefert zuerst den offiziellen
            # Proxy und danach den direkten TV-Endpunkt als Ausweichroute.
            res.stream_info = (play_url, "hls")
            res.referer = movie.url or f"{FILMFREI24_BASE_URL}/"
            res.origin = FILMFREI24_BASE_URL
        elif name in ("moflix", "veev"):
            embed_referer = (
                movie.url if provider_for_value(movie.url) == "megakino"
                else "https://moflix-stream.xyz/"
            )
            try:
                res.stream_info = extract_stream_url(
                    play_url, session=session, log_cb=log, pool=None,
                    referer=embed_referer,
                )
                if res.stream_info is None:
                    if state.embed_pool is None:
                        log("Starte Browser-Pool für Embed-Fallback …")
                        try:
                            state.embed_pool = VOEBrowserPool(log_cb=log, setup_voe=False)
                        except Exception as exc:
                            log(f"Browser-Pool konnte nicht starten: {exc}", "warn")
                            state.embed_pool = None
                            continue
                    res.stream_info = extract_stream_url(
                        play_url, session=session, log_cb=log, pool=state.embed_pool,
                        referer=embed_referer,
                        browser_wait_seconds=12,
                    )
            except Exception as exc:
                log(f"  Embed-Extraktion fehlgeschlagen: {exc}", "warn")
                res.stream_info = None
            parsed = urlparse(play_url)
            res.referer = play_url
            res.origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else ""
        elif name == "kinoger":
            referer = movie.url or "https://kinoger.com/"
            try:
                res.stream_info = extract_stream_url(
                    play_url, session=session, log_cb=log, pool=None,
                    referer=referer,
                )
                if res.stream_info is None:
                    if state.embed_pool is None:
                        log("Starte Browser-Pool für KinoGer-Mirror …")
                        try:
                            state.embed_pool = VOEBrowserPool(log_cb=log, setup_voe=False)
                        except Exception as exc:
                            log(f"Browser-Pool konnte nicht starten: {exc}", "warn")
                            state.embed_pool = None
                            continue
                    res.stream_info = extract_stream_url(
                        play_url, session=session, log_cb=log, pool=state.embed_pool,
                        referer=referer,
                        browser_wait_seconds=12,
                    )
            except Exception as exc:
                log(f"  KinoGer-Mirror fehlgeschlagen: {exc}", "warn")
                res.stream_info = None
            parsed = urlparse(play_url)
            res.referer = play_url
            res.origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else ""
        elif name == "doodstream":
            try:
                res.stream_info = extract_doodstream_url(play_url, session=session, log_cb=log)
            except Exception as exc:
                log(f"  Doodstream-Extraktion fehlgeschlagen: {exc}", "warn")
                res.stream_info = None
            parsed = urlparse(play_url)
            res.referer = f"{parsed.scheme}://{parsed.netloc}/"
            res.origin = f"{parsed.scheme}://{parsed.netloc}"
        elif name == "vidara":
            # VIDARA (vidmatrixa.com u.a.) – von yt-dlp nicht unterstützt, eigener
            # Extraktor (POST /api/stream → streaming_url, HLS).
            try:
                res.stream_info = extract_vidara_url(play_url, session=session, log_cb=log)
            except Exception as exc:
                log(f"  VIDARA-Extraktion fehlgeschlagen: {exc}", "warn")
                res.stream_info = None
            parsed = urlparse(play_url)
            res.referer = f"{parsed.scheme}://{parsed.netloc}/"
            res.origin = f"{parsed.scheme}://{parsed.netloc}"
        elif name == "vidsonic":
            # Vidsonic (vidsonic.net) – von yt-dlp nicht unterstützt, eigener
            # Extraktor (hex-kodierte + umgekehrte URL im HTML, HLS).
            try:
                res.stream_info = extract_vidsonic_url(play_url, session=session, log_cb=log)
            except Exception as exc:
                log(f"  Vidsonic-Extraktion fehlgeschlagen: {exc}", "warn")
                res.stream_info = None
            parsed = urlparse(play_url)
            res.referer = f"{parsed.scheme}://{parsed.netloc}/"
            res.origin = f"{parsed.scheme}://{parsed.netloc}"
        elif name == "firestream":
            try:
                res.stream_info = extract_firestream_url(play_url, session=session, log_cb=log)
            except Exception as exc:
                log(f"  FireStream-Extraktion fehlgeschlagen: {exc}", "warn")
                res.stream_info = None
            parsed = urlparse(play_url)
            res.referer = f"{parsed.scheme}://{parsed.netloc}/"
            res.origin = f"{parsed.scheme}://{parsed.netloc}"
        elif provider_for_value(movie.url) == "megakino":
            # MegaKino nimmt regelmaessig neue Player-Domains auf. Erst wird
            # ohne Browser nach direkten HLS-/MP4-Quellen gesucht, danach faengt
            # der gemeinsame Embed-Pool Medienrequests ab. Als letzter Weg darf
            # yt-dlp die unveraenderte Player-URL versuchen.
            referer = movie.url or "https://megakino.org/"
            try:
                res.stream_info = extract_stream_url(
                    play_url, session=session, log_cb=log, pool=None,
                    referer=referer,
                )
                if res.stream_info is None:
                    if state.embed_pool is None:
                        log("Starte Browser-Pool für MegaKino-Hoster …")
                        try:
                            state.embed_pool = VOEBrowserPool(log_cb=log, setup_voe=False)
                        except Exception as exc:
                            log(f"Browser-Pool konnte nicht starten: {exc}", "warn")
                            state.embed_pool = None
                    if state.embed_pool is not None:
                        res.stream_info = extract_stream_url(
                            play_url, session=session, log_cb=log, pool=state.embed_pool,
                            referer=referer,
                            browser_wait_seconds=10,
                        )
            except Exception as exc:
                log(f"  MegaKino-Hoster fehlgeschlagen: {exc}", "warn")
                res.stream_info = None
            if res.stream_info is None:
                res.stream_info = (play_url, "web")
            parsed = urlparse(play_url)
            res.referer = play_url
            res.origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else ""
        elif provider_for_value(movie.url) == "sflix":
            # Die SFlix-Player (UpCloud/Vidsrc/…) sind generische Embed-Seiten.
            # Direkte Regex-Auflösung bleibt billig; der gemeinsame Browser-Pool
            # fängt als Fallback den signierten HLS-Request des Players ab.
            referer = movie.url or f"{SFLIX_BASE_URL}/"
            try:
                res.stream_info = extract_stream_url(
                    play_url,
                    session=session,
                    log_cb=log,
                    pool=None,
                    referer=referer,
                )
                if res.stream_info is None:
                    if state.embed_pool is None:
                        log("Starte Browser-Pool für SFlix-Hoster …")
                        try:
                            state.embed_pool = VOEBrowserPool(
                                log_cb=log,
                                setup_voe=False,
                            )
                        except Exception as exc:
                            log(
                                f"Browser-Pool konnte nicht starten: {exc}",
                                "warn",
                            )
                            state.embed_pool = None
                    if state.embed_pool is not None:
                        res.stream_info = extract_stream_url(
                            play_url,
                            session=session,
                            log_cb=log,
                            pool=state.embed_pool,
                            referer=referer,
                            browser_wait_seconds=12,
                        )
            except Exception as exc:
                log(f"  SFlix-Hoster fehlgeschlagen: {exc}", "warn")
                res.stream_info = None
            if res.stream_info is None:
                res.stream_info = (play_url, "web")
            res.referer = referer
            res.origin = SFLIX_BASE_URL
        elif provider_for_value(movie.url) == "ridomovies":
            # Closeload/Rapidrame sind generische Embed-Player. Erst die
            # günstige HTML-Auflösung probieren, dann den gemeinsamen
            # Browser-Pool für signierte Medienrequests verwenden.
            referer = movie.url or f"{RIDOMOVIES_BASE_URL}/"
            try:
                res.stream_info = extract_stream_url(
                    play_url,
                    session=session,
                    log_cb=log,
                    pool=None,
                    referer=referer,
                )
                if res.stream_info is None:
                    if state.embed_pool is None:
                        log("Starte Browser-Pool für Ridomovies-Hoster …")
                        try:
                            state.embed_pool = VOEBrowserPool(
                                log_cb=log,
                                setup_voe=False,
                            )
                        except Exception as exc:
                            log(
                                f"Browser-Pool konnte nicht starten: {exc}",
                                "warn",
                            )
                            state.embed_pool = None
                    if state.embed_pool is not None:
                        res.stream_info = extract_stream_url(
                            play_url,
                            session=session,
                            log_cb=log,
                            pool=state.embed_pool,
                            referer=referer,
                            browser_wait_seconds=12,
                        )
            except Exception as exc:
                log(f"  Ridomovies-Hoster fehlgeschlagen: {exc}", "warn")
                res.stream_info = None
            if res.stream_info is None:
                res.stream_info = (play_url, "web")
            res.referer = referer
            res.origin = RIDOMOVIES_BASE_URL
        elif provider_for_value(movie.url) == "mkissa":
            # MKissa liefert direkte Streams und generische Anime-Embeds.
            # Direkte Medien bleiben unangetastet; Embed-Player durchlaufen
            # zunächst die billige Extraktion und danach den Browser-Pool.
            referer = f"{MKISSA_BASE_URL}/"
            parsed = urlparse(play_url)
            if parsed.path.casefold().endswith((".m3u8", ".mp4")):
                res.stream_info = (play_url, "web")
            else:
                try:
                    res.stream_info = extract_stream_url(
                        play_url,
                        session=session,
                        log_cb=log,
                        pool=None,
                        referer=referer,
                    )
                    if res.stream_info is None:
                        if state.embed_pool is None:
                            log("Starte Browser-Pool für MKissa-Hoster …")
                            try:
                                state.embed_pool = VOEBrowserPool(
                                    log_cb=log,
                                    setup_voe=False,
                                )
                            except Exception as exc:
                                log(
                                    f"Browser-Pool konnte nicht starten: {exc}",
                                    "warn",
                                )
                                state.embed_pool = None
                        if state.embed_pool is not None:
                            res.stream_info = extract_stream_url(
                                play_url,
                                session=session,
                                log_cb=log,
                                pool=state.embed_pool,
                                referer=referer,
                                browser_wait_seconds=12,
                            )
                except Exception as exc:
                    log(f"  MKissa-Hoster fehlgeschlagen: {exc}", "warn")
                    res.stream_info = None
                if res.stream_info is None:
                    res.stream_info = (play_url, "web")
            res.referer = referer
            res.origin = "https://mkissa.to"
        else:
            # Generischer Hoster (Streamtape/Vidoza/Vidmoly/Filemoon/…):
            # yt-dlp probieren lassen. Referer = eigene Hoster-Domain
            # (bei s.to-Auflösung), sonst filmpalast wie gehabt.
            res.stream_info = (play_url, "web")
            if was_sto:
                parsed = urlparse(play_url)
                res.referer = f"{parsed.scheme}://{parsed.netloc}/" if parsed.netloc else "https://filmpalast.to/"
            else:
                res.referer = "https://filmpalast.to/"
            res.origin = ""

        if res.stream_info:
            stream_url, _stream_type = res.stream_info
            log(f"  Prüfe Hoster: {hoster.name}")
            ok, probe_msg = probe_stream_url(stream_url, referer=res.referer, origin=res.origin)
            state.hoster_intel.record_probe(
                play_url, ok, probe_msg, hoster_name=hoster.name,
            )
            if not ok:
                log(f"  {hoster.name} nicht nutzbar: {probe_msg}", "warn")
                if "unsupported url" in probe_msg.lower():
                    unsupported_domains.add(play_url)
                res.stream_info = None
                continue
            break
        else:
            # Der Extraktor lief vollständig durch, ohne eine Stream-URL zu
            # finden. Innerhalb dieses Laufs nicht erneut versuchen.
            barren_hoster_urls.add(hoster.url)
            if play_url:
                barren_hoster_urls.add(play_url)

    return res


def find_movie_source_fallbacks(
    movie: FilmpalastMovie,
    selected_slug: str,
    excluded_urls: set,
) -> List[FilmpalastMovie]:
    """Sucht denselben Film erst dann bei anderen Katalogquellen, wenn alle
    Hoster des ausgewählten Treffers zur Laufzeit gescheitert sind."""
    title = clean_movie_title(movie.title)
    wanted = _norm_title(title)
    wanted_year = str(movie.year or "")
    if not wanted:
        return []
    log(f"  Suche alternative Filmquellen für «{title}» …", "warn")
    alternatives: List[FilmpalastMovie] = []
    seen_urls = set(excluded_urls)
    try:
        candidates = search_movie_candidates(title)
    except Exception as exc:
        log(f"  Alternative Filmquellen nicht durchsuchbar: {exc}", "warn")
        return []

    for candidate in candidates:
        if not candidate.is_movie or candidate.slug == selected_slug:
            continue
        if _norm_title(candidate.title) != wanted:
            continue
        candidate_year = str(candidate.year or "")
        if wanted_year and candidate_year and candidate_year != wanted_year:
            continue
        if candidate.url in seen_urls:
            continue
        try:
            loaded = state.fp_movies.get(candidate.slug) or load_movie_for_slug(candidate.slug)
        except Exception as exc:
            log(f"  Filmquelle {candidate.title} nicht ladbar: {exc}", "warn")
            continue
        if not loaded or not loaded.hosters or _norm_title(loaded.title) != wanted:
            continue
        loaded_year = str(loaded.year or candidate_year or "")
        if wanted_year and loaded_year and loaded_year != wanted_year:
            continue
        if loaded.url in seen_urls:
            continue
        state.fp_movies[candidate.slug] = loaded
        seen_urls.add(loaded.url)
        alternatives.append(loaded)
        if len(alternatives) >= 6:
            break

    if alternatives:
        log(f"  {len(alternatives)} alternative Filmquelle(n) vorbereitet.")
    else:
        log("  Keine weitere Filmquelle mit exakt passendem Titel/Jahr gefunden.", "warn")
    return alternatives


def _enqueue_hoster_attempt(
    movie: FilmpalastMovie,
    movie_slug: str,
    out_path: Path,
    result: _HosterResult,
    unsupported_domains: set,
    failed_hoster_urls: set,
    attempt_errors: List[str],
    source_movies: List[FilmpalastMovie],
    source_index: int,
    source_fallbacks_loaded: List[bool],
    refreshed_hoster_urls: set,
    barren_hoster_urls: Optional[set] = None,
    cancelled: Optional[Callable[[], bool]] = None,
    gate_seen: Optional[List[bool]] = None,
    gate_retry: Optional[Callable[[], bool]] = None,
    slow_candidates: Optional[List[tuple]] = None,
    last_resort: bool = False,
    attempt_id: str = "",
):
    """Startet einen Downloadversuch und schaltet bei Laufzeitfehlern auf den
    nächsten Hoster um. Ein logischer Job wird erst nach Erfolg oder nach dem
    letzten Anbieter als abgeschlossen gemeldet."""
    if (cancelled and cancelled()) or not _queue_slug_claimed(movie_slug):
        return False
    gate_seen = gate_seen or [bool(result.gated)]
    gate_seen[0] = gate_seen[0] or bool(result.gated)
    if barren_hoster_urls is None:
        barren_hoster_urls = set()
    if slow_candidates is None:
        slow_candidates = []
    stream_url, stream_type = result.stream_info
    hoster_used = result.hoster_used
    label = f"{movie.title}  ({hoster_used})"
    logical_job = _ensure_queue_job(movie_slug, movie)
    demo_mode = appconfig.demo_mode_enabled()
    logical_attempt_id = attempt_id or str(logical_job.get("attempt_id") or "")
    if attempt_id and logical_job.get("attempt_id") != attempt_id:
        return False
    updated = _update_queue_job(
        movie_slug,
        expected_job_id=logical_job["job_id"],
        expected_attempt_id=logical_attempt_id,
        status="queued",
        title=movie.title,
        provider=result.provider or _movie_provider(movie, movie_slug),
        hoster=hoster_used,
        quality=result.quality,
        content_language=(
            result.content_language
            or _movie_content_language(movie, fallback=movie_slug)
        ),
    )
    if updated is None:
        return False
    log(f"  Stream bereit ({hoster_used}): {stream_url[:60]}…")

    def _attempt_done(ok: bool, msg: str):
        current = _queue_job_for_slug(movie_slug)
        if not current or (
            current.get("job_id") != logical_job["job_id"]
            or current.get("attempt_id") != logical_attempt_id
        ):
            return
        if result.hoster_url_used and not demo_mode:
            state.hoster_intel.record_download(
                result.hoster_url_used,
                ok,
                hoster_name=hoster_used,
                speed_bps=getattr(job, "average_speed_bps", 0),
                failure_kind=getattr(job, "failure_kind", ""),
            )
        if ok:
            accepted = on_job_done(
                True, msg, label, out_path,
                slug=movie_slug,
                job_id=logical_job["job_id"],
                attempt_id=logical_attempt_id,
            )
            terminal = _queue_job_for_id(logical_job["job_id"], include_history=True)
            if (
                accepted
                and terminal
                and terminal.get("attempt_id") == logical_attempt_id
                and terminal.get("status") == "completed"
                and not parse_episode_slug(movie_slug)
                and not demo_mode
            ):
                _movie_subscription_download_finished(movie_slug, out_path, result.quality)
            return
        if msg == "Abgebrochen":
            on_job_done(False, msg, label, out_path, slug=movie_slug, job_id=logical_job["job_id"], attempt_id=logical_attempt_id)
            return
        if (cancelled and cancelled()) or not _queue_slug_claimed(movie_slug):
            on_job_done(False, "Abgebrochen", label, out_path, slug=movie_slug, job_id=logical_job["job_id"], attempt_id=logical_attempt_id)
            return

        is_slow = getattr(job, "failure_kind", "") == "slow"
        if last_resort:
            final_msg = "; ".join(attempt_errors + [f"Letzte langsame Reserve: {msg}"])
            on_job_done(False, final_msg, label, out_path, slug=movie_slug, job_id=logical_job["job_id"], attempt_id=logical_attempt_id)
            return
        if is_slow:
            source_key = result.source_hoster_url or result.hoster_url_used
            if not any(
                (candidate_result.source_hoster_url or candidate_result.hoster_url_used) == source_key
                for _candidate_movie, candidate_result, _speed in slow_candidates
            ):
                slow_candidates.append((
                    movie,
                    result,
                    float(getattr(job, "average_speed_bps", 0) or 0),
                ))

        # Signierte CDN-Links können zwischen Probe und Download ablaufen. Den
        # gleichen Hoster genau einmal frisch extrahieren, bevor er ausscheidet.
        source_url = result.source_hoster_url
        if not is_slow and source_url and source_url not in refreshed_hoster_urls:
            refreshed_hoster_urls.add(source_url)
            log(f"  {hoster_used}: Link wird einmal frisch aufgelöst …", "warn")
            # Ein abgelaufener Hoster-/CDN-Link darf genau einen Cache-Miss
            # erzeugen. Bei aktivem SerienStream-Cooldown bricht die folgende
            # Extraktion vor jedem Provider-Request ab und nutzt Fallbacks.
            state.resolved_link_cache.invalidate(
                source_url, result.hoster_url_used,
            )
            with state.hoster_extract_lock:
                refreshed = _extract_from_movie(
                    movie,
                    unsupported_domains,
                    excluded_hoster_urls=failed_hoster_urls,
                    barren_hoster_urls=barren_hoster_urls,
                )
            gate_seen[0] = gate_seen[0] or bool(refreshed.gated)
            if refreshed.stream_info and refreshed.stream_info[0] == stream_url:
                # Identischer Link: die Signatur war nicht abgelaufen, der Fehler
                # lag am Abruf selbst. Ein zweiter Versuch scheitert genauso.
                log(
                    f"  {hoster_used}: unveränderter Link – kein zweiter Versuch",
                    "warn",
                )
            elif refreshed.stream_info:
                if _enqueue_hoster_attempt(
                    movie, movie_slug, out_path, refreshed, unsupported_domains,
                    failed_hoster_urls, attempt_errors, source_movies, source_index,
                    source_fallbacks_loaded, refreshed_hoster_urls,
                    barren_hoster_urls, cancelled,
                    gate_seen, gate_retry, slow_candidates, last_resort,
                    attempt_id=logical_attempt_id,
                ):
                    return
                on_job_done(False, "Abgebrochen", label, out_path, slug=movie_slug, job_id=logical_job["job_id"], attempt_id=logical_attempt_id)
                return

        attempt_errors.append(f"{hoster_used}: {msg}")
        if result.source_hoster_url:
            failed_hoster_urls.add(result.source_hoster_url)
        log(f"  {hoster_used}-Download fehlgeschlagen – versuche nächsten Anbieter", "warn")
        on_job_progress(
            -1, f"{hoster_used} ausgefallen · wechsle Anbieter …", label,
            slug=movie_slug, job_id=logical_job["job_id"], attempt_id=logical_attempt_id,
        )

        with state.hoster_extract_lock:
            next_result = _extract_from_movie(
                movie,
                unsupported_domains,
                excluded_hoster_urls=failed_hoster_urls,
                barren_hoster_urls=barren_hoster_urls,
            )
        gate_seen[0] = gate_seen[0] or bool(next_result.gated)
        if next_result.stream_info:
            if _enqueue_hoster_attempt(
                movie, movie_slug, out_path, next_result, unsupported_domains,
                failed_hoster_urls, attempt_errors, source_movies, source_index,
                source_fallbacks_loaded, refreshed_hoster_urls,
                barren_hoster_urls, cancelled,
                gate_seen, gate_retry, slow_candidates, last_resort,
                attempt_id=logical_attempt_id,
            ):
                return
            on_job_done(False, "Abgebrochen", label, out_path, slug=movie_slug, job_id=logical_job["job_id"], attempt_id=logical_attempt_id)
            return

        # Alle Hoster dieses Katalogtreffers sind verbraucht. Nun denselben Inhalt
        # bei weiteren Katalogquellen testen – für Filme UND Episoden.
        ep_info = parse_episode_slug(movie_slug)
        if not source_fallbacks_loaded[0]:
            source_fallbacks_loaded[0] = True
            on_job_progress(
                -1, "Hoster erschöpft · suche alternative Quellen …", label,
                slug=movie_slug, job_id=logical_job["job_id"], attempt_id=logical_attempt_id,
            )
            if ep_info:
                series_title = strip_episode_suffix(source_movies[0].title) or source_movies[0].title
                tried_providers = {
                    _movie_provider(candidate, movie_slug)
                    for candidate in source_movies
                }
                tried_providers.discard("")
                alternatives = find_episode_fallbacks(
                    series_title,
                    ep_info[1],
                    ep_info[2],
                    aliases=_episode_fallback_aliases(movie_slug, series_title),
                    source_slug=movie_slug,
                    excluded_providers=tried_providers,
                )
                seen = {m.url for m in source_movies}
                source_movies.extend(m for m in alternatives if m.url not in seen)
            else:
                source_movies.extend(find_movie_source_fallbacks(
                    source_movies[0], movie_slug, {m.url for m in source_movies},
                ))
        for next_index in range(source_index + 1, len(source_movies)):
            next_movie = source_movies[next_index]
            log(f"  Wechsle Filmquelle: {clean_movie_title(next_movie.title)}", "warn")
            with state.hoster_extract_lock:
                source_result = _extract_from_movie(
                    next_movie,
                    unsupported_domains,
                    excluded_hoster_urls=failed_hoster_urls,
                    barren_hoster_urls=barren_hoster_urls,
                )
            gate_seen[0] = gate_seen[0] or bool(source_result.gated)
            if not source_result.stream_info:
                continue
            if _enqueue_hoster_attempt(
                next_movie, movie_slug, out_path, source_result, unsupported_domains,
                failed_hoster_urls, attempt_errors, source_movies, next_index,
                source_fallbacks_loaded, refreshed_hoster_urls,
                barren_hoster_urls, cancelled,
                gate_seen, gate_retry, slow_candidates, last_resort,
                attempt_id=logical_attempt_id,
            ):
                return
            on_job_done(False, "Abgebrochen", label, out_path, slug=movie_slug, job_id=logical_job["job_id"], attempt_id=logical_attempt_id)
            return

        if ep_info and gate_seen[0] and gate_retry and gate_retry():
            log("  serienstream-Captcha aktiv – Episode nach Cooldown erneut versuchen.", "warn")
            on_job_progress(
                -1, "Captcha-Cooldown · Wiederholung vorgemerkt …", label,
                slug=movie_slug, job_id=logical_job["job_id"], attempt_id=logical_attempt_id,
            )
            return

        if slow_candidates:
            reserve_movie, reserve_result, _reserve_speed = max(
                slow_candidates,
                key=lambda candidate: candidate[2],
            )
            reserve_label = reserve_result.hoster_used or "langsame Quelle"
            log(
                f"  Alle schnelleren Quellen erschoepft – {reserve_label} "
                "wird als langsame Reserve ohne Speed-Limit fortgesetzt.",
                "warn",
            )
            on_job_progress(
                -1,
                f"Keine schnellere Quelle · nutze {reserve_label} als Reserve …",
                label,
                slug=movie_slug,
                job_id=logical_job["job_id"],
                attempt_id=logical_attempt_id,
            )
            if _enqueue_hoster_attempt(
                reserve_movie,
                movie_slug,
                out_path,
                reserve_result,
                unsupported_domains,
                failed_hoster_urls,
                attempt_errors,
                source_movies,
                source_index,
                source_fallbacks_loaded,
                refreshed_hoster_urls,
                barren_hoster_urls,
                cancelled,
                gate_seen,
                gate_retry,
                [],
                True,
                attempt_id=logical_attempt_id,
            ):
                return
            on_job_done(False, "Abgebrochen", label, out_path, slug=movie_slug, job_id=logical_job["job_id"], attempt_id=logical_attempt_id)
            return

        reason = "serienstream-Captcha aktiv" if gate_seen[0] else "alle Anbieter und Filmquellen ausgeschöpft"
        final_msg = "; ".join(attempt_errors + [reason])
        on_job_done(False, final_msg, label, out_path, slug=movie_slug, job_id=logical_job["job_id"], attempt_id=logical_attempt_id)

    def _download_started():
        current = _queue_job_for_slug(movie_slug) or logical_job
        _update_queue_job(
            movie_slug,
            expected_job_id=logical_job["job_id"],
            expected_attempt_id=logical_attempt_id,
            status="downloading",
            started_at=current.get("started_at") or time.time(),
            attempts=int(current.get("attempts") or 0) + 1,
            provider=result.provider or _movie_provider(movie, movie_slug),
            hoster=hoster_used,
            quality=result.quality,
        )

    job = DownloadJob(
        stream_url=stream_url,
        stream_type=stream_type,
        out_path=out_path,
        queue_slug=movie_slug,
        provider=result.provider or _movie_provider(movie, movie_slug),
        content_language=(
            result.content_language
            or _movie_content_language(movie, fallback=movie_slug)
        ),
        referer=result.referer,
        origin=result.origin,
        on_progress=lambda pct, msg: on_job_progress(
            pct,
            msg,
            label,
            slug=movie_slug,
            job_id=logical_job["job_id"],
            attempt_id=logical_attempt_id,
            downloaded_bytes=job.downloaded_bytes,
            total_bytes=job.total_bytes,
            speed_bps=job.average_speed_bps,
            eta_seconds=job.eta_seconds,
        ),
        on_done=_attempt_done,
        on_start=_download_started,
        job_id=logical_job["job_id"],
        attempt_id=logical_attempt_id,
        allow_slow=last_resort,
        queue_priority=0 if not parse_episode_slug(movie_slug) else 100,
        demo_mode=demo_mode,
    )
    with state.queue_lifecycle_lock:
        with state.queue_claim_lock:
            current = _queue_job_for_slug(movie_slug)
            if (
                (cancelled and cancelled())
                or movie_slug not in state.picked
                or not current
                or current.get("job_id") != logical_job["job_id"]
                or current.get("attempt_id") != logical_attempt_id
                or current.get("status") == "cancelling"
            ):
                return False
            add_front = getattr(state.dl_queue, "add_front", None)
            # Langsame Reserven ohne Speed-Limit koennen stundenlang kriechen.
            # Sie kommen ans Queue-Ende, damit schnelle Downloads nicht hinter
            # ihnen verhungern; normale Folgeversuche behalten ihren Slot vorn.
            if add_front and not last_resort:
                add_front(job)
            else:
                state.dl_queue.add(job)
    return True


_SERVICE_EXPORTS = (
    "_HosterResult",
    "_extract_from_movie",
    "find_movie_source_fallbacks",
    "_enqueue_hoster_attempt",
)
publish_service(globals(), _SERVICE_EXPORTS)
