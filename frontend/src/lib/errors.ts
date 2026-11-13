/**
 * Structured API Error class with HTTP status, status text, and backend error payload.
 */
export class ApiError extends Error {
  public status: number;
  public statusText: string;
  public data: unknown;

  constructor(status: number, statusText: string, data: unknown) {
    let message = `API Error ${status}: ${statusText}`;
    if (typeof data === "object" && data !== null) {
      const errObj = data as Record<string, unknown>;
      const detail = errObj.detail;
      if (Array.isArray(detail)) {
        // FastAPI/Pydantic validation errors arrive as a list of objects.
        const messages = detail
          .map((item) => {
            if (typeof item === "string") return item;
            if (item && typeof item === "object") {
              const entry = item as Record<string, unknown>;
              const loc = Array.isArray(entry.loc) ? entry.loc.join(".") : "";
              const msg = typeof entry.msg === "string" ? entry.msg : "";
              return loc ? `${loc}: ${msg}` : msg;
            }
            return "";
          })
          .filter((part) => part.length > 0);
        if (messages.length > 0) message = messages.join("; ");
      } else if (typeof detail === "string") {
        message = detail;
      } else if (typeof errObj.error === "string") {
        message = errObj.error;
      }
    } else if (typeof data === "string" && data.length > 0) {
      message = data;
    }
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.statusText = statusText;
    this.data = data;
  }
}
