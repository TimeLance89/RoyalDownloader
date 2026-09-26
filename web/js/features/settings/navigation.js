import { createScope } from "../../core/lifecycle.js";

export function createSettingsNavigation(root) {
  let scope;
  let initialized = false;
  const panel = root?.querySelector(".settings-panel");
  const directory = root?.querySelector(".settings-directory");
  const links = [...(root?.querySelectorAll("[data-settings-target]") || [])];
  const sections = [...(root?.querySelectorAll("[data-settings-section]") || [])];
  if (!root || !panel || !links.length || !sections.length) return;

  const activate = (requestedId, { scroll = true } = {}) => {
    const id = sections.some((section) => section.id === requestedId)
      ? requestedId
      : "settings-overview";
    panel.classList.toggle("is-overview", id === "settings-overview");

    sections.forEach((section) => {
      const active = section.id === id;
      section.classList.toggle("is-active", active);
      section.hidden = !active;
      section.setAttribute("aria-hidden", active ? "false" : "true");
    });

    links.forEach((link) => {
      const active = link.dataset.settingsTarget === id;
      link.classList.toggle("is-active", active);
      if (active) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });

    const activeLink = links.find((link) => link.dataset.settingsTarget === id);
    if (directory && activeLink && window.innerWidth <= 820) {
      const targetLeft = activeLink.offsetLeft
        - Math.max(0, (directory.clientWidth - activeLink.offsetWidth) / 2);
      directory.scrollTo({
        left: targetLeft,
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
          ? "auto"
          : "smooth",
      });
    }

    if (scroll) {
      const workbench = root.querySelector(".settings-workbench");
      const top = workbench
        ? root.scrollTop + workbench.getBoundingClientRect().top - root.getBoundingClientRect().top - 8
        : 0;
      root.scrollTo({
        top: Math.max(0, top),
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
          ? "auto"
          : "smooth",
      });
    }
  };


  return {
    open: activate,
    mount() {
      if (scope) return;
      scope = createScope();
      links.forEach((link) => {
        scope.listen(link, "click", (event) => {
          event.preventDefault();
          activate(link.dataset.settingsTarget);
        });
      });

      root.querySelectorAll("[data-settings-open]").forEach((button) => {
        scope.listen(button, "click", () => activate(button.dataset.settingsOpen));
      });

      const markDirty = () => {
        const status = root.querySelector("#settings-saved-status");
        if (status) status.textContent = "Ungespeicherte Änderungen.";
      };
      scope.listen(panel, "input", markDirty);
      scope.listen(panel, "change", markDirty);
      scope.listen(panel, "click", (event) => {
        if (event.target.closest(".provider-order-button, .content-language-card")) markDirty();
      });

      if (!initialized) {
        initialized = true;
        activate(window.location.hash.slice(1) || "settings-overview", { scroll: false });
      }
    },
    refresh() {},
    unmount() { scope?.dispose(); scope = null; },
  };
}
