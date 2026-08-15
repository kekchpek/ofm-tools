import { useNavigate } from "react-router-dom";
import { loginUrl } from "./api/client";
import AppHeader from "./AppHeader";
import ConnectionError from "./ConnectionError";
import { useSession } from "./useSession";

type Tool = {
  path: string;
  title: string;
  tagline: string;
  description: string;
  bullets: string[];
};

const TOOLS: Tool[] = [
  {
    path: "/editor",
    title: "Edit content",
    tagline: "Inspect and modify a single file",
    description:
      "Open a photo or video to read its metadata, walk its byte-level memory layout, transfer metadata between files, convert formats, and refresh the embedded preview.",
    bullets: ["Metadata inspector", "Memory layout map", "Convert and transfer"],
  },
  {
    path: "/factory",
    title: "OFM Factory",
    tagline: "Batch-build content pieces",
    description:
      "Set up content pieces side by side. Each one takes the picture or footage from your source file and rebuilds it in the format of a donor file, wearing that donor's metadata.",
    bullets: ["Many pieces at once", "Source + metadata per piece", "One-click generate"],
  },
];

export default function HomePage() {
  const navigate = useNavigate();
  const { authReady, authRequired, canUseApp, user, error: sessionError, logout } = useSession();

  async function handleLogout() {
    await logout();
    navigate("/");
  }

  return (
    <div className="app">
      <AppHeader
        title="Content Metadata Changer"
        subtitle="Choose what you want to do."
        authReady={authReady}
        authRequired={authRequired}
        user={user}
        onLogout={() => void handleLogout()}
      />

      {!authReady ? (
        <section className="panel">
          <p>Loading…</p>
        </section>
      ) : sessionError ? (
        <ConnectionError message={sessionError} />
      ) : !canUseApp ? (
        <section className="panel auth-panel">
          <h2>Sign in required</h2>
          <p>Sign in with your Google account to upload files and run metadata jobs.</p>
          <a className="auth-login-button" href={loginUrl("/")}>
            Sign in with Google
          </a>
        </section>
      ) : (
        <section className="tool-picker">
          {TOOLS.map((tool) => (
            <button
              key={tool.path}
              type="button"
              className="tool-card"
              onClick={() => navigate(tool.path)}
            >
              <span className="tool-card-tagline">{tool.tagline}</span>
              <span className="tool-card-title">{tool.title}</span>
              <span className="tool-card-description">{tool.description}</span>
              <ul className="tool-card-bullets">
                {tool.bullets.map((bullet) => (
                  <li key={bullet}>{bullet}</li>
                ))}
              </ul>
              <span className="tool-card-action">Open →</span>
            </button>
          ))}
        </section>
      )}
    </div>
  );
}
