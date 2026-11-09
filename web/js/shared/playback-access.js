/** UI eligibility only. The server verifies the linked profile and each item. */
export const isPlaybackUser = user => Boolean(user?.id && user.enabled !== false && ["admin", "member"].includes(user.role));
export const playbackIdentity = user => JSON.stringify([user?.id, user?.role, user?.enabled, user?.updated_at]);
export const playbackDenied = error => [401, 403, 404, 409].includes(error?.status);
