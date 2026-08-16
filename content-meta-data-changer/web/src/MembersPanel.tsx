import { useEffect, useState } from "react";
import { inviteMember, listMembers, removeMember, type OfmMember } from "./api/client";

type MembersPanelProps = {
  ofmId: string;
};

/**
 * Invite people to an OFM by email.
 *
 * Every member may invite and remove others — only deleting the OFM itself is
 * owner-only today. The server is the authority on that; this panel just
 * reports what it returns.
 */
export default function MembersPanel({ ofmId }: MembersPanelProps) {
  const [members, setMembers] = useState<OfmMember[]>([]);
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void listMembers(ofmId)
      .then((result) => {
        if (!cancelled) setMembers(result);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [ofmId]);

  async function handleInvite(event: React.FormEvent) {
    event.preventDefault();
    const value = email.trim();
    if (!value || busy) return;
    setBusy(true);
    setError(null);
    try {
      const member = await inviteMember(ofmId, value);
      setMembers((current) =>
        current.some((item) => item.id === member.id) ? current : [...current, member],
      );
      setEmail("");
    } catch (cause) {
      setError(String(cause));
    } finally {
      setBusy(false);
    }
  }

  async function handleRemove(member: OfmMember) {
    setError(null);
    const previous = members;
    setMembers((current) => current.filter((item) => item.id !== member.id));
    try {
      await removeMember(ofmId, member.id);
    } catch (cause) {
      setError(String(cause));
      setMembers(previous);
    }
  }

  return (
    <section className="panel members-panel">
      <button type="button" className="members-toggle" onClick={() => setOpen((value) => !value)}>
        <span>
          People · {members.length} {members.length === 1 ? "member" : "members"}
        </span>
        <span className="members-chevron">{open ? "▾" : "▸"}</span>
      </button>

      {open && (
        <>
          <ul className="members-list">
            {members.map((member) => (
              <li className="members-row" key={member.id}>
                <span className="members-email">{member.email}</span>
                <span className={`ofm-role ofm-role-${member.role}`}>
                  {member.role === "owner" ? "Owner" : "Editor"}
                </span>
                {!member.accepted && <span className="members-pending">Invited</span>}
                {member.role !== "owner" && (
                  <button
                    type="button"
                    className="members-remove"
                    onClick={() => void handleRemove(member)}
                  >
                    Remove
                  </button>
                )}
              </li>
            ))}
          </ul>

          <form className="members-invite" onSubmit={(event) => void handleInvite(event)}>
            <input
              className="output-name-input members-invite-input"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="teammate@example.com"
              aria-label="Email address to invite"
            />
            <button type="submit" className="generate-button" disabled={!email.trim() || busy}>
              {busy ? "Inviting…" : "Invite"}
            </button>
          </form>
          <p className="members-hint">
            They can accept with any Google account using this email address — an invitation works
            even if they have never signed in before.
          </p>
          {error && <p className="piece-error">{error}</p>}
        </>
      )}
    </section>
  );
}
