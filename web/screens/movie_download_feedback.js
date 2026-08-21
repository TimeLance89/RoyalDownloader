// Sichtbarer Lebenszyklus eines Film-Downloads im geöffneten Detaildialog.
const fpDownloadFeedback = new Map();

function renderFpDownloadFeedback(slug) {
  const status = document.getElementById("fp-detail-download-status");
  if (!status) return;
  const feedback = fpDownloadFeedback.get(slug);
  status.hidden = !feedback;
  status.className = `detail-download-status is-${feedback?.kind || "idle"}`;
  status.textContent = feedback?.message || "";
}

function setFpDownloadFeedback(slug, message = "", kind = "error") {
  if (!slug) return;
  if (message) fpDownloadFeedback.set(slug, { message, kind });
  else fpDownloadFeedback.delete(slug);
  if (state.fp.selectedSlug === slug) renderFpDownloadFeedback(slug);
}

function applyFpQueueAddResponse(slug, response) {
  const reason = api.queueAddFailureReason(response, [slug]);
  if (reason) {
    const message = `Download nicht gestartet: ${reason}`;
    setFpDownloadFeedback(slug, message, "error");
    setDownloadState("error", "Download nicht gestartet", reason, 0);
    return false;
  }
  setFpDownloadFeedback(slug, "Download eingeplant. Die Quelle wird vorbereitet.", "active");
  return true;
}

function applyFpDownloadJobResult(result) {
  const slug = String(result?.slug || "");
  if (!slug) return;
  if (result.ok) {
    setFpDownloadFeedback(slug, "Download erfolgreich abgeschlossen.", "success");
    return;
  }
  const reason = String(result.msg || "Alle Anbieter oder Hoster sind ausgefallen.");
  setFpDownloadFeedback(slug, `Download fehlgeschlagen: ${reason}`, "error");
}
