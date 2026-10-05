import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { getConversation, REASON_LABEL, stampOf } from "../api.js";

export default function ConversationDetail() {
  const { id } = useParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    getConversation(id).then(setData).catch((problem) => setError(problem.message));
  }, [id]);

  if (error) return <p className="error">Could not load {id}: {error}</p>;
  if (!data) return <p className="muted">Loading {id}…</p>;

  const escalated = data.terminal_state === "escalated";
  const badge = escalated
    ? `ESCALATED — ${REASON_LABEL[data.escalation_reason] || data.escalation_reason}`
    : data.terminal_state.toUpperCase();
  const nothingHappened = ["escalated", "refused", "abandoned"].includes(data.terminal_state);

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Conversation {data.conversation_id}</h1>
          <p className="subtitle">Sunrise Clinic, Dehradun — {stampOf(data.at)}</p>
        </div>
        <span className={"pill " + (escalated ? "pill-danger" : "pill-ok")}>{badge}</span>
      </header>

      <div className="split">
        <section className="card">
          <h2 className="card-title">Transcript and tool calls</h2>
          {/* Tool calls are rendered inline where they fired: they are the
              visual proof that nothing in the reply was invented. */}
          <Transcript turns={data.turns} calls={data.tool_calls} reply={data.reply} />
          {nothingHappened && !data.appointment_id && (
            <p className="banner">Booking flow abandoned. No appointment was created.</p>
          )}
        </section>

        <section className="card">
          <h2 className="card-title">Outcome</h2>
          <dl className="outcome">
            <Row k="terminal_state" v={data.terminal_state} />
            <Row k="escalation_reason" v={data.escalation_reason ?? "null"} />
            <Row k="patient_id" v={data.patient_id ?? "null"} />
            <Row k="appointment_id" v={data.appointment_id ?? "null"} />
            <Row k="tool_calls" v={data.tool_calls.length} />
            <Row k="turns" v={data.turns.length} />
            <Row k="tokens" v={(data.metrics.tokens ?? 0).toLocaleString()} />
            <Row k="latency" v={formatLatency(data.metrics.latency_ms)} />
            <Row k="model" v={data.metrics.model ?? "—"} />
          </dl>

          <h3 className="section-label">Determinism</h3>
          <p className="determinism">
            {data.stable
              ? `Same terminal state across ${data.runs} run${data.runs === 1 ? "" : "s"}.`
              : `Terminal state changed across ${data.runs} runs.`}
            <span className={"pill " + (data.stable ? "pill-ok" : "pill-danger")}>
              {data.stable ? "STABLE" : "UNSTABLE"}
            </span>
          </p>
          {!data.stable && (
            <ul className="fingerprints">
              {data.fingerprints.map((print) => <li key={print}><code>{print}</code></li>)}
            </ul>
          )}
        </section>
      </div>
    </>
  );
}

function Transcript({ turns, calls, reply }) {
  // Caller turns, then tool calls, then the agent's reply -- which is the real
  // order of events, not a layout convenience. The policy engine reads every
  // turn before it calls a mutating tool, so that a clinical red flag in the
  // final turn still arrives before a booking could commit. Interleaving the
  // calls between the turns would draw an order that did not happen, in the
  // one panel whose job is to prove nothing was invented.
  return (
    <div className="transcript">
      {turns.map((turn, index) => (
        <div className="row" key={`turn-${index}`}>
          <span className="who">Caller</span>
          <p className="bubble">{turn}</p>
        </div>
      ))}
      {calls.map((call, index) => (
        <div className="row" key={`call-${index}`}>
          <span className="who">Tool</span>
          <pre className="tool">
            <span className="tool-name">{call.name}</span>({formatArgs(call.arguments)})
          </pre>
        </div>
      ))}
      {reply && (
        <div className="row">
          <span className="who">Agent</span>
          <p className="bubble bubble-agent">{reply}</p>
        </div>
      )}
    </div>
  );
}

function formatLatency(ms) {
  if (!ms && ms !== 0) return "—";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

function formatArgs(args) {
  if (!args || typeof args !== "object") return "";
  return Object.entries(args)
    .map(([key, value]) => `${key}=${JSON.stringify(value)}`)
    .join(", ");
}

function Row({ k, v }) {
  return (
    <div className="outcome-row">
      <dt>{k}</dt>
      <dd><code>{String(v)}</code></dd>
    </div>
  );
}
