export type Agreement = { id: string; name: string; counterparty: string | null; created_at: string };
export type Version = {
  id: string; agreement_id: string; version_label: string; source_kind: string;
  original_filename: string; sha256: string; page_count: number | null; status: string;
};
export type PageSummary = { page_number: number; has_text: boolean; text_sha256: string; warnings: string[] };
export type Page = PageSummary & { text: string };
export type ExtractionRun = { id: string; agreement_version_id: string; status: string; provider?: string | null; model?: string | null; chunk_count: number; unprocessed_chunk_count: number; screened_out_chunk_count: number; processed_chunk_count: number; candidate_count: number; validation_findings: { code?: string; message?: string }[]; error_code: string | null; error_summary: string | null };
export type Candidate = { id: string; extraction_run_id: string; extraction_origin?: "openrouter" | "provider" | "mock_test" | "synthetic_demo"; status: string; validation_status: string; validation_findings: ({ code?: string; field?: string; message?: string } | string)[]; canonical_payload: Record<string, any>; evidence: { id: string; page_number: number; quote: string; source_section: string | null }[] };
export type ApprovedObligation = { id: string; agreement_id: string; agreement_name: string; lifecycle_status: string; current_revision_id: string; revision_number: number; approved_at: string; canonical_payload: Record<string, any> };
export type MonitoringPeriod = { id: string; obligation_id: string; obligation_revision_id: string; period_label: string; period_start: string; period_end: string; due_date: string | null; deadline_rule: string | null; status: string; is_overdue: boolean; updates: { id: string; status: string; note: string | null; supporting_reference: string | null }[] };
export type ComparisonItem = { id: string; change_type: string; prior_obligation_revision_id: string | null; candidate_id: string | null; proposed_changes: Record<string, any>; rationale: string; status: string };
export type AuditEvent = { id: string; actor_user_id: string | null; action: string; entity_type: string; entity_id: string; occurred_at: string; summary: Record<string, any> };

export const DEV_IDENTITIES = {
  admin: "Demo Admin",
  reviewer: "Demo Reviewer",
  contributor: "Demo Contributor",
  read_only: "Demo Read Only",
} as const;
export type DevIdentity = keyof typeof DEV_IDENTITIES;
export const DEFAULT_DEV_USER: DevIdentity = "contributor";

export function getActiveDevUser(): DevIdentity {
  const stored = localStorage.getItem("devUser");
  return stored && Object.prototype.hasOwnProperty.call(DEV_IDENTITIES, stored) ? stored as DevIdentity : DEFAULT_DEV_USER;
}

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000/api/v1";

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("X-Dev-User", getActiveDevUser());
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try { message = (await response.json()).detail ?? message; } catch { /* use fallback */ }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export const covenantApi = {
  listAgreements: () => api<Agreement[]>("/agreements"),
  createAgreement: (body: { name: string; counterparty: string }) => api<Agreement>("/agreements", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  }),
  listVersions: (agreementId: string) => api<Version[]>(`/agreements/${agreementId}/versions`),
  uploadVersion: (agreementId: string, file: File, versionLabel: string, sourceKind: string) => {
    const body = new FormData();
    body.set("file", file); body.set("version_label", versionLabel); body.set("source_kind", sourceKind);
    return api<Version>(`/agreements/${agreementId}/versions`, { method: "POST", body });
  },
  processVersion: (versionId: string) => api<{ status: string; page_count: number }>(`/versions/${versionId}/process`, { method: "POST" }),
  listPages: (versionId: string) => api<PageSummary[]>(`/versions/${versionId}/pages`),
  getPage: (versionId: string, pageNumber: number) => api<Page>(`/versions/${versionId}/pages/${pageNumber}`),
  openOriginalPdf: async (versionId: string) => {
    const headers = new Headers({ "X-Dev-User": getActiveDevUser() });
    const response = await fetch(`${API_BASE}/versions/${versionId}/pdf`, { headers });
    if (!response.ok) throw new Error(`Original PDF request failed (${response.status})`);
    const blob = await response.blob();
    return URL.createObjectURL(blob);
  },
  startExtraction: (versionId: string) => api<ExtractionRun>(`/versions/${versionId}/extraction-runs`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) }),
  getExtractionRun: (runId: string) => api<ExtractionRun>(`/extraction-runs/${runId}`),
  listCandidates: (runId: string) => api<Candidate[]>(`/extraction-runs/${runId}/candidates`),
  reviewQueue: () => api<(Candidate & { agreement_id: string })[]>("/review/candidates"),
  reviewCandidate: (id: string) => api<any>(`/review/candidates/${id}`),
  decideCandidate: (id: string, body: { action: string; comment?: string; corrected_obligation?: Record<string, any> }) => api<any>(`/candidates/${id}/review-decisions`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  listObligations: (params: { category?: string; agreement_id?: string; search?: string; sort?: string } = {}) => {
    const query = new URLSearchParams(Object.entries(params).filter(([, value]) => value) as [string, string][]);
    return api<ApprovedObligation[]>(`/obligations${query.size ? `?${query}` : ""}`);
  },
  getObligation: (id: string) => api<any>(`/obligations/${id}`),
  getRevisions: (id: string) => api<any[]>(`/obligations/${id}/revisions`),
  listMonitoring: (params: { agreement_id?: string; status?: string; period_label?: string } = {}) => {
    const query = new URLSearchParams(Object.entries(params).filter(([, value]) => value) as [string, string][]);
    return api<MonitoringPeriod[]>(`/monitoring-periods${query.size ? `?${query}` : ""}`);
  },
  createMonitoring: (id: string, body: Record<string, unknown>) => api<MonitoringPeriod>(`/obligations/${id}/monitoring-periods`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  updateMonitoring: (id: string, body: Record<string, unknown>) => api<MonitoringPeriod>(`/monitoring-periods/${id}/updates`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  listComparisons: (agreementId: string) => api<any[]>(`/agreements/${agreementId}/amendment-comparisons`),
  createComparison: (agreementId: string, body: Record<string, unknown>) => api<any>(`/agreements/${agreementId}/amendment-comparisons`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  removalReview: (id: string) => api<any>(`/comparison-items/${id}/removal-review`),
  decideComparison: (id: string, decision: string, comment?: string, fullDocumentReviewConfirmed = false) => api<any>(`/comparison-items/${id}/decisions`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decision, comment, full_document_review_confirmed: fullDocumentReviewConfirmed }) }),
  listAudit: (params: { action?: string; entity_type?: string } = {}) => {
    const query = new URLSearchParams(Object.entries(params).filter(([, value]) => value) as [string, string][]);
    return api<AuditEvent[]>(`/audit-events${query.size ? `?${query}` : ""}`);
  },
};
