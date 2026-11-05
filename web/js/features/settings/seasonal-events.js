import { createScope } from "../../core/lifecycle.js";

export function createEventSettings(root, { events }) {
  const toggle = root.querySelector("#seasonal-events-enabled");
  const status = root.querySelector("#seasonal-events-status");
  const text = (de, en) => root.ownerDocument.documentElement.lang.startsWith("en") ? en : de;
  let scope = null;
  return {
    mount() {
      if (scope?.active || !toggle || !events) return;
      scope = createScope();
      const owner = scope;
      toggle.disabled = true;
      void events().load({ signal: owner.signal }).then(value => {
        if (!owner.active) return;
        toggle.checked = value;
        toggle.disabled = false;
        status.textContent = "";
      }).catch(error => { if (owner.active) status.textContent = error.message; });
      owner.listen(toggle, "change", async () => {
        const previous = events().enabled;
        toggle.disabled = true;
        status.textContent = text("Speichere …", "Saving …");
        try {
          await events().save(toggle.checked, { signal: owner.signal });
          if (owner.active) status.textContent = text("Gespeichert · wirkt sofort.", "Saved · takes effect immediately.");
        } catch (error) {
          if (owner.active) { toggle.checked = previous; status.textContent = error.message; }
        } finally { if (owner.active) toggle.disabled = false; }
      });
    },
    unmount() { scope?.dispose(); scope = null; },
  };
}
