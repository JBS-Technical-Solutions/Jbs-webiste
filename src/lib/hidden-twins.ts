/** Twins that are live on a direct URL only — not listed on Digital Twins. */
export const HIDDEN_TWIN_PATHS = ["/digital-twins/methanol-heating-media"] as const;

export function isHiddenTwinPath(pathname: string | null | undefined) {
  if (!pathname) return false;
  return HIDDEN_TWIN_PATHS.some((path) => pathname === path || pathname.startsWith(`${path}/`));
}
