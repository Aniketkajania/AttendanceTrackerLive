// Standard JSON handling and readable FastAPI validation errors.
function errorDetail(detail, fallback) {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail.map(item => {
      if (typeof item === "string") return item;
      if (!item || typeof item !== "object") return String(item);
      const location = Array.isArray(item.loc) ? item.loc.filter(part => part !== "body").join(".") : "";
      return [location, item.msg || item.message || "Invalid value"].filter(Boolean).join(": ");
    });
    return messages.join("; ") || fallback;
  }
  if (detail && typeof detail === "object") return detail.message || detail.msg || fallback;
  return fallback;
}

export async function api(url, opts = {}) {
  const headers = new Headers(opts.headers || {});
  if (opts.body != null && typeof opts.body === "string" && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const r = await fetch(url, { ...opts, headers });
  if (r.status === 401) window.dispatchEvent(new Event("auth-expired"));
  if (!r.ok) {
    let detail;
    try {
      const body = await r.json();
      detail = body?.detail ?? body?.message;
    } catch {}
    const fallback = r.statusText || `Request failed (HTTP ${r.status})`;
    throw new Error(errorDetail(detail, fallback));
  }
  if (r.status === 204) return null;
  return r.json();
}
