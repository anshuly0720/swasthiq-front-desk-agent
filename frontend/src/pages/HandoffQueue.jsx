import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { clockOf, getHandoffs, getStats, REASON_LABEL, REASON_TONE, resolveHandoff } from "../api.js";

export default function HandoffQueue() {
  const navigate = useNavigate();
  const [stats, setStats] = useState(null);
  const [handoffs, setHandoffs] = useState([]);
  const [error, setError] = useState(null);

  async function load() {
    try {
      const [nextStats, nextHandoffs] = await Promise.all([getStats(), getHandoffs()]);
      setStats(nextStats);
      setHandoffs(nextHandoffs.handoffs);
      setError(null);
    } catch (problem) {
      setError(problem.message);
    }
  }

  useEffect(() => { load(); }, []);

  async function onResolve(id) {
    await resolveHandoff(id);
    load();
  }

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Handoff Queue</h1>
          <p className="subtitle">Sunrise Clinic, Dehradun — conversations the agent escalated</p>
        </div>
        <span className="pill pill-info">{handoffs.length} OPEN</span>
      </header>

      {error && <p className="error">Could not reach the backend: {error}</p>}

      <section className="counters">
        <Counter label="Conversations" value={stats?.conversations ?? "—"} note="today" />
        <Counter label="Completed by agent" value={stats?.completed ?? "—"}
                 note={stats ? `${stats.completed_pct}%` : ""} />
        <Counter label="Escalated" value={stats?.escalated ?? "—"}
                 note={stats ? `${stats.open} still open` : ""} noteTone="info" />
        <Counter label="Urgent" value={stats?.urgent ?? "—"}
                 note="clinical, unresolved" noteTone="danger" />
      </section>

      <section className="card">
        <h2 className="card-title">Open handoffs</h2>
        <table className="table">
          <thead>
            <tr>
              <th>Conversation</th>
              <th>Caller said</th>
              <th>Reason</th>
              <th>Time</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {handoffs.length === 0 && (
              <tr><td colSpan={5} className="empty">
                No open handoffs. Run a conversation against POST /agent/run to populate this.
              </td></tr>
            )}
            {handoffs.map((row) => (
              <tr key={row.conversation_id}>
                <td>
                  <button className="link" onClick={() => navigate(`/conversations/${row.conversation_id}`)}>
                    <code>{row.conversation_id}</code>
                  </button>
                </td>
                <td className="said">{row.caller_said ? `"${row.caller_said}"` : "—"}</td>
                <td>
                  <span className={`pill pill-${REASON_TONE[row.reason] || "warn"}`}>
                    {REASON_LABEL[row.reason] || row.reason}
                  </span>
                </td>
                <td className="muted">{clockOf(row.at)}</td>
                <td className="right">
                  {/* The clinical row is the one a human must pick up first, so
                      it carries the filled button, as in the mockup. */}
                  <button
                    className={row.reason === "clinical_urgent" ? "btn btn-primary" : "btn"}
                    onClick={() => onResolve(row.conversation_id)}
                  >
                    Resolve
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}

function Counter({ label, value, note, noteTone }) {
  return (
    <div className="counter">
      <p className="counter-label">{label}</p>
      <p className="counter-value">{value}</p>
      <p className={"counter-note" + (noteTone ? ` note-${noteTone}` : "")}>{note}</p>
    </div>
  );
}
