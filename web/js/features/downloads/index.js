import { createScope } from "../../core/lifecycle.js";
import { websocket } from "../../core/websocket.js";

// The queue dock is application-wide, so this feature lives through tab switches.
// Server messages remain unchanged. Existing presenters are injected at the seam.
export function createLiveUpdates({ onMessage, onDownload = onMessage, onOpen, onUnauthorized, socket = websocket }) {
  let scope;
  return {
    mount() {
      if (scope) return;
      scope = createScope();
      for (const topic of ["log", "progress", "job_done",
        "queue_started", "queue_update", "provider_status", "queue_done", "jellyfin_update"]) {
        const downloadTopic = ["progress", "job_done", "queue_started", "queue_update", "provider_status", "queue_done"].includes(topic);
        scope.add(socket.subscribe(topic, downloadTopic ? onDownload : onMessage));
      }
      scope.add(socket.subscribe("connection.open", onOpen));
      scope.add(socket.subscribe("session.expired", onUnauthorized));
      socket.connect();
    },
    refresh() {
      const current = scope;
      if (!current?.active) return;
      return onOpen({ isCurrent: () => scope === current && current.active });
    },
    unmount() {
      scope?.dispose();
      scope = null;
      socket.disconnect();
    },
  };
}
