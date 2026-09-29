/** Provider capabilities only; never infer a title's tracks from this list. */
export function supportedProviderLanguages(metadata) {
  const values = Array.isArray(metadata?.content_languages)
    ? metadata.content_languages : [metadata?.content_language];
  return [...new Set(values.map(value => String(value || "").toLowerCase()).filter(Boolean))];
}

export function providerMatchesLanguages(metadata, selected) {
  return supportedProviderLanguages(metadata).some(language => selected.has(language));
}
