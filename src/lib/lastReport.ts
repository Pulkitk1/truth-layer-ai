const KEY = "truthlayer:lastFileId";

/** Remembers which document's results to show on /results. Storage can be unavailable, so never throw. */
export function rememberReport(fileId: string) {
  try {
    window.localStorage.setItem(KEY, fileId);
  } catch {
    /* private mode or blocked storage: the ?file= link still works */
  }
}

export function recallReport(): string | null {
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function forgetReport() {
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}
