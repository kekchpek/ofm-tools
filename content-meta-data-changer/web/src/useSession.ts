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
  logout: () => Promise<void>;
};

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

  useEffect(() => {
    void Promise.all([getAuthConfig(), getCurrentUser()])
      .then(([config, currentUser]) => {
        setAuthConfig(config);
        setUser(currentUser);
      })
      .finally(() => setAuthReady(true));
  }, []);

  useEffect(() => {
    if (!authReady) {
      return;
    }
    if (authConfig?.enabled && !user) {
      setSessionId(null);
      return;
    }
    void createSession().then(setSessionId);
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
    canUseApp: !authRequired || user !== null,
    logout,
  };
}
