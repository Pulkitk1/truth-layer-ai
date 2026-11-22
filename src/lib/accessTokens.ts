/**
 * Per-document access tokens.
 *
 * Uploading a PDF returns a secret token that proves ownership of that document. It is sent only in the
 * `Authorization` header, never in a URL (URLs end up in history and logs) and never logged.
 *
 * Where it lives: localStorage, keyed by document id, so a document's results can be reopened later in this
 * browser. Anything in localStorage can be read by a script running on this page, which is why the site sends a
 * strict Content-Security-Policy and loads no third-party scripts. Storage can be unavailable (private mode), so
 * there is an in-memory fallback that lasts for the current page visit. Only the most recent documents are kept.
 */
const KEY = "truthlayer:access-tokens";
const MAX_TOKENS = 20;

const memory = new Map<string, string>();

function read(): Record<string, string> {
  try {
    const raw = window.localStorage.getItem(KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : {};
    return parsed && typeof parsed === "object" ? (parsed as Record<string, string>) : {};
  } catch {
    return {};
  }
}

function write(map: Record<string, string>) {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(map));
  } catch {
    /* blocked or full: the in-memory copy still works for this visit */
  }
}

export function saveToken(fileId: string, token: string) {
  memory.set(fileId, token);
  const map = read();
  delete map[fileId]; // re-insert so the newest document is last
  map[fileId] = token;
  const ids = Object.keys(map);
  for (const old of ids.slice(0, Math.max(0, ids.length - MAX_TOKENS))) delete map[old];
  write(map);
}

export function getToken(fileId: string): string | null {
  return memory.get(fileId) ?? read()[fileId] ?? null;
}

export function forgetToken(fileId: string) {
  memory.delete(fileId);
  const map = read();
  delete map[fileId];
  write(map);
}

/** Request headers that prove ownership of a document (empty if this browser has no token for it). */
export function authHeaders(fileId: string): Record<string, string> {
  const token = getToken(fileId);
  return token ? { Authorization: `Bearer ${token}` } : {};
}
