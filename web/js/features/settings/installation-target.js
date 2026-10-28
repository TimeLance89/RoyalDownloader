export const installationPaths = os => os === "windows" ? ["C:\\Royal\\Medien\\Filme", "C:\\Royal\\Medien\\Serien"]
  : os === "macos" ? ["/Users/DEIN_NAME/Movies/Royal/Filme", "/Users/DEIN_NAME/Movies/Royal/Serien"]
    : os === "linux" ? ["/srv/royal/media/Filme", "/srv/royal/media/Serien"] : ["", ""];

export function validInstallationPath(os, value) {
  const path = String(value || "").trim();
  if (!path || /[\r\n\0]/.test(path)) return false;
  if (os === "windows") return /^[A-Za-z]:[\\/]/.test(path) || /^(?:\\\\|\/\/)[^\\/]+[\\/][^\\/]+/.test(path);
  return ["linux", "macos"].includes(os) && path.startsWith("/") && !path.startsWith("//") && !path.includes("\\");
}
