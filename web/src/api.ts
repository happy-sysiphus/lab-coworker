import type {
  AppConfig, AskResult, AuthConfig, AutoItem, DomainsInfo, KgGraph, KgStatus, Question, Lab, LabMe, ParsedLog, RecordDetail, RecordMeta, Reference,
} from "./types";
import type { TraceEvent, TraceRun } from "./flow";

// AuthProvider가 등록한다 — api.ts가 Supabase나 라우터를 직접 알지 않게
let getToken: () => Promise<string | null> = async () => null;
let onAuthError: (status: 401 | 403) => void = () => {};
export function registerAuth(t: typeof getToken, e: typeof onAuthError) {
  getToken = t; onAuthError = e;
}

async function http<T>(method: string, url: string, body?: unknown): Promise<T> {
  const token = await getToken();
  const res = await fetch(url, {
    method,
    headers: {
      ...(body ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    if (res.status === 401 || res.status === 403) onAuthError(res.status);
    const detail = await res.json().catch(() => ({}));
    throw new Error((detail as { detail?: string }).detail ?? `요청 실패 (${res.status})`);
  }
  return res.json() as Promise<T>;
}

// PDF 바이트를 그대로 올린다 (python-multipart 없이)
async function upload<T>(url: string, file: Blob): Promise<T> {
  const token = await getToken();
  const res = await fetch(url, {
    method: "PUT",
    headers: { "Content-Type": "application/pdf", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: file,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error((detail as { detail?: string }).detail ?? `업로드 실패 (${res.status})`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  parse: (text: string) =>
    http<{ parsed: ParsedLog; gaps: string[] }>("POST", "/api/parse", { text }),
  saveRecord: (text: string, parsed: ParsedLog, followupOf?: string,
    qa?: { question: string; answer: string }[]) =>
    http<{ id: string; path: string; run_id: string | null }>("POST", "/api/records",
      { text, parsed, followup_of: followupOf ?? null, qa: qa ?? [] }),
  updateRecord: (id: string, patch: Partial<Pick<RecordDetail["record"],
    "title" | "experiment_type" | "objective" | "equipment" | "materials" | "parameters" |
    "results" | "symptom" | "suspected_causes" | "actions_taken" | "notes">> & { body?: string }) =>
    http<RecordDetail>("PUT", `/api/records/${id}`, patch),
  saveRaw: (text: string) =>
    http<{ id: string; path: string }>("POST", "/api/records/raw", { text }),
  ask: (text: string, runId?: string) =>
    http<AskResult>("POST", "/api/ask", { text, run_id: runId ?? null }),
  kgGraph: () => http<KgGraph>("GET", "/api/kg/graph"),
  domains: () => http<DomainsInfo>("GET", "/api/ontology/domains"),
  setDomains: (domains: string[]) =>
    http<{ domains: string[]; notice: string | null; run_id: string }>("PUT", "/api/ontology/domains", { domains }),
  uploadManual: (file: File, pages?: string) =>
    upload<{ doc_id: string; created: boolean; run_id: string }>(
      `/api/manuals/${encodeURIComponent(file.name)}${pages ? `?pages=${encodeURIComponent(pages)}` : ""}`, file),
  kgStatus: () => http<KgStatus>("GET", "/api/kg/status"),
  kgBuild: (docId?: string) => http<{ run_id: string }>("POST", "/api/kg/build", { doc_id: docId ?? null }),
  questions: (tab: string) => http<{ questions: Question[]; auto?: AutoItem[] }>("GET", `/api/kg/questions?tab=${tab}`),
  question: (qid: string) => http<Question>("GET", `/api/kg/questions/${encodeURIComponent(qid)}`),
  answer: (qid: string, action: string, reasonCode?: string, edit?: Record<string, unknown>) =>
    http<{ status: string; verdict?: string; wrote?: string[]; run_id?: string }>(
      "POST", `/api/kg/questions/${encodeURIComponent(qid)}/answer`, { action, reason_code: reasonCode ?? null, edit: edit ?? null }),
  bulkAccept: (qids: string[]) => http<{ answered: unknown[] }>("POST", "/api/kg/questions/bulk-accept", { qids }),
  revoke: (itemId: string) => http<{ removed: boolean }>("POST", `/api/kg/items/${encodeURIComponent(itemId)}/revoke`),
  flowRuns: () => http<{ runs: TraceRun[] }>("GET", "/api/flow/runs"),
  flowRun: (id: string, after = 0) =>
    http<{ run: TraceRun; events: TraceEvent[] }>("GET", `/api/flow/runs/${encodeURIComponent(id)}?after=${after}`),
  listRecords: () => http<{ records: RecordMeta[] }>("GET", "/api/records"),
  getRecord: (id: string) => http<RecordDetail>("GET", `/api/records/${id}`),
  feedback: (recordId: string, resolved: boolean, cause?: string, note?: string) =>
    http<{ message: string }>("POST", "/api/feedback",
      { record_id: recordId, resolved, cause: cause ?? null, note: note ?? "" }),
  putReferences: (recordId: string, references: Reference[]) =>
    http<{ record: RecordMeta }>("PUT", `/api/records/${recordId}/references`, { references }),
  config: () => http<AppConfig>("GET", "/api/config"),
  authConfig: () => http<AuthConfig>("GET", "/api/auth-config"),
  labMe: () => http<LabMe>("GET", "/api/labs/me"),
  labCreate: (name: string) => http<{ lab: Lab; role: string }>("POST", "/api/labs", { name }),
  labJoin: (invite_code: string) =>
    http<{ lab: Lab; role: string }>("POST", "/api/labs/join", { invite_code }),
  // daily_llm_limit은 일부러 빠져 있다 — 일일 상한은 운영자만 DB에서 정한다
  labSettings: (patch: Partial<{
    name: string; llm_mode: string;
    llm_provider: string; llm_credential: string; rotate_invite: boolean;
  }>) => http<{ ok: boolean }>("PUT", "/api/labs/settings", patch),
};
