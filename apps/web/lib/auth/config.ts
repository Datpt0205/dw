/**
 * Frontend auth configuration (baked at build time via NEXT_PUBLIC_*).
 *
 * `oidc` (default) drives the real Keycloak Authorization-Code + PKCE flow.
 * `dev` keeps the legacy one-click persona login for host `make dev` where
 * Keycloak may not be running.
 */

export type AuthMode = "oidc" | "dev";

export const AUTH_MODE: AuthMode =
  (process.env.NEXT_PUBLIC_AUTH_MODE as AuthMode) ?? "oidc";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export const KEYCLOAK_URL =
  process.env.NEXT_PUBLIC_KEYCLOAK_URL ?? "http://localhost:8080";

export const KEYCLOAK_REALM =
  process.env.NEXT_PUBLIC_KEYCLOAK_REALM ?? "dw";

export const KEYCLOAK_CLIENT_ID =
  process.env.NEXT_PUBLIC_KEYCLOAK_CLIENT_ID ?? "dw-web";
