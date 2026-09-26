export class ApiError extends Error {
  constructor(message, { status = 0, code = "", resource = "", cause } = {}) {
    super(message, { cause });
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.resource = resource;
  }
}

export const isAbortError = error => error?.name === "AbortError";

// Subscriber failures must not prevent the remaining subscribers from updating.
export function reportError(error) {
  console.error("Royal:", error);
}
