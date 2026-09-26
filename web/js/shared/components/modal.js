import { createScope } from "../../core/lifecycle.js";

/** Shell-owned overlays. Each open modal owns its pending work and focus target. */
export function createModalController(root, {
  closeFpTrailerModal, stopFpDetailHeroTrailer, stopSeriesDetailHeroTrailer,
  closeCollectionDetails = () => {}, closeAniworldDetails = () => {}, closeAnimeDetails = () => {}, closeSeriesDetails = () => {}, closeMovieDetails = () => {}, closeLanguageChoice = () => {}, trailerModalFocusableElements, resumeMoodMatchAfterDetail = () => false,
}) {
  const opened = new Map();
  const find = id => [...root.querySelectorAll("[id]")].find(node => node.id === id);
  function activeMediaModal() {
    return root.querySelector(".media-modal.is-open:not([hidden])");
  }

  function openMediaModal(modalId, trigger = null) {
    const modal = find(modalId);
    if (!modal) return;
    const current = activeMediaModal();
    if (current && current !== modal) closeMediaModal(current.id, false);
    if (!modal.hidden && modal.classList.contains("is-open")) return;
    const returnFocus = trigger instanceof root.ownerDocument.defaultView.HTMLElement ? trigger : root.ownerDocument.activeElement;
    const scope = createScope();
    opened.set(modal, { scope, returnFocus });
    modal.hidden = false;
    modal.classList.add("is-open");
    root.ownerDocument.body.classList.add("media-modal-open");
    const scrollContainers = modal.querySelectorAll(
      ".media-modal-panel, .detail-body, .tiles-scroll, .anime-detail-content",
    );
    scrollContainers.forEach((element) => { element.scrollTop = 0; element.scrollLeft = 0; });
    scope.frame(() => {
      scrollContainers.forEach((element) => { element.scrollTop = 0; element.scrollLeft = 0; });
      modal.querySelector(".media-modal-close")?.focus();
    });
  }

  function closeMediaModal(modalId, restoreFocus = true) {
    const modal = find(modalId);
    if (!modal || modal.hidden) return;
    if (modalId === "fp-detail-modal") {
      closeMovieDetails();
      closeLanguageChoice();
      closeFpTrailerModal(false);
      stopFpDetailHeroTrailer();
    } else if (modalId === "series-detail-modal") {
      closeSeriesDetails();
      closeFpTrailerModal(false);
      stopSeriesDetailHeroTrailer();
    } else if (modalId === "anime-detail-modal") {
      closeAnimeDetails();
    } else if (modalId === "movie-collection-modal") {
      closeCollectionDetails();
    } else if (modalId === "aniworld-detail-modal") {
      closeAniworldDetails();
    }
    const entry = opened.get(modal);
    const returnFocus = entry?.returnFocus;
    entry?.scope.dispose();
    opened.delete(modal);
    modal.classList.remove("is-open");
    modal.hidden = true;
    if (!activeMediaModal()) root.ownerDocument.body.classList.remove("media-modal-open");
    const resumedMood = restoreFocus
      && resumeMoodMatchAfterDetail();
    if (!resumedMood && restoreFocus && returnFocus instanceof root.ownerDocument.defaultView.HTMLElement && returnFocus.isConnected) {
      returnFocus.focus();
    }
  }

  function closeAllMediaModals(restoreFocus = true) {
    closeFpTrailerModal(false);
    root.querySelectorAll(".media-modal:not([hidden])").forEach((modal) => {
      closeMediaModal(modal.id, restoreFocus);
    });
  }

  function handleMediaModalKeydown(event) {
    const trailerModal = find("fp-trailer-modal");
    if (trailerModal && !trailerModal.hidden) {
      if (event.key === "Escape") {
        event.preventDefault();
        closeFpTrailerModal();
        return true;
      }
      if (event.key === "Tab") {
        const focusable = trailerModalFocusableElements();
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && root.ownerDocument.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && root.ownerDocument.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
      return true;
    }
    const modal = activeMediaModal();
    if (!modal) return false;
    if (event.key === "Escape") {
      event.preventDefault();
      closeMediaModal(modal.id);
      return true;
    }
    if (event.key !== "Tab") return false;
    const focusable = [...modal.querySelectorAll(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    )].filter((element) => !element.hidden && element.getClientRects().length);
    if (!focusable.length) {
      event.preventDefault();
      modal.querySelector(".media-modal-panel")?.focus();
      return true;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && root.ownerDocument.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && root.ownerDocument.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
    return true;
  }

  return {
    active: activeMediaModal, open: openMediaModal, close: closeMediaModal,
    closeAll: closeAllMediaModals, keydown: handleMediaModalKeydown,
    unmount() { closeAllMediaModals(false); for (const entry of opened.values()) entry.scope.dispose(); opened.clear(); },
  };
}
