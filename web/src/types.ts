export interface Parameter { name: string; value: string; controllable: boolean }
export interface Symptom {
  category: "low_value" | "unstable" | "abnormal" | "none";
  description: string;
}
export const symptomCategoryLabels: Record<Symptom["category"], string> = {
  none: "문제 없음",
  low_value: "값이 낮음",
  unstable: "불안정·재현성",
  abnormal: "비정상 거동",
};
export interface SuspectedCause {
  cause: string;
  status: "unconfirmed" | "confirmed" | "rejected";
}
export interface Resolution { resolved: boolean; actual_cause: string | null; note: string }

export interface ParsedLog {
  title?: string;   // AI가 지은 짧은 제목 — 구버전 응답엔 없다
  experiment_type: string;
  objective: string;
  equipment: string[];
  materials: string[];
  parameters: Parameter[];
  results: string;
  symptom: Symptom;
  suspected_causes: SuspectedCause[];
  actions_taken: string[];
  summary: string;
  unrecorded_required_parameters: string[];
  notes?: string;   // 특이사항 — 백엔드(backend 브랜치) 병합 전 응답엔 없다
}

export interface Reference {
  type: "paper" | "link" | "record" | "pdf";  // pdf는 파일 첨부 스펙에서 사용 예정
  title: string;
  url: string;
  record_id: string;
}

export interface RecordMeta {
  id: string; date: string; title?: string; experiment_type: string; objective: string;
  equipment: string[]; materials: string[]; symptom: Symptom;
  resolution: Resolution; needs_review: boolean; followup_of: string | null;
  references?: Reference[];   // 백엔드 병합 전 응답엔 없다 — 읽는 쪽에서 ?? []
}
export interface RecordDetail {
  record: RecordMeta & {
    parameters: Parameter[]; results: string;
    suspected_causes: SuspectedCause[]; actions_taken: string[];
    notes?: string;   // 특이사항 — 백엔드 병합 전 응답엔 없다
  };
  body: string;
}
export type Evidence = "records" | "knowledge" | "web" | "none";
export interface EvidenceCard {
  id: string; kind: string; title: string; text: string;
  source: { record_id?: string; doc_id?: string; page?: number; url?: string; wiki?: string; term_id?: string };
}
export interface AskResult {
  answer: string;
  evidence: Evidence | "wiki";   // "wiki"는 이전 버전 세션(localStorage)에 남은 값 — 지금의 knowledge
  records: Pick<RecordMeta, "id" | "date" | "experiment_type" | "objective" | "symptom" | "resolution">[];
  wiki: string[];
  cards?: EvidenceCard[];        // 이하 필드는 그래프 리서치 에이전트 응답 — 이전 세션엔 없다
  terms?: { id: string; label: string }[];
  unknown?: string[];
  mode?: "seen" | "partial" | "unseen";
  rounds?: number;
  warnings?: string[];
  run_id?: string;
}
export type KgNodeKind =
  "experiment" | "equipment" | "material" | "technique" | "parameter" | "metric" | "cause" | "symptom" | "passage";
export interface KgNode {
  id: string; kind: KgNodeKind; label: string; label_ko: string;
  status: "verified" | "temp"; full: string; rec_ids: string[];
}
export interface KgLink { source: string; target: string; rel: string; kind: string }
export interface KgGraph { nodes: KgNode[]; links: KgLink[] }
export interface AppConfig {
  required_fields: string[]; required_parameters: string[];
  provider: string; vault: string; domains?: string[];
}
export interface DomainBundle { ontology: string; role: string }
export interface Domain {
  id: string; name: string; status: "active" | "showcase"; vocabulary?: string; description?: string;
  bundle: DomainBundle[];
}
export interface OntologyMeta {
  name: string; version?: string | null; license?: string | null; size?: string | null;
  usability?: string | null; adoption?: string | null; url?: string | null;
}
export interface DomainsInfo {
  domains: Domain[]; ontologies: Record<string, OntologyMeta>; selected: string[]; active: string;
  vocabulary: string; vocab: { terms: number; units: number; predicates: number; by_kind: Record<string, number> };
}

export interface AuthConfig {
  deploy: boolean; supabase_url: string | null; supabase_anon_key: string | null;
}
export interface Lab {
  id: string; name: string; llm_mode: "central" | "own";
  llm_provider: string | null; daily_llm_limit: number;
  invite_code?: string;   // 관리자에게만 내려온다
}
export interface LabMember { user_id: string; email: string; role: string }
export interface LabMe {
  lab: Lab | null; role: "admin" | "member" | null;
  usage_today: number; members?: LabMember[];
}

export interface ChatMsg { role: "user" | "ai"; text: string; chips?: string[] }
// 사용자 발화 직전의 대화 상태 — 되감기·포크의 복원 지점
export interface ConvoSnapshot {
  rawText: string; messages: ChatMsg[]; parsed: ParsedLog | null;
  gaps: string[]; gapIndex: number; answers: string[]; rounds: number;
}
export interface Session {
  id: string;
  kind: "log" | "ask" | "followup";
  title: string;
  pinned?: boolean;        // 사이드바 고정 — 목록 맨 위 정렬
  createdAt: number;
  saved: boolean;          // 레코드로 저장 완료 여부 (log/followup)
  baseId?: string;         // followup: 기준 레코드 id
  rawText: string;         // 누적 원문
  messages: ChatMsg[];
  parsed: ParsedLog | null;
  gaps: string[];
  gapIndex: number;        // 현재 질문 중인 gap
  answers: string[];       // 로컬 누적 답변 (재파싱 전)
  rounds: number;          // 재파싱 횟수 (최대 3)
  askResult?: AskResult;
  history?: ConvoSnapshot[]; // n번째 = n+1번째 사용자 발화 직전 상태 (초기 로그 제외)
}
