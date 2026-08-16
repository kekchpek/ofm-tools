import { Link } from "react-router-dom";
import { loginUrl, type User } from "./api/client";

type AppHeaderProps = {
  title: string;
  subtitle: string;
  authReady: boolean;
  authRequired: boolean;
  user: User | null;
  onLogout: () => void;
  /** Shown on inner pages so users can get back up a level. */
  showBackLink?: boolean;
  /** Where the back link goes, and what it is called. */
  backTo?: string;
  backLabel?: string;
};

export default function AppHeader({
  title,
  subtitle,
  authReady,
  authRequired,
  user,
  onLogout,
  showBackLink = false,
  backTo = "/",
  backLabel = "All tools",
}: AppHeaderProps) {
  return (
    <header className="header">
      <div className="header-row">
        <div>
          {showBackLink && (
            <Link className="back-link" to={backTo}>
              ← {backLabel}
            </Link>
          )}
          <h1>{title}</h1>
          <p>{subtitle}</p>
        </div>
        {authReady && authRequired && (
          <div className="auth-bar">
            {user ? (
              <>
                {user.picture_url ? <img className="auth-avatar" src={user.picture_url} alt="" /> : null}
                <span className="auth-name">{user.name}</span>
                <button type="button" onClick={onLogout}>
                  Sign out
                </button>
              </>
            ) : (
              <a className="auth-login-button" href={loginUrl(window.location.pathname)}>
                Sign in with Google
              </a>
            )}
          </div>
        )}
      </div>
    </header>
  );
}
