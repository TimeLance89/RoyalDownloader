import { cleanMediaCardInitials } from "../features/discovery/catalog-identity.js";
import { createShell } from "../core/shell.js";
import { switchTab } from "../shell/presentation.js";
import { openMobileQueue } from "../shell/presentation.js";
import { closeMobileQueue } from "../shell/presentation.js";
import { toggleDesktopQueue } from "../shell/presentation.js";
import { closeMediaModal } from "../shell/presentation.js";
import { openWatchModeModal } from "../shell/actions/anime.js";
import { handleMediaModalKeydown } from "../shell/presentation.js";
import { setQueueDockExpanded } from "../shell/presentation.js";
import { refreshQueueUiAfterChange } from "../shell/presentation.js";
import { renderSerienstreamHealth } from "../shell/presentation.js";
import { setDownloadState } from "../shell/presentation.js";
import { state } from "../shell/presentation.js";
import { sharedPresentation } from "../shell/presentation.js";
import { setMediaCardMeta } from "../shared/components/media-card.js";
import { createCardArtwork } from "../shared/components/card-artwork.js";
import { renderMediaCard } from "../shared/components/media-card.js";
import { jellyfinStatusText as statusText } from "../shared/components/status-badge.js";
import { setCatalogJellyfinBadge as statusBadge } from "../shared/components/status-badge.js";

export function composeCore({ i18n, modal }) {
return {
cleanMediaCardInitials,
localization: i18n,
shell: createShell(document, {
      switchTab, openMobileQueue, closeMobileQueue, toggleDesktopQueue, closeMediaModal,
      openWatchModeModal, handleMediaModalKeydown, setQueueDockExpanded, refreshQueueUiAfterChange,
      renderSerienstreamHealth, setDownloadState, getDownloadPercent: () => state.download.percent,
      closeNotifications: () => sharedPresentation.notifications.close(),
      openDirectory: (...args) => sharedPresentation.directory.open(...args),
    }),
setMediaCardMeta,
cardArtwork: createCardArtwork(document.body),
modal,
renderMediaCard,
jellyfinStatusText: statusText,
setCatalogJellyfinBadge: statusBadge
};
}
