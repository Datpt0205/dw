"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { API_BASE_URL, AUTH_MODE } from "./config";
import { getKeycloak } from "./keycloak";
import {
  activeQuickToken,
  activeQuickUsername,
  clearActiveWorkspace,
  clearDevToken,
  devToken,
  setActiveWorkspace,
} from "../session";

export interface Membership {
  tenantId: string;
  tenantSlug: string;
  tenantName: string;
  workspaceId: string;
  workspaceSlug: string;
  workspaceName: string;
  roles: string[];
  scopes: string[];
}

export type AuthStatus =
  "loading" | "unauthenticated" | "no-workspace" | "error" | "ready";

interface AuthContextValue {
  mode: typeof AUTH_MODE;
  status: AuthStatus;
  error: string | null;
  subject: string | null;
  displayName: string;
  email: string | null;
  memberships: Membership[];
  active: Membership | null;
  roles: string[];
  scopes: string[];
  hasScope: (scope: string) => boolean;
  hasRole: (role: string) => boolean;
  login: () => void;
  register: () => void;
  logout: () => void;
  selectWorkspace: (workspaceId: string) => void;
  refreshDevSession: () => void;
}

interface BootstrapMembership {
  tenant_id: string;
  tenant_slug: string;
  tenant_name: string;
  workspace_id: string;
  workspace_slug: string;
  workspace_name: string;
  roles: string[];
  scopes: string[];
}

interface BootstrapResponse {
  principal_id: string;
  subject: string;
  email: string | null;
  display_name: string;
  memberships: BootstrapMembership[];
}

const AuthContext = createContext<AuthContextValue | null>(null);

function mapMembership(m: BootstrapMembership): Membership {
  return {
    tenantId: m.tenant_id,
    tenantSlug: m.tenant_slug,
    tenantName: m.tenant_name,
    workspaceId: m.workspace_id,
    workspaceSlug: m.workspace_slug,
    workspaceName: m.workspace_name,
    roles: m.roles,
    scopes: m.scopes,
  };
}

async function fetchBootstrap(token: string): Promise<BootstrapResponse> {
  const res = await fetch(`${API_BASE_URL}/api/v1/auth/bootstrap`, {
    headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
  });
  if (!res.ok) {
    throw new Error(`bootstrap failed (HTTP ${res.status})`);
  }
  return (await res.json()) as BootstrapResponse;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [error, setError] = useState<string | null>(null);
  const [subject, setSubject] = useState<string | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState<string | null>(null);
  const [memberships, setMemberships] = useState<Membership[]>([]);
  const [active, setActive] = useState<Membership | null>(null);
  const initStarted = useRef(false);

  const activate = useCallback(
    (m: Membership, identity: { subject: string; displayName: string }) => {
      setActive(m);
      setActiveWorkspace({
        tenantId: m.tenantId,
        workspaceId: m.workspaceId,
        subject: identity.subject,
        displayName: identity.displayName,
        tenantName: m.tenantName,
        roles: m.roles,
        scopes: m.scopes,
      });
    },
    [],
  );

  const applyBootstrap = useCallback(
    (data: BootstrapResponse) => {
      const list = data.memberships.map(mapMembership);
      setSubject(data.subject);
      setDisplayName(data.display_name);
      setEmail(data.email);
      setMemberships(list);
      if (list.length === 0) {
        setStatus("no-workspace");
        return;
      }
      const previous =
        typeof window !== "undefined"
          ? window.localStorage.getItem("dw.active.workspaceId")
          : null;
      const chosen = list.find((m) => m.workspaceId === previous) ?? list[0]!;
      activate(chosen, {
        subject: data.subject,
        displayName: data.display_name,
      });
      setStatus("ready");
    },
    [activate],
  );

  const loadDevSession = useCallback(() => {
    const token = devToken();
    if (!token) {
      setStatus("unauthenticated");
      return;
    }
    setStatus("loading");
    fetchBootstrap(token)
      .then(applyBootstrap)
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : "bootstrap error");
        setStatus("error");
      });
  }, [applyBootstrap]);

  useEffect(() => {
    if (initStarted.current) return;
    initStarted.current = true;

    if (AUTH_MODE === "dev") {
      loadDevSession();
      return;
    }

    // Fast account switcher (demo): if a quick account is active, bootstrap with
    // its stored token and skip the Keycloak redirect handshake entirely.
    if (activeQuickUsername()) {
      void (async () => {
        const token = await activeQuickToken();
        if (!token) {
          setStatus("unauthenticated");
          return;
        }
        try {
          applyBootstrap(await fetchBootstrap(token));
        } catch (e) {
          setError(e instanceof Error ? e.message : "bootstrap error");
          setStatus("error");
        }
      })();
      return;
    }

    const kc = getKeycloak();
    kc.init({
      onLoad: "check-sso",
      pkceMethod: "S256",
      silentCheckSsoRedirectUri:
        typeof window !== "undefined"
          ? `${window.location.origin}/silent-check-sso.html`
          : undefined,
      checkLoginIframe: false,
    })
      .then(async (authenticated) => {
        if (!authenticated || !kc.token) {
          setStatus("unauthenticated");
          return;
        }
        kc.onTokenExpired = () => {
          void kc.updateToken(30);
        };
        try {
          applyBootstrap(await fetchBootstrap(kc.token));
        } catch (e) {
          setError(e instanceof Error ? e.message : "bootstrap error");
          setStatus("error");
        }
      })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : "keycloak init failed");
        setStatus("error");
      });
  }, [applyBootstrap, loadDevSession]);

  const login = useCallback(() => {
    if (AUTH_MODE === "dev") {
      window.location.href = "/dev-login";
      return;
    }
    void getKeycloak().login({ redirectUri: window.location.origin });
  }, []);

  const register = useCallback(() => {
    if (AUTH_MODE === "dev") {
      window.location.href = "/dev-login";
      return;
    }
    void getKeycloak().register({ redirectUri: window.location.origin });
  }, []);

  const logout = useCallback(() => {
    // A quick-account session was never established through the Keycloak JS
    // adapter, so kc.logout() would throw/bounce. Just clear local state and
    // return to the app root, which renders the login screen.
    const wasQuick = activeQuickUsername() !== null;
    clearActiveWorkspace();
    if (AUTH_MODE === "dev") {
      clearDevToken();
      window.location.href = "/dev-login";
      return;
    }
    if (wasQuick) {
      window.location.href = "/";
      return;
    }
    void getKeycloak().logout({ redirectUri: window.location.origin });
  }, []);

  const selectWorkspace = useCallback(
    (workspaceId: string) => {
      const m = memberships.find((x) => x.workspaceId === workspaceId);
      if (!m) return;
      activate(m, { subject: subject ?? "", displayName });
      setStatus("ready");
    },
    [memberships, activate, subject, displayName],
  );

  const value = useMemo<AuthContextValue>(() => {
    const roles = active?.roles ?? [];
    const scopes = active?.scopes ?? [];
    return {
      mode: AUTH_MODE,
      status,
      error,
      subject,
      displayName,
      email,
      memberships,
      active,
      roles,
      scopes,
      hasScope: (scope: string) =>
        roles.includes("platform_admin") || scopes.includes(scope),
      hasRole: (role: string) => roles.includes(role),
      login,
      register,
      logout,
      selectWorkspace,
      refreshDevSession: loadDevSession,
    };
  }, [
    status,
    error,
    subject,
    displayName,
    email,
    memberships,
    active,
    login,
    register,
    logout,
    selectWorkspace,
    loadDevSession,
  ]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (ctx === null) {
    throw new Error("useAuth must be used within <AuthProvider>");
  }
  return ctx;
}
