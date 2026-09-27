import { createScope } from "../../core/lifecycle.js";
import { isAbortError } from "../../core/errors.js";
import { createMovieSubscriptionView } from "./movie-view.js";

export function createMovieSubscriptionsView(root, { model, ...presentation }) {
  const view = createMovieSubscriptionView(root, { model, ...presentation });
  let scope;
  let feedback = "";
  function refresh() { if (scope?.active) view.render(feedback); }
  async function check() {
    const current = scope;
    if (!current?.active || model.get().checkRunning) return;
    feedback = "";
    try { await model.check(null, { signal: current.signal }); }
    catch (error) { if (current.active && !isAbortError(error)) feedback = `Prüfung fehlgeschlagen: ${error.message}`; }
    finally { if (current.active) refresh(); }
  }
  return {
    refresh,
    mount() {
      if (scope?.active) return;
      scope = createScope();
      scope.add(model.subscribe(refresh));
      scope.listen(root.querySelector("#movie-subscriptions-check"), "click", () => { void check(); });
      refresh();
      if (!model.get().loaded) void model.refresh({ signal: scope.signal });
    },
    unmount() { scope?.dispose(); scope = null; view.unmount(); },
  };
}
