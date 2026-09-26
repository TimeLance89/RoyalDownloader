import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";

export function fillJellyfinUsers(select, users, selectedId = "", selectedName = "") {
  select.replaceChildren();
  const placeholder = select.ownerDocument.createElement("option");
  placeholder.value = "";
  placeholder.textContent = users.length ? "Benutzer auswählen …" : "Benutzer laden …";
  select.appendChild(placeholder);
  for (const user of users) {
    const option = select.ownerDocument.createElement("option");
    option.value = user.id;
    option.textContent = user.name;
    option.translate = false;
    option.dataset.name = user.name;
    select.appendChild(option);
  }
  if (selectedId && !users.some((user) => user.id === selectedId)) {
    const option = select.ownerDocument.createElement("option");
    option.value = selectedId;
    option.textContent = selectedName || "Gespeicherter Benutzer";
    option.translate = false;
    option.dataset.name = selectedName || "";
    select.appendChild(option);
  }
  select.value = selectedId && [...select.options].some((option) => option.value === selectedId)
    ? selectedId
    : (users.length === 1 ? users[0].id : "");
}


export function createJellyfinUserPicker(root, { urlId, keyId, selectId, buttonId, statusId, onError = () => {}, client = api }) {
  const byId = id => root.querySelector(`#${id}`);
  let scope;
  let busy = false;
  async function load() {
    if (!scope?.active || busy) return;
    const current = scope;
    const button = byId(buttonId), select = byId(selectId), status = statusId ? byId(statusId) : null;
    busy = true; button.disabled = true;
    if (status) status.textContent = "Lade Jellyfin-Benutzer …";
    try {
      const value = await client.post("/api/jellyfin/users", {
        url: byId(urlId).value.trim(), api_key: byId(keyId).value.trim(),
      }, { signal: current.signal });
      if (!current.active) return;
      fillJellyfinUsers(select, value.users || [], select.value);
      select.dispatchEvent(new Event("change", { bubbles: true }));
      if (status) status.textContent = value.users?.length ? `${value.users.length} Benutzer gefunden` : "Keine aktiven Jellyfin-Benutzer gefunden";
    } catch (error) {
      if (!current.active) return;
      if (status) status.textContent = error.message; else onError(error.message);
    } finally { if (current.active) { busy = false; button.disabled = false; } }
  }
  return {
    fill: (users, id, name) => fillJellyfinUsers(byId(selectId), users, id, name),
    mount() { if (scope) return; scope = createScope(); byId(buttonId).disabled = false; scope.listen(byId(buttonId), "click", load); },
    unmount() { scope?.dispose(); scope = null; busy = false; },
  };
}
