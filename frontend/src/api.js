const BASE = import.meta.env.VITE_API_BASE || "";

async function get(path) {
  const reply = await fetch(BASE + path);
  if (!reply.ok) throw new Error(`${reply.status} on ${path}`);
  return reply.json();
}

export const getStats = () => get("/ui/stats");
export const getHandoffs = () => get("/ui/handoffs");
export const getConversation = (id) => get(`/ui/conversations/${id}`);

export async function resolveHandoff(id) {
  const reply = await fetch(`${BASE}/ui/handoffs/${id}/resolve`, { method: "POST" });
  if (!reply.ok) throw new Error(`${reply.status} resolving ${id}`);
  return reply.json();
}

// Escalation reasons are the five strings in schema.md. The UI never invents a
// label for one it has not seen.
export const REASON_LABEL = {
  clinical_urgent: "CLINICAL",
  medical_advice: "MEDICAL ADVICE",
  not_authorised: "NOT AUTHORISED",
  ambiguous_patient: "AMBIGUOUS PATIENT",
  out_of_scope: "OUT OF SCOPE",
};

export const REASON_TONE = {
  clinical_urgent: "danger",
  medical_advice: "danger",
  not_authorised: "warn",
  ambiguous_patient: "warn",
  out_of_scope: "warn",
};

export function clockOf(iso) {
  if (!iso) return "";
  const at = new Date(iso);
  return Number.isNaN(at.getTime())
    ? ""
    : at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

export function stampOf(iso) {
  if (!iso) return "";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "";
  return at.toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" })
    + ", " + clockOf(iso);
}
