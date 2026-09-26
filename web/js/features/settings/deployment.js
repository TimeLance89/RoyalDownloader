export function updateDeploymentModeHints(root, context, mode) {
  const nas = mode === "nas";
  const movie = root.querySelector(context === "setup" ? "#setup-save-path" : "#save-path");
  const series = root.querySelector(context === "setup" ? "#setup-series-path" : "#series-path");
  if (movie) movie.placeholder = nas ? "/volume1/media/Filme" : "C:\\Users\\Name\\Downloads\\Royal\\Filme";
  if (series) series.placeholder = nas ? "/volume1/media/Serien" : "C:\\Users\\Name\\Downloads\\Royal\\Serien";
  const status = root.querySelector("#deployment-mode-status");
  if (context === "settings" && status) status.textContent = nas
    ? "NAS-Modus · start.sh/Docker · im Netzwerk erreichbar"
    : "Computer-Modus · lokaler Browser · nur auf diesem Gerät";
}
export function selectedDeploymentMode(root, name = "deployment-mode") {
  return root.querySelector(`input[name="${name}"]:checked`)?.value || "desktop";
}
