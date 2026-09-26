import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";
import { isAbortError } from "../../core/errors.js";
import { createViewState } from "../../shared/components/view-state.js";
import { createProfileView } from "./view.js";

/** Personal requests come from profile-summary, independently of the download queue. */
export function createProfile(root, { switchTab, userRoleLabel, applyUser, showHousehold, closeHousehold, openSecurity, reopenTasteOnboarding }) {
  const view = createProfileView(root, { switchTab, userRoleLabel });
  let scope;
  let pending;
  const find = id => root.querySelector(`#${id}`);
  const showState = (state, title, detail = "") => {
    root.dataset.viewState = state;
    find("profile-recent-downloads").replaceChildren(createViewState({ state, title, detail, className: "profile-empty", retry: state === "error" ? refresh : undefined }));
  };
  function refresh() {
    const current = scope;
    if (!current?.active) return Promise.resolve();
    if (pending) return pending;
    showState("loading", "Profil wird geladen …");
    const request = api.get("/api/me/profile-summary", { signal: current.signal }).then(summary => {
      if (!current.active) return;
      applyUser(summary.user);
      view.render(summary);
      root.dataset.viewState = "ready";
    }).catch(error => {
      if (!current.active || isAbortError(error)) return;
      showState("error", "Profil konnte nicht geladen werden", error.message);
    }).finally(() => { if (pending === request) pending = null; });
    pending = request;
    return request;
  }
  return {
    mount() {
      if (scope?.active) return;
      scope = createScope();
      const current = scope;
      scope.listen(find("profile-edit-taste"), "click", async () => {
        if (!window.confirm("Geschmack vollständig neu aufbauen? Bisherige persönliche Signale werden gelöscht.")) return;
        try {
          const response = await api.post("/api/taste/reset", undefined, { signal: current.signal });
          if (current.active) reopenTasteOnboarding(response.user);
        } catch (error) {
          if (current.active && !isAbortError(error)) showState("error", "Geschmack konnte nicht zurückgesetzt werden", error.message);
        }
      });
      scope.listen(find("profile-show-taste-detail"), "click", () => root.querySelector(".profile-genres-panel")?.scrollIntoView({ behavior: "smooth", block: "center" }));
      scope.listen(find("profile-household-open"), "click", showHousehold);
      scope.listen(find("profile-open-library"), "click", () => switchTab("bibliothek"));
      scope.listen(find("profile-security"), "click", openSecurity);
      root.querySelectorAll("[data-profile-security]").forEach(button => scope.listen(button, "click", openSecurity));
      void refresh();
    },
    refresh,
    unmount() { scope?.dispose(); scope = null; pending = null; view.unmount(); closeHousehold(); },
  };
}
