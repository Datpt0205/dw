"use client";

import { ApiClient } from "@dw/api-client";
import { API_BASE_URL, AUTH_MODE } from "./auth/config";
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
} as const;

export interface Session {
  tenantId: string;
  workspaceId: string;
  subject?: string;
  displayName?: string;
  tenantName?: string;
  roles?: string[];
  scopes?: string[];
}

/** Back-compat alias for components that still import the old name. */
export type DevSession = Session;

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
  const kc = getKeycloak();
  if (!kc.authenticated) return null;
  try {
    await kc.updateToken(30);
  } catch {
    return null;
  }
  return kc.token ?? null;
}

export function apiClient(): ApiClient {
  return new ApiClient({
    baseUrl: API_BASE_URL,
    getAccessToken: currentAccessToken,
    fetchImpl: (input, init) => {
      const headers = new Headers(init?.headers);
      if (typeof window !== "undefined") {
        const tenantId = window.localStorage.getItem(KEYS.tenant);
        const workspaceId = window.localStorage.getItem(KEYS.workspace);
        if (tenantId && workspaceId) {
          headers.set("X-Tenant-Id", tenantId);
          headers.set("X-Workspace-Id", workspaceId);
        }
      }
      return fetch(input, { ...init, headers });
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
