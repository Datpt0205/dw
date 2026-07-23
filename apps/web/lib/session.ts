"use client";

import { ApiClient } from "@dw/api-client";

/**
 * Dev session (ADR-013): bearer token + tenant/workspace ids live in
 * localStorage, entered on the Admin page. The backend re-verifies everything —
 * this is convenience, never authorization.
 */

const KEYS = {
  token: "dw.dev.token",
  tenant: "dw.dev.tenantId",
  workspace: "dw.dev.workspaceId",
  profile: "dw.dev.profile",
} as const;

export interface DevSession {
  token: string;
  tenantId: string;
  workspaceId: string;
  /** Display info from one-click login (absent when pasted manually). */
  subject?: string;
  displayName?: string;
  tenantName?: string;
  roles?: string[];
}

export function loadSession(): DevSession | null {
  if (typeof window === "undefined") return null;
  const token = window.localStorage.getItem(KEYS.token);
  const tenantId = window.localStorage.getItem(KEYS.tenant);
  const workspaceId = window.localStorage.getItem(KEYS.workspace);
  if (!token || !tenantId || !workspaceId) return null;
  const session: DevSession = { token, tenantId, workspaceId };
  const rawProfile = window.localStorage.getItem(KEYS.profile);
  if (rawProfile) {
    try {
      Object.assign(session, JSON.parse(rawProfile) as Partial<DevSession>);
    } catch {
      // ignore a corrupt profile blob — core session fields still work
    }
  }
  return session;
}

export function saveSession(session: DevSession): void {
  window.localStorage.setItem(KEYS.token, session.token);
  window.localStorage.setItem(KEYS.tenant, session.tenantId);
  window.localStorage.setItem(KEYS.workspace, session.workspaceId);
  const { subject, displayName, tenantName, roles } = session;
  window.localStorage.setItem(
    KEYS.profile,
    JSON.stringify({ subject, displayName, tenantName, roles }),
  );
}

export function clearSession(): void {
  for (const key of Object.values(KEYS)) window.localStorage.removeItem(key);
}

/** One-click demo login: exchange a roster subject for a full session. */
export async function loginAs(subject: string): Promise<DevSession> {
  const info = await apiClient().createDevSession(subject);
  const session: DevSession = {
    token: info.token,
    tenantId: info.tenant_id,
    workspaceId: info.workspace_id,
    subject: info.subject,
    displayName: info.display_name,
    tenantName: info.tenant_name,
    roles: info.roles,
  };
  saveSession(session);
  return session;
}

export function apiClient(): ApiClient {
  return new ApiClient({
    baseUrl: process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000",
    getAccessToken: () => loadSession()?.token ?? null,
    fetchImpl: (input, init) => {
      const session = loadSession();
      const headers = new Headers(init?.headers);
      if (session) {
        headers.set("X-Tenant-Id", session.tenantId);
        headers.set("X-Workspace-Id", session.workspaceId);
      }
      return fetch(input, { ...init, headers });
    },
  });
}

/** Demo roles that may create content (approver chỉ duyệt). */
export function canCreate(session: DevSession | null): boolean {
  if (!session) return false;
  if (!session.roles) return true; // manual session: let the API decide
  return session.roles.some((r) => r === "member" || r === "platform_admin");
}
