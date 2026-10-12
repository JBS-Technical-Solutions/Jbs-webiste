import type { Account } from "./types";

const ACCOUNT_KEY = "hazop-studio:account";
const ACCOUNT_EVENT = "hazop-studio:account-changed";

interface Stored {
  token: string;
  user: Account;
}

export function subscribeAccount(cb: () => void) {
  window.addEventListener("storage", cb);
  window.addEventListener(ACCOUNT_EVENT, cb);
  return () => {
    window.removeEventListener("storage", cb);
    window.removeEventListener(ACCOUNT_EVENT, cb);
  };
}

/** Raw stored JSON (a stable string for useSyncExternalStore); parse with `parseAccount`. */
export function accountSnapshot() {
  return localStorage.getItem(ACCOUNT_KEY);
}

export function parseAccount(raw: string | null): Stored | null {
  if (!raw) return null;
  try {
    const v = JSON.parse(raw) as Stored;
    return v?.token && v.user ? v : null;
  } catch {
    return null;
  }
}

export function storedToken() {
  return typeof window === "undefined" ? null : (parseAccount(accountSnapshot())?.token ?? null);
}

export function saveAccount(token: string, user: Account) {
  localStorage.setItem(ACCOUNT_KEY, JSON.stringify({ token, user }));
  window.dispatchEvent(new Event(ACCOUNT_EVENT));
}

export function clearAccount() {
  localStorage.removeItem(ACCOUNT_KEY);
  window.dispatchEvent(new Event(ACCOUNT_EVENT));
}

/** Email the company inbox about a new sign-up (same Web3Forms account as the website's contact form). */
export async function notifySignup(user: Account) {
  const accessKey = process.env.NEXT_PUBLIC_WEB3FORMS_ACCESS_KEY;
  if (!accessKey) return;
  const data = new FormData();
  data.append("access_key", accessKey);
  data.append("subject", `New HAZOP Studio sign-up: ${user.first_name} ${user.last_name} (${user.company})`);
  data.append("from_name", "HAZOP Studio");
  data.append("name", `${user.first_name} ${user.last_name}`);
  data.append("email", user.email);
  data.append("company", user.company);
  data.append("role", user.role);
  try {
    await fetch("https://api.web3forms.com/submit", { method: "POST", body: data });
  } catch {
    /* the sign-up is already saved on the server */
  }
}
