export async function api(url, opts) {
  const r = await fetch(url, opts);
  if (r.status === 401) window.dispatchEvent(new Event("auth-expired"));
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return r.json();
}