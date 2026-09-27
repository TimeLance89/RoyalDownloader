/** Safe text-only status UI; ready content remains owned by its feature. */
export function createViewState({ state, title = "", detail = "", className = "", retry } = {}) {
  const element = document.createElement("div");
  element.className = className;
  element.dataset.viewState = state;
  element.setAttribute("role", state === "error" ? "alert" : "status");
  if (state === "loading") element.setAttribute("aria-busy", "true");
  if (title) {
    const heading = document.createElement("strong");
    heading.textContent = title;
    element.append(heading);
  }
  if (detail) {
    const copy = document.createElement("span");
    copy.textContent = detail;
    element.append(copy);
  }
  if (retry) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "queue-action-btn";
    button.textContent = "Erneut versuchen";
    button.addEventListener("click", retry);
    element.append(button);
  }
  return element;
}
