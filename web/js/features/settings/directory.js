import { api } from "../../core/api.js";
import { createScope } from "../../core/lifecycle.js";
import { createDialog } from "../../shared/components/dialog.js";

/** Shared folder picker for setup and settings; selection does not persist config. */
export function createDirectoryPicker(root, { client = api } = {}) {
  const byId = id => root.querySelector(`#${id}`);
  let scope, target, path = "", parent = "", entries = [];
  let cancelRequest = () => {};
  const dialog = createDialog(root, { initialFocus: () => byId("dir-modal-close"),
    onClose() { scope = null; target = null; entries = []; cancelRequest(); },
  });
  async function browse(requestedPath) {
    if (!scope?.active) return;
    cancelRequest();
    const current = createScope();
    const release = scope.add(() => current.dispose());
    cancelRequest = release;
    const list = byId("dir-modal-list");
    byId("dir-modal-select").disabled = true;
    byId("dir-modal-up").disabled = true;
    list.textContent = "Ordner werden geladen …";
    try {
      const data = await client.get(`/api/browse-dir?${new URLSearchParams({ path: requestedPath || "" })}`, { signal: current.signal });
      if (!current.active) return;
      if (data.error) throw new Error(data.error);
      path = data.path; parent = data.parent; entries = data.dirs || [];
      byId("dir-modal-path").textContent = path;
      byId("dir-modal-up").disabled = !parent;
      byId("dir-modal-select").disabled = false;
      list.replaceChildren(...entries.map((entry, index) => {
        const item = root.ownerDocument.createElement("div");
        item.className = "dir-item"; item.translate = false; item.textContent = entry.name;
        item.dataset.directoryIndex = String(index); item.tabIndex = 0; item.setAttribute("role", "button");
        return item;
      }));
      if (!entries.length) list.textContent = "Keine Unterordner vorhanden.";
    } catch (error) { if (current.active) list.textContent = `Ordner nicht abrufbar: ${error.message}`; }
    finally { release(); }
  }
  return {
    open(input, trigger) {
      dialog.unmount();
      target = input;
      scope = dialog.open(trigger);
      scope.listen(byId("dir-modal-close"), "click", () => dialog.close());
      scope.listen(byId("dir-modal-up"), "click", () => { if (parent) void browse(parent); });
      scope.listen(byId("dir-modal-select"), "click", () => {
        if (byId("dir-modal-select").disabled || !target) return;
        target.value = path;
        target.dispatchEvent(new Event("input", { bubbles: true }));
        dialog.close();
      });
      const openEntry = event => {
        const item = event.target.closest("[data-directory-index]");
        if (!item || !root.contains(item)) return;
        const entry = entries[Number(item.dataset.directoryIndex)];
        if (entry) void browse(entry.path);
      };
      scope.listen(byId("dir-modal-list"), "click", openEntry);
      scope.listen(byId("dir-modal-list"), "keydown", event => {
        if (["Enter", " "].includes(event.key)) { event.preventDefault(); openEntry(event); }
      });
      void browse(input.value);
    },
    unmount: dialog.unmount,
  };
}
