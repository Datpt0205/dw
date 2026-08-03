"use client";

import { ApiClient } from "@dw/api-client";
import {
  API_BASE_URL,
  AUTH_MODE,
  KEYCLOAK_CLIENT_ID,
  KEYCLOAK_REALM,
  KEYCLOAK_URL,
} from "./auth/config";
import { getKeycloak } from "./auth/keycloak";

/**
 * Session bridge. The access token is never persisted: in `oidc` mode it lives
 * in the keycloak-js instance (in memory), in `dev` mode it is a local HS256
 * token. Only the *active workspace* (tenant/workspace ids + a display profile)
 * is kept in localStorage — those are not secrets. The backend re-verifies every
 * request, so this is convenience, never authorization.
 */

const KEYS = {
  tenant: "dw.active.tenantId",
  workspace: "dw.active.workspaceId",
  profile: "dw.active.profile",
  devToken: "dw.dev.token",
  quickAccounts: "dw.quick.accounts",
  quickActive: "dw.quick.active",
} as const;

/**
 * Fast account switcher (demo convenience, OIDC mode). Each account keeps its
 * OIDC tokens in localStorage so the presenter can jump between An/Bình/Chi
 * without re-entering a password. Tokens are refreshed on demand. This is a
 * demo tool — it is NOT how production sessions should be stored.
 */
export interface QuickAccount {
  username: string;
  displayName: string;
  roles: string[];
  token: string;
  refreshToken: string;
  expiresAt: number;
  savedAt: number;
}

const TOKEN_URL = `${KEYCLOAK_URL}/realms/${KEYCLOAK_REALM}/protocol/openid-connect/token`;

function readQuickAccounts(): Record<string, QuickAccount> {
  if (typeof window === "undefined") return {};
  try {
    return JSON.parse(
      window.localStorage.getItem(KEYS.quickAccounts) || "{}",
    ) as Record<string, QuickAccount>;
  } catch {
    return {};
  }
}

function writeQuickAccounts(map: Record<string, QuickAccount>): void {
  window.localStorage.setItem(KEYS.quickAccounts, JSON.stringify(map));
}

function decodeToken(token: string): {
  name?: string;
  preferred_username?: string;
  realm_access?: { roles?: string[] };
} {
  try {
    const part = token.split(".")[1] ?? "";
    return JSON.parse(atob(part.replace(/-/g, "+").replace(/_/g, "/")));
  } catch {
    return {};
  }
}

function toAccount(
  username: string,
  data: { access_token: string; refresh_token: string; expires_in: number },
): QuickAccount {
  const claims = decodeToken(data.access_token);
  return {
    username,
    displayName: claims.name || claims.preferred_username || username,
    roles:
      claims.realm_access?.roles?.filter(
        (r) =>
          !r.startsWith("default-") &&
          r !== "offline_access" &&
          r !== "uma_authorization",
      ) ?? [],
    token: data.access_token,
    refreshToken: data.refresh_token,
    expiresAt: Date.now() + (data.expires_in - 30) * 1000,
    savedAt: Date.now(),
  };
}

export function activeQuickUsername(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(KEYS.quickActive);
}

/** Password-grant login for a demo persona; stores tokens + makes it active. */
export async function quickLogin(
  username: string,
  password: string,
): Promise<QuickAccount> {
  const res = await fetch(TOKEN_URL, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "password",
      client_id: KEYCLOAK_CLIENT_ID,
      username,
      password,
      scope: "openid",
    }),
  });
  if (!res.ok) throw new Error("Đăng nhập nhanh thất bại (kiểm tra mật khẩu)");
  const account = toAccount(username, await res.json());
  const map = readQuickAccounts();
  map[username] = account;
  writeQuickAccounts(map);
  window.localStorage.setItem(KEYS.quickActive, username);
  return account;
}

function clearQuickActive(): void {
  if (typeof window !== "undefined")
    window.localStorage.removeItem(KEYS.quickActive);
}

/** Public: token for the active quick account (used by the auth bootstrap). */
export async function activeQuickToken(): Promise<string | null> {
  return quickAccessToken();
}

/** Token for the active quick account, refreshing via refresh_token if stale. */
async function quickAccessToken(): Promise<string | null> {
  const username = activeQuickUsername();
  if (!username) return null;
  const map = readQuickAccounts();
  const acc = map[username];
  if (!acc) return null;
  if (Date.now() < acc.expiresAt) return acc.token;
  try {
    const res = await fetch(TOKEN_URL, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type: "refresh_token",
        client_id: KEYCLOAK_CLIENT_ID,
        refresh_token: acc.refreshToken,
      }),
    });
    // Refresh token also expired/invalid → the session is truly over. Drop the
    // dead account and report "no token" so the app returns to login cleanly,
    // instead of sending an expired token that 401s into an error screen.
    if (!res.ok) {
      clearQuickActive();
      return null;
    }
    const refreshed = toAccount(username, await res.json());
    map[username] = refreshed;
    writeQuickAccounts(map);
    return refreshed.token;
  } catch {
    // Network error refreshing — keep the account but signal no usable token.
    return null;
  }
}

export interface Session {
  tenantId: string;
  workspaceId: string;
  subject?: string;
  displayName?: string;
  tenantName?: string;
  roles?: string[];
  scopes?: string[];
}

export interface ActiveWorkspace {
  tenantId: string;
  workspaceId: string;
  subject?: string;
  displayName?: string;
  tenantName?: string;
  roles: string[];
  scopes: string[];
}

export function loadSession(): Session | null {
  if (typeof window === "undefined") return null;
  const tenantId = window.localStorage.getItem(KEYS.tenant);
  const workspaceId = window.localStorage.getItem(KEYS.workspace);
  if (!tenantId || !workspaceId) return null;
  const session: Session = { tenantId, workspaceId };
  const raw = window.localStorage.getItem(KEYS.profile);
  if (raw) {
    try {
      Object.assign(session, JSON.parse(raw) as Partial<Session>);
    } catch {
      // ignore a corrupt profile blob — core fields still work
    }
  }
  return session;
}

export function setActiveWorkspace(active: ActiveWorkspace): void {
  window.localStorage.setItem(KEYS.tenant, active.tenantId);
  window.localStorage.setItem(KEYS.workspace, active.workspaceId);
  const { subject, displayName, tenantName, roles, scopes } = active;
  window.localStorage.setItem(
    KEYS.profile,
    JSON.stringify({ subject, displayName, tenantName, roles, scopes }),
  );
}

export function clearActiveWorkspace(): void {
  window.localStorage.removeItem(KEYS.tenant);
  window.localStorage.removeItem(KEYS.workspace);
  window.localStorage.removeItem(KEYS.profile);
  clearQuickActive();
}

/** Dev-mode only: store the local bearer token. */
export function setDevToken(token: string): void {
  window.localStorage.setItem(KEYS.devToken, token);
}

export function devToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(KEYS.devToken);
}

export function clearDevToken(): void {
  window.localStorage.removeItem(KEYS.devToken);
}

/** Dev-mode one-click login: exchange a roster subject for a local token.
 * The active workspace + scopes are then resolved via /auth/bootstrap. */
export async function loginAsDev(subject: string): Promise<void> {
  const info = await apiClient().createDevSession(subject);
  setDevToken(info.token);
}

async function currentAccessToken(): Promise<string | null> {
  if (AUTH_MODE === "dev") {
    return typeof window === "undefined"
      ? null
      : window.localStorage.getItem(KEYS.devToken);
  }
  // Fast account switcher (demo) takes precedence when a quick account is active.
  const quick = await quickAccessToken();
  if (quick) return quick;
  const kc = getKeycloak();
  if (!kc.authenticated) return null;
  try {
    await kc.updateToken(30);
  } catch {
    return null;
  }
  return kc.token ?? null;
}

// Guard so a burst of concurrent 401s triggers exactly one redirect.
let redirectingOn401 = false;

export function apiClient(): ApiClient {
  return new ApiClient({
    baseUrl: API_BASE_URL,
    getAccessToken: currentAccessToken,
    fetchImpl: async (input, init) => {
      const headers = new Headers(init?.headers);
      if (typeof window !== "undefined") {
        const tenantId = window.localStorage.getItem(KEYS.tenant);
        const workspaceId = window.localStorage.getItem(KEYS.workspace);
        if (tenantId && workspaceId) {
          headers.set("X-Tenant-Id", tenantId);
          headers.set("X-Workspace-Id", workspaceId);
        }
      }
      const res = await fetch(input, { ...init, headers });
      // 401 = the session is no longer authenticated (token died mid-use).
      // Clear local state and bounce to the login screen instead of leaving the
      // user staring at a failed action. (403 = permission, handled per-call.)
      if (
        res.status === 401 &&
        typeof window !== "undefined" &&
        !redirectingOn401
      ) {
        redirectingOn401 = true;
        clearActiveWorkspace();
        window.location.href = "/";
      }
      return res;
    },
  });
}

/**
 * UI permission helper mirroring the backend rule: `platform_admin` bypasses
 * scope checks; otherwise the scope must be present. This only hides/disables
 * controls for clarity — the API is the sole authority.
 */
export function hasScope(session: Session | null, scope: string): boolean {
  if (!session) return false;
  if (session.roles?.includes("platform_admin")) return true;
  return session.scopes?.includes(scope) ?? false;
}

export function hasRole(session: Session | null, role: string): boolean {
  return session?.roles?.includes(role) ?? false;
}

/** May the current session create tender/work-ops content? */
export function canCreate(session: Session | null): boolean {
  return (
    hasScope(session, "tender.write") || hasScope(session, "work_ops.write")
  );
}
