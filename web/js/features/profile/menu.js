import { createScope } from "../../core/lifecycle.js";
import { appStore } from "../../core/store.js";
import { userInitials, userRoleLabel } from "./identity.js";

/** The account menu belongs to the authenticated shell, independently of profile navigation. */
export function createUserMenu(root, { logout, navigate, openSecurity, openHousehold }) {
  let scope;
  const find = id => root.querySelector(`#${id}`);
  const trigger = find("user-menu-trigger");
  const popover = find("user-menu-popover");
  function close() {
    popover.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
    root.classList.remove("is-open");
  }
  function refresh() {
    const user = appStore.get().user;
    if (!user) return;
    ["user-menu-name", "user-menu-popover-name"].forEach(id => { find(id).textContent = user.display_name || user.username; });
    ["user-menu-role", "user-menu-popover-role"].forEach(id => { find(id).textContent = userRoleLabel(user); });
    find("user-menu-avatar").textContent = userInitials(user);
  }
  return {
    mount() {
      if (scope?.active) return;
      scope = createScope();
      scope.add(appStore.subscribe(refresh));
      refresh();
      scope.listen(trigger, "click", () => {
        const open = popover.hidden;
        popover.hidden = !open;
        trigger.setAttribute("aria-expanded", String(open));
        root.classList.toggle("is-open", open);
      });
      scope.listen(document, "click", event => { if (!root.contains(event.target)) close(); });
      scope.listen(popover, "click", event => {
        const action = event.target.closest("[data-user-action]")?.dataset.userAction;
        if (!action) return;
        close();
        if (action === "logout") logout();
        if (action === "security") openSecurity();
        if (action === "profile") navigate("profil");
        if (action === "household") { navigate("profil"); void openHousehold(); }
      });
    },
    refresh,
    unmount() { close(); scope?.dispose(); scope = null; },
  };
}
