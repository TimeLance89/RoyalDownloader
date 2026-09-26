export function createSettingsActions({
  getDeploymentHints,
  getDeploymentMode,
  getProviders,
  getSettings,
}) {
  // Compatibility entry points for the remaining setup presenter.
  function updateDeploymentModeHints(context, mode) { getDeploymentHints()(context, mode); }
  function selectedDeploymentMode(name = "deployment-mode") { return getDeploymentMode()(name); }
  function providerLanguage(provider) { return getProviders().language(provider); }
  function applyProviderPriority(value) { getProviders().apply(value); }
  function initSettings() { return getSettings().initialize(); }
  return { updateDeploymentModeHints, selectedDeploymentMode, providerLanguage, applyProviderPriority, initSettings };
}
