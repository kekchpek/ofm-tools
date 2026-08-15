import { useCallback, useEffect, useState } from "react";
import {
  createSession,
  getAuthConfig,
  getCurrentUser,
  logout as logoutRequest,
  type AuthConfig,
  type User,
} from "./api/client";

export type SessionState = {
  authConfig: AuthConfig | null;
  user: User | null;
  authReady: boolean;
  sessionId: string | null;
  /** True once sign-in requirements (if any) are satisfied. */
  canUseApp: boolean;
  authRequired: boolean;
  /** Set when the API could not be reached or answered unexpectedly. */
  error: string | null;
  logout: () => Promise<void>;
};

function describe(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/**
 * Auth config, signed-in user, and an upload session.
 *
 * Shared by every page so the sign-in gate and session bootstrap behave
 * identically in the editor and in OFM Factory.
 */
export function useSession(): SessionState {
  const [authConfig, setAuthConfig] = useState<AuthConfig | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [config, currentUser] = await Promise.all([getAuthConfig(), getCurrentUser()]);
        if (cancelled) return;
        setAuthConfig(config);
        setUser(currentUser);
        setError(null);
      } catch (cause) {
        // Without this the app would silently behave as if auth were disabled
        // and then fail later with a confusing "session is not ready".
        if (!cancelled) setError((previous) => previous ?? describe(cause));
      } finally {
        if (!cancelled) setAuthReady(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!authReady) {
      return;
    }
    if (authConfig?.enabled && !user) {
      setSessionId(null);
      return;
    }
    let cancelled = false;
    void createSession()
      .then((id) => {
        if (cancelled) return;
        setSessionId(id);
        setError(null);
      })
      .catch((cause) => {
        // Keep the earliest failure: when CORS blocks everything, the auth
        // lookup fails first and names the more diagnostic endpoint.
        if (!cancelled) setError((previous) => previous ?? describe(cause));
      });
    return () => {
      cancelled = true;
    };
  }, [authReady, authConfig?.enabled, user]);

  const logout = useCallback(async () => {
    await logoutRequest();
    setUser(null);
    setSessionId(null);
  }, []);

  const authRequired = authConfig?.enabled === true;

  return {
    authConfig,
    user,
    authReady,
    sessionId,
    authRequired,
    error,
    // A failed auth lookup must not read as "no sign-in needed".
    canUseApp: error === null && (!authRequired || user !== null),
    logout,
  };
}
