import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { createOfm, deleteOfm, listOfms, loginUrl, type Ofm } from "./api/client";
import AppHeader from "./AppHeader";
import ConnectionError from "./ConnectionError";
import { useSession } from "./useSession";

export default function OfmListPage() {
  const navigate = useNavigate();
  const { authReady, authRequired, canUseApp, user, sessionId, error: sessionError, logout } =
    useSession();

  const [ofms, setOfms] = useState<Ofm[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState<string | null>(null);

  useEffect(() => {
    if (!sessionId || loaded) {
      return;
    }
    let cancelled = false;
    void listOfms()
      .then((result) => {
        if (!cancelled) setOfms(result);
      })
      .catch((cause) => {
        if (!cancelled) setError(String(cause));
      })
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId, loaded]);

  async function handleCreate(event: React.FormEvent) {
    event.preventDefault();
    const name = newName.trim();
    if (!name || creating) {
      return;
    }
    setCreating(true);
    try {
      const created = await createOfm(name);
      setNewName("");
      setOfms((current) => [...current, created]);
      navigate(`/factory/${created.id}`);
    } catch (cause) {
      setError(String(cause));
    } finally {
      setCreating(false);
    }
  }

  async function handleDelete(ofm: Ofm) {
    setConfirmingDelete(null);
    setOfms((current) => current.filter((item) => item.id !== ofm.id));
    try {
      await deleteOfm(ofm.id);
    } catch (cause) {
      setError(String(cause));
      setLoaded(false); // resync; the optimistic removal may have been wrong
    }
  }

  async function handleLogout() {
    await logout();
    navigate("/");
  }

  return (
    <div className="app">
      <AppHeader
        title="OFM Factory"
        subtitle="Pick an OFM to work in, or create a new one."
        authReady={authReady}
        authRequired={authRequired}
        user={user}
        onLogout={() => void handleLogout()}
        showBackLink
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
          <p>Sign in with your Google account to create and open OFMs.</p>
          <a className="auth-login-button" href={loginUrl("/factory")}>
            Sign in with Google
          </a>
        </section>
      ) : (
        <>
          <section className="panel">
            <h2>Create an OFM</h2>
            <p className="ofm-create-hint">
              An OFM holds content pieces and the people working on them. You can create as many as
              you need and invite others to any of them.
            </p>
            <form className="ofm-create-form" onSubmit={(event) => void handleCreate(event)}>
              <input
                className="ofm-create-input"
                value={newName}
                onChange={(event) => setNewName(event.target.value)}
                placeholder="OFM name, e.g. Summer campaign"
                maxLength={200}
                aria-label="New OFM name"
              />
              <button
                type="submit"
                className="generate-button"
                disabled={!newName.trim() || creating}
              >
                {creating ? "Creating…" : "Create OFM"}
              </button>
            </form>
          </section>

          {error && (
            <section className="panel">
              <p className="piece-error">{error}</p>
            </section>
          )}

          {loaded && ofms.length === 0 ? (
            <section className="panel piece-empty">
              <h2>No OFMs yet</h2>
              <p>Create your first OFM above to start building content pieces.</p>
            </section>
          ) : (
            <div className="ofm-grid">
              {ofms.map((ofm) => (
                <div className="panel ofm-card" key={ofm.id}>
                  <button
                    type="button"
                    className="ofm-card-open"
                    onClick={() => navigate(`/factory/${ofm.id}`)}
                  >
                    <span className="ofm-card-name">{ofm.name}</span>
                    <span className="ofm-card-meta">
                      {ofm.piece_count} {ofm.piece_count === 1 ? "piece" : "pieces"} ·{" "}
                      {ofm.member_count} {ofm.member_count === 1 ? "member" : "members"}
                    </span>
                    <span className={`ofm-role ofm-role-${ofm.role}`}>
                      {ofm.is_owner ? "Owner" : "Editor"}
                    </span>
                  </button>

                  {ofm.can_delete &&
                    (confirmingDelete === ofm.id ? (
                      <div className="ofm-confirm">
                        <span>Delete “{ofm.name}” and all its pieces?</span>
                        <button
                          type="button"
                          className="ofm-confirm-yes"
                          onClick={() => void handleDelete(ofm)}
                        >
                          Delete
                        </button>
                        <button type="button" onClick={() => setConfirmingDelete(null)}>
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <button
                        type="button"
                        className="piece-remove"
                        onClick={() => setConfirmingDelete(ofm.id)}
                      >
                        Delete
                      </button>
                    ))}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
