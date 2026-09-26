// Compatibility entry points for the remaining setup presenter.
function updateDeploymentModeHints(context, mode) { sharedPresentation.deploymentHints(context, mode); }
function selectedDeploymentMode(name = "deployment-mode") { return sharedPresentation.deploymentMode(name); }
function providerLanguage(provider) { return sharedPresentation.providers.language(provider); }
function applyProviderPriority(value) { sharedPresentation.providers.apply(value); }
function initSettings() { return sharedPresentation.settings.initialize(); }
