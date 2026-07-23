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
} as const;

export interface DevSession {
  token: string;
  tenantId: string;
  workspaceId: string;
}

export function loadSession(): DevSession | null {
  if (typeof window === "undefined") return null;
  const token = window.localStorage.getItem(KEYS.token);
  const tenantId = window.localStorage.getItem(KEYS.tenant);
  const workspaceId = window.localStorage.getItem(KEYS.workspace);
  if (!token || !tenantId || !workspaceId) return null;
  return { token, tenantId, workspaceId };
}

export function saveSession(session: DevSession): void {
  window.localStorage.setItem(KEYS.token, session.token);
  window.localStorage.setItem(KEYS.tenant, session.tenantId);
  window.localStorage.setItem(KEYS.workspace, session.workspaceId);
}

export function clearSession(): void {
  for (const key of Object.values(KEYS)) window.localStorage.removeItem(key);
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
