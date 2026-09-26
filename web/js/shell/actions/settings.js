import { sharedPresentation } from "../presentation.js";
// Compatibility entry points for the remaining setup presenter.
export function updateDeploymentModeHints(context, mode) { sharedPresentation.deploymentHints(context, mode); }
export function selectedDeploymentMode(name = "deployment-mode") { return sharedPresentation.deploymentMode(name); }
export function providerLanguage(provider) { return sharedPresentation.providers.language(provider); }
export function applyProviderPriority(value) { sharedPresentation.providers.apply(value); }
export function initSettings() { return sharedPresentation.settings.initialize(); }
