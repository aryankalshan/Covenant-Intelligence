import { FormEvent, useEffect, useRef, useState } from "react";
import { Agreement, ApprovedObligation, AuditEvent, Candidate, covenantApi, DEV_IDENTITIES, ExtractionRun, getActiveDevUser, MonitoringPeriod, Page, PageSummary, Version } from "./api";

type View = "dashboard" | "agreements" | "register" | "review" | "monitoring" | "amendments" | "audit";
const MONITORING_STATUSES = ["awaiting_setup", "upcoming", "due", "awaiting_evidence", "submitted", "reviewed", "not_assessed", "not_applicable"];
const CONTRIBUTOR_MONITORING_STATUSES = ["awaiting_setup", "upcoming", "due", "awaiting_evidence", "submitted"];

function extractionOriginLabel(origin?: Candidate["extraction_origin"]): string {
  if (origin === "synthetic_demo") return "Synthetic demonstration fixture · not AI generated";
  if (origin === "mock_test") return "Mock provider test result · not a live extraction";
  if (origin === "openrouter") return "AI generated via OpenRouter · not approved";
  return "AI provider result · not approved";
}

export default function App() {
  const [agreements, setAgreements] = useState<Agreement[]>([]);
  const [activeAgreementId, setActiveAgreementId] = useState("");
  const [versions, setVersions] = useState<Version[]>([]);
  const [activeVersionId, setActiveVersionId] = useState("");
  const [pages, setPages] = useState<PageSummary[]>([]);
  const [pagesLoading, setPagesLoading] = useState(false);
  const [pagesLoadedForVersion, setPagesLoadedForVersion] = useState("");
  const [activePage, setActivePage] = useState<Page | null>(null);
  const [agreementName, setAgreementName] = useState("");
  const [counterparty, setCounterparty] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [versionLabel, setVersionLabel] = useState("Original");
  const [sourceKind, setSourceKind] = useState("synthetic");
  const [busy, setBusy] = useState(false);
  const extractionActionInFlight = useRef(false);
  const [error, setError] = useState("");
  const [run, setRun] = useState<ExtractionRun | null>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [activeView, setActiveView] = useState<View>("agreements");
  const [reviewRows, setReviewRows] = useState<(Candidate & { agreement_id: string })[]>([]);
  const [selectedReview, setSelectedReview] = useState<any>(null);
  const [reviewDraft, setReviewDraft] = useState<Record<string, any> | null>(null);
  const [reviewComment, setReviewComment] = useState("");
  const [obligations, setObligations] = useState<ApprovedObligation[]>([]);
  const [registerSearch, setRegisterSearch] = useState("");
  const [registerCategory, setRegisterCategory] = useState("");
  const [selectedRegister, setSelectedRegister] = useState<ApprovedObligation | null>(null);
  const [revisionRows, setRevisionRows] = useState<any[]>([]);
  const [monitoringRows, setMonitoringRows] = useState<MonitoringPeriod[]>([]);
  const [monitorFilter, setMonitorFilter] = useState("");
  const [periodFilter, setPeriodFilter] = useState("");
  const [monitorAgreement, setMonitorAgreement] = useState("");
  const [monitorObligation, setMonitorObligation] = useState("");
  const [monitorLabel, setMonitorLabel] = useState("");
  const [monitorStart, setMonitorStart] = useState("");
  const [monitorEnd, setMonitorEnd] = useState("");
  const [monitorDue, setMonitorDue] = useState("");
  const [comparisonAgreement, setComparisonAgreement] = useState("");
  const [comparisonVersions, setComparisonVersions] = useState<Version[]>([]);
  const [comparisonBase, setComparisonBase] = useState("");
  const [comparisonAmendment, setComparisonAmendment] = useState("");
  const [comparisonRows, setComparisonRows] = useState<any[]>([]);
  const [comparisonComment, setComparisonComment] = useState("");
  const [removalReview, setRemovalReview] = useState<Record<string, any>>({});
  const [removalConfirmed, setRemovalConfirmed] = useState<Record<string, boolean>>({});
  const [auditRows, setAuditRows] = useState<AuditEvent[]>([]);
  const [auditFilter, setAuditFilter] = useState("");
  const [workflowMessage, setWorkflowMessage] = useState("");
  const activeDevUser = getActiveDevUser();
  const isReviewer = activeDevUser === "admin" || activeDevUser === "reviewer";

  async function refreshAgreements(preferredId?: string) {
    const rows = await covenantApi.listAgreements();
    setAgreements(rows);
    const selected = preferredId ?? activeAgreementId ?? rows[0]?.id ?? "";
    setActiveAgreementId(selected);
  }

  useEffect(() => { refreshAgreements().catch((e) => setError(e.message)); }, []);

  useEffect(() => {
    if (!activeAgreementId) { setVersions([]); return; }
    covenantApi.listVersions(activeAgreementId).then((rows) => {
      setVersions(rows);
      if (!rows.some((row) => row.id === activeVersionId)) setActiveVersionId(rows[0]?.id ?? "");
    }).catch((e) => setError(e.message));
  }, [activeAgreementId]);

  useEffect(() => {
    if (!activeVersionId) { setPages([]); setActivePage(null); setPagesLoading(false); setPagesLoadedForVersion(""); return; }
    setRun(null);
    setCandidates([]);
    setPagesLoading(true);
    covenantApi.listPages(activeVersionId).then((rows) => {
      setPages(rows);
      setActivePage(null);
      setPagesLoadedForVersion(activeVersionId);
    }).catch((e) => setError(e.message)).finally(() => setPagesLoading(false));
  }, [activeVersionId]);

  async function loadReviewQueue() {
    const rows = await covenantApi.reviewQueue(); setReviewRows(rows);
    if (selectedReview && !rows.some((item) => item.id === selectedReview.id)) setSelectedReview(null);
  }
  async function loadRegister() {
    const rows = await covenantApi.listObligations({ search: registerSearch || undefined, category: registerCategory || undefined, sort: "deadline" });
    setObligations(rows);
  }
  async function loadMonitoring() { setMonitoringRows(await covenantApi.listMonitoring({ agreement_id: monitorAgreement || undefined, status: monitorFilter || undefined, period_label: periodFilter || undefined })); }
  async function loadAudit() { setAuditRows(await covenantApi.listAudit({ action: auditFilter || undefined })); }
  useEffect(() => {
    const task = activeView === "dashboard" ? Promise.all([covenantApi.listAgreements().then(setAgreements), loadRegister(), loadReviewQueue()])
      : activeView === "review" ? loadReviewQueue() : activeView === "register" ? loadRegister()
      : activeView === "monitoring" ? Promise.all([loadMonitoring(), loadRegister()]) : activeView === "audit" ? loadAudit() : Promise.resolve();
    task.catch((e) => setError(e.message));
  }, [activeView]);

  async function chooseReview(id: string) {
    try { const detail = await covenantApi.reviewCandidate(id); setSelectedReview(detail); setReviewDraft(JSON.parse(JSON.stringify(detail.canonical_payload))); setReviewComment(""); }
    catch (e) { setError((e as Error).message); }
  }
  async function decideReview(action: "approved" | "corrected" | "rejected" | "needs_information") {
    if (!selectedReview) return;
    setBusy(true); setError(""); setWorkflowMessage("");
    try {
      const body: { action: string; comment?: string; corrected_obligation?: Record<string, any> } = { action, comment: reviewComment || undefined };
      if (action === "corrected") body.corrected_obligation = reviewDraft ?? undefined;
      await covenantApi.decideCandidate(selectedReview.id, body);
      setWorkflowMessage(`Candidate ${action.replace(/_/g, " ")}.`); setSelectedReview(null); await loadReviewQueue();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function openRegisterItem(item: ApprovedObligation) {
    setSelectedRegister(item);
    try { setRevisionRows(await covenantApi.getRevisions(item.id)); }
    catch (e) { setError((e as Error).message); }
  }
  async function createMonitoringPeriod(event: FormEvent) {
    event.preventDefault(); if (!monitorObligation) return;
    try {
      await covenantApi.createMonitoring(monitorObligation, { period_label: monitorLabel, period_start: monitorStart, period_end: monitorEnd, due_date: monitorDue || null });
      setWorkflowMessage("Monitoring period initialized."); await loadMonitoring();
    } catch (e) { setError((e as Error).message); }
  }
  async function setMonitoringStatus(periodId: string, status: string) {
    try { await covenantApi.updateMonitoring(periodId, { status, note: "Updated from obligation tracker." }); await loadMonitoring(); }
    catch (e) { setError((e as Error).message); }
  }
  async function loadComparisonVersions(agreementId: string) {
    setComparisonAgreement(agreementId); setComparisonRows([]);
    if (!agreementId) { setComparisonVersions([]); return; }
    try {
      const rows = await covenantApi.listVersions(agreementId);
      setComparisonVersions(rows);
      setComparisonBase(rows[rows.length - 1]?.id ?? "");
      setComparisonAmendment(rows[0]?.id ?? "");
      const previousComparisons = await covenantApi.listComparisons(agreementId);
      setComparisonRows(previousComparisons[0]?.items ?? []);
    }
    catch (e) { setError((e as Error).message); }
  }
  async function runComparison() {
    if (!comparisonAgreement || !comparisonBase || !comparisonAmendment || comparisonBase === comparisonAmendment) return;
    setBusy(true); setError(""); setWorkflowMessage("");
    try {
      let runState = await covenantApi.startExtraction(comparisonAmendment);
      for (let attempt = 0; attempt < 60 && ["queued", "running"].includes(runState.status); attempt++) {
        await new Promise((resolve) => window.setTimeout(resolve, 1000)); runState = await covenantApi.getExtractionRun(runState.id);
      }
      if (!["succeeded", "partial"].includes(runState.status)) throw new Error(runState.error_summary ?? "Amendment extraction did not complete.");
      const comparison = await covenantApi.createComparison(comparisonAgreement, { base_version_id: comparisonBase, amendment_version_id: comparisonAmendment, extraction_run_id: runState.id });
      setComparisonRows(comparison.items); setWorkflowMessage(`Comparison ready with ${comparison.items.length} proposed changes. ${runState.unprocessed_chunk_count ? `${runState.unprocessed_chunk_count} relevant chunks were not processed.` : ""}`);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function decideComparison(itemId: string, decision: string) {
    try { await covenantApi.decideComparison(itemId, decision, comparisonComment || undefined, removalConfirmed[itemId] ?? false); setComparisonRows((rows) => rows.map((item) => item.id === itemId ? { ...item, status: decision } : item)); setComparisonComment(""); }
    catch (e) { setError((e as Error).message); }
  }
  async function openRemovalReview(itemId: string) {
    try {
      const review = await covenantApi.removalReview(itemId);
      const pdfUrl = await covenantApi.openOriginalPdf(review.amendment_version.id);
      setRemovalReview((current) => ({ ...current, [itemId]: { ...review, pdfUrl } }));
    } catch (e) { setError((e as Error).message); }
  }

  const navigation: [View, string][] = [["dashboard", "Dashboard"], ["agreements", "Agreements"], ["register", "Covenant Register"], ["review", "Review Queue"], ["monitoring", "Obligation Tracker"], ["amendments", "Amendment Comparison"], ["audit", "Audit History"]];

  async function onCreateAgreement(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const agreement = await covenantApi.createAgreement({ name: agreementName, counterparty });
      setAgreementName(""); setCounterparty(""); await refreshAgreements(agreement.id);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function onUpload(event: FormEvent) {
    event.preventDefault();
    if (!activeAgreementId || !file) return;
    setBusy(true); setError("");
    try {
      const uploaded = await covenantApi.uploadVersion(activeAgreementId, file, versionLabel, sourceKind);
      await covenantApi.processVersion(uploaded.id);
      const updated = await covenantApi.listVersions(activeAgreementId);
      setVersions(updated); setActiveVersionId(uploaded.id); setFile(null);
      const input = document.getElementById("pdf-file") as HTMLInputElement | null;
      if (input) input.value = "";
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function openPage(number: number) {
    if (!activeVersionId) return;
    setError("");
    try { setActivePage(await covenantApi.getPage(activeVersionId, number)); }
    catch (e) { setError((e as Error).message); }
  }

  async function onExtract() {
    if (!activeVersionId || extractionActionInFlight.current) return;
    extractionActionInFlight.current = true;
    setBusy(true); setError(""); setCandidates([]);
    try {
      let current = run?.agreement_version_id === activeVersionId && ["queued", "running"].includes(run.status)
        ? run
        : await covenantApi.startExtraction(activeVersionId);
      setRun(current);
      while (["queued", "running"].includes(current.status)) {
        await new Promise((resolve) => window.setTimeout(resolve, 750));
        current = await covenantApi.getExtractionRun(current.id);
        setRun(current);
      }
      setCandidates(await covenantApi.listCandidates(current.id));
    } catch (e) { setError((e as Error).message); }
    finally { extractionActionInFlight.current = false; setBusy(false); }
  }

  const selectedVersion = versions.find((version) => version.id === activeVersionId);

  return (
    <div className="min-h-screen bg-[#f6f7f9] text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-indigo-700 text-sm font-bold text-white">CI</div>
            <div><p className="text-sm font-semibold tracking-wide">COVENANT INTELLIGENCE</p><p className="text-xs text-slate-500">Agreement workspace</p></div>
          </div>
          <label className="flex items-center gap-2 text-xs text-slate-500">Development identity
            <select aria-label="Development identity" className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-slate-700" value={activeDevUser} onChange={(e) => { localStorage.setItem("devUser", e.target.value); window.location.reload(); }}>
              {Object.entries(DEV_IDENTITIES).map(([identity, label]) => <option key={identity} value={identity}>{label}</option>)}
            </select>
          </label>
        </div>
        <nav aria-label="Main navigation" className="mx-auto flex max-w-7xl gap-1 overflow-x-auto px-6 pb-3">{navigation.map(([view, label]) => <button key={view} onClick={() => { setActiveView(view); setError(""); setWorkflowMessage(""); }} className={`whitespace-nowrap rounded-lg px-3 py-2 text-xs font-medium ${activeView === view ? "bg-indigo-50 text-indigo-800" : "text-slate-500 hover:bg-slate-50 hover:text-slate-800"}`}>{label}</button>)}</nav>
      </header>
      <main className="mx-auto max-w-7xl px-6 py-8">
        <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
          <div><p className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-indigo-700">Covenant intelligence</p><h1 className="text-3xl font-semibold tracking-tight">{navigation.find(([view]) => view === activeView)?.[1]}</h1><p className="mt-2 max-w-2xl text-sm text-slate-500">Evidence-backed contractual obligations for finance and compliance teams.</p></div>
          <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-900"><strong>Development mode</strong><br />Use public or synthetic documents only.</div>
        </div>
        {error && <div role="alert" className="mb-5 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">{error}</div>}
        {workflowMessage && <div role="status" className="mb-5 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{workflowMessage}</div>}

        {activeView === "agreements" && <div className="grid gap-6 lg:grid-cols-[330px_1fr]">
          <aside className="space-y-5">
            <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <h2 className="mb-4 text-sm font-semibold">Create agreement</h2>
              <form className="space-y-3" onSubmit={onCreateAgreement}>
                <label className="block text-xs font-medium text-slate-600">Agreement name<input required value={agreementName} onChange={(e) => setAgreementName(e.target.value)} placeholder="e.g. Revolving Credit Facility" className="mt-1.5 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100" /></label>
                <label className="block text-xs font-medium text-slate-600">Counterparty<input value={counterparty} onChange={(e) => setCounterparty(e.target.value)} placeholder="Optional" className="mt-1.5 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100" /></label>
                <button disabled={busy || (activeDevUser !== "admin" && activeDevUser !== "contributor")} className="w-full rounded-lg bg-indigo-700 px-3 py-2.5 text-sm font-semibold text-white hover:bg-indigo-800 disabled:opacity-50">Create agreement</button>
              </form>
            </section>

            <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <h2 className="mb-4 text-sm font-semibold">Upload a document</h2>
              <form className="space-y-3" onSubmit={onUpload}>
                <label className="block text-xs font-medium text-slate-600">Agreement<select aria-label="Agreement" value={activeAgreementId} onChange={(e) => setActiveAgreementId(e.target.value)} className="mt-1.5 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm"><option value="">Select an agreement</option>{agreements.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</select></label>
                <label className="block text-xs font-medium text-slate-600">Version label<input value={versionLabel} onChange={(e) => setVersionLabel(e.target.value)} className="mt-1.5 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm" /></label>
                <label className="block text-xs font-medium text-slate-600">Source<select value={sourceKind} onChange={(e) => setSourceKind(e.target.value)} className="mt-1.5 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm"><option value="synthetic">Synthetic</option><option value="public">Public</option></select></label>
                <label className="block text-xs font-medium text-slate-600">PDF file<input id="pdf-file" type="file" accept="application/pdf,.pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="mt-1.5 block w-full text-xs file:mr-3 file:rounded-lg file:border-0 file:bg-slate-100 file:px-3 file:py-2 file:text-xs file:font-semibold file:text-slate-700" /></label>
                <button disabled={busy || !activeAgreementId || !file || (activeDevUser !== "admin" && activeDevUser !== "contributor")} className="w-full rounded-lg bg-slate-900 px-3 py-2.5 text-sm font-semibold text-white hover:bg-slate-700 disabled:opacity-40">{busy ? "Processing PDF…" : "Upload and extract text"}</button>
              </form>
            </section>
          </aside>

          <section className="min-h-[640px] rounded-2xl border border-slate-200 bg-white shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-5 py-4">
              <div><h2 className="text-sm font-semibold">Document text</h2><p className="mt-1 text-xs text-slate-500">Page-level text extracted with PyMuPDF</p></div>
              <div className="flex items-center gap-2">
                <select aria-label="Document version" value={activeVersionId} onChange={(e) => setActiveVersionId(e.target.value)} className="max-w-56 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs">
                  <option value="">Select document version</option>{versions.map((v) => <option key={v.id} value={v.id}>{v.version_label} · {v.original_filename}</option>)}
                </select>
                {selectedVersion && <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-[11px] font-medium text-emerald-700">{selectedVersion.status}</span>}
              </div>
            </div>
            {!activeVersionId ? <div className="grid min-h-[560px] place-items-center p-8 text-center"><div><div className="mx-auto mb-4 grid h-12 w-12 place-items-center rounded-2xl bg-indigo-50 text-indigo-700">▤</div><h3 className="text-sm font-semibold">No document selected</h3><p className="mt-1 text-xs text-slate-500">Create an agreement and upload a PDF to see its extracted text.</p></div></div> : (
              <div className="grid min-h-[560px] md:grid-cols-[180px_1fr]">
                <nav aria-label="Document pages" className="border-b border-slate-200 p-3 md:border-b-0 md:border-r">
                  <p className="px-2 pb-2 text-[10px] font-semibold uppercase tracking-wider text-slate-400">Pages · {pages.length}</p>
                  <div className="space-y-1">{pages.map((p) => <button key={p.page_number} onClick={() => openPage(p.page_number)} className={`flex w-full items-center justify-between rounded-lg px-2.5 py-2 text-left text-xs ${activePage?.page_number === p.page_number ? "bg-indigo-50 font-semibold text-indigo-800" : "text-slate-600 hover:bg-slate-50"}`}><span>Page {p.page_number}</span><span className={`h-1.5 w-1.5 rounded-full ${p.has_text ? "bg-emerald-500" : "bg-amber-400"}`} aria-label={p.has_text ? "Text found" : "No text found"} /></button>)}</div>
                </nav>
                <article className="p-5 md:p-7">
                  {activePage ? <>
                    <div className="mb-5 flex flex-wrap items-center justify-between gap-2"><h3 className="text-base font-semibold">Page {activePage.page_number}</h3><span className="font-mono text-[10px] text-slate-400">SHA-256 {activePage.text_sha256.slice(0, 16)}…</span></div>
                    {activePage.warnings.length > 0 && <div className="mb-4 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">{activePage.warnings.join(" ")}</div>}
                    <pre className="min-h-80 whitespace-pre-wrap break-words rounded-xl bg-slate-50 p-5 font-mono text-xs leading-6 text-slate-700">{activePage.text || "No selectable text was found on this page."}</pre>
                  </> : <div className="grid min-h-[500px] place-items-center text-center"><div><p className="text-sm font-semibold">Choose a page</p><p className="mt-1 text-xs text-slate-500">Extracted source text and its hash will appear here.</p></div></div>}
                </article>
              </div>
            )}
            {selectedVersion?.status === "processed" && <div className="border-t border-slate-200 px-5 py-4">
              <button onClick={onExtract} disabled={busy || pagesLoading || pagesLoadedForVersion !== activeVersionId} aria-busy={Boolean(run && ["queued", "running"].includes(run.status))} className="rounded-lg bg-indigo-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">{pagesLoading || pagesLoadedForVersion !== activeVersionId ? "Loading pages…" : run && ["queued", "running"].includes(run.status) ? busy ? run.chunk_count > 0 ? `Extracting ${run.processed_chunk_count}/${run.chunk_count} chunks…` : "Extraction queued…" : "Resume status check" : "Extract covenants"}</button>
              {run && <div role="status" className="mt-2 text-xs text-slate-600"><p>Run {run.status} · {run.candidate_count} draft candidates{run.provider ? ` · ${run.provider}${run.model ? ` / ${run.model}` : ""}` : ""}</p>{run.error_summary && <p role="alert" className="mt-1 rounded bg-rose-50 p-2 text-rose-800">{run.error_summary}</p>}{(run.unprocessed_chunk_count > 0 || run.screened_out_chunk_count > 0) && <p className="mt-1 text-amber-800">Retrieval is not exhaustive: {run.unprocessed_chunk_count} relevant chunks were not processed and {run.screened_out_chunk_count} chunks were screened out.</p>}</div>}
              {run?.validation_findings.map((finding, index) => <p key={index} className="mt-1 text-xs text-amber-800">{finding.message ?? finding.code}</p>)}
              {candidates.length > 0 && <div className="mt-5 space-y-4">
                <h3 className="text-sm font-semibold">Draft candidates awaiting human review <span className="text-slate-500">({candidates.length})</span></h3>
                {candidates.some((item) => item.extraction_origin === "synthetic_demo") && <p className="rounded-lg bg-sky-50 px-3 py-2 text-xs text-sky-900">Synthetic demonstration fixtures · not generated by an AI provider.</p>}
                {candidates.some((item) => item.extraction_origin === "mock_test") && <p className="rounded-lg bg-slate-100 px-3 py-2 text-xs text-slate-700">Mock provider test results · not generated by a live AI provider.</p>}
                {(["financial_covenant", "reporting_obligation", "affirmative_covenant", "negative_covenant"] as const).map((category) => {
                  const group = candidates.filter((item) => item.canonical_payload.obligation_category === category);
                  const label = category.replace(/_/g, " ");
                  return group.length ? <section key={category} aria-label={label}><h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-indigo-800">{label} · {group.length}</h4><div className="space-y-3">{group.map((item) => <article key={item.id} className="rounded-xl border border-slate-200 p-4"><div className="flex flex-wrap justify-between gap-2"><strong className="text-sm">{item.canonical_payload.obligation_description}</strong><span className="text-xs text-amber-700">Draft · {item.status}</span></div><p className="mt-1 text-[11px] text-slate-500">{extractionOriginLabel(item.extraction_origin)}</p><p className="mt-2 text-xs text-slate-600">Threshold: {item.canonical_payload.threshold_value ?? "Not specified"} {item.canonical_payload.threshold_unit ?? ""} {item.canonical_payload.comparison_operator ?? ""} · Deadline: {item.canonical_payload.reporting_deadline ?? item.canonical_payload.deadline_calculation_rule ?? "Not specified"}</p>{item.canonical_payload.referenced_definitions?.map((definition: any, index: number) => <p key={index} className="mt-2 text-xs text-slate-600">Definition · {definition.term}: {definition.definition_text ?? "Unresolved"} {definition.source_page ? `(page ${definition.source_page})` : ""}</p>)}{item.evidence.map((evidence) => <blockquote key={evidence.id} className="mt-3 border-l-2 border-indigo-300 pl-3 text-xs text-slate-700">“{evidence.quote}” <span className="font-semibold">· page {evidence.page_number}</span></blockquote>)}{item.validation_findings.length > 0 && <p className="mt-2 text-xs text-amber-800">Human review needed: {item.validation_findings.map((finding) => typeof finding === "string" ? finding : finding.code ?? finding.message ?? "validation warning").join(", ")}</p>}{item.canonical_payload.uncertainty_reasons?.map((reason: string, index: number) => <p key={index} className="mt-1 text-xs text-amber-800">Unresolved: {reason}</p>)}</article>)}</div></section> : null;
                })}
              </div>}
            </div>}
          </section>
        </div>}
        {activeView === "dashboard" && <section className="grid gap-4 md:grid-cols-3"><Metric title="Agreements" value={agreements.length} onClick={() => setActiveView("agreements")} /><Metric title="Approved obligations" value={obligations.length} onClick={() => { setActiveView("register"); loadRegister(); }} /><Metric title="Pending review" value={reviewRows.length} onClick={() => { setActiveView("review"); loadReviewQueue(); }} /><div className="col-span-full rounded-2xl border border-amber-200 bg-amber-50 p-5 text-sm text-amber-900">Draft extraction is not exhaustive and is not legal advice. Every proposed change and obligation requires human verification.</div></section>}

        {activeView === "review" && <section className="grid gap-5 xl:grid-cols-[300px_1fr]"><aside className="rounded-2xl border border-slate-200 bg-white p-4"><div className="mb-3 flex items-center justify-between"><h2 className="text-sm font-semibold">Unreviewed candidates</h2><span className="rounded-full bg-indigo-50 px-2 py-1 text-xs text-indigo-800">{reviewRows.length}</span></div>{reviewRows.map((item) => <button key={item.id} onClick={() => chooseReview(item.id)} className={`mb-2 w-full rounded-xl border p-3 text-left ${selectedReview?.id === item.id ? "border-indigo-400 bg-indigo-50" : "border-slate-100 hover:bg-slate-50"}`}><span className="block text-xs font-semibold">{item.canonical_payload.obligation_description}</span><span className="mt-1 block text-[11px] text-slate-500">{item.canonical_payload.obligation_category.replace(/_/g, " ")} · {item.status}{item.extraction_origin === "synthetic_demo" ? " · demo fixture" : ""}</span></button>)}</aside>
          {!selectedReview ? <div className="grid min-h-96 place-items-center rounded-2xl border border-slate-200 bg-white text-sm text-slate-500">Select a candidate to inspect its contract evidence.</div> : <div className="grid gap-4 2xl:grid-cols-2"><section className="rounded-2xl border border-slate-200 bg-white p-5"><h2 className="mb-1 text-sm font-semibold">Source agreement</h2><p className="mb-4 text-xs text-slate-500">{selectedReview.agreement.name} · {selectedReview.agreement.version_label}</p>{selectedReview.source_pages.map((source: any) => { const quotes = selectedReview.evidence.filter((item: any) => item.page_number === source.page_number).map((item: any) => item.quote); return <article key={source.page_number} className="mb-4"><h3 className="mb-2 text-xs font-semibold">Page {source.page_number}</h3><pre className="max-h-[520px] overflow-auto whitespace-pre-wrap rounded-xl bg-slate-50 p-4 text-xs leading-6 text-slate-700">{highlightQuotes(source.text, quotes)}</pre></article>; })}</section>
            <section className="rounded-2xl border border-slate-200 bg-white p-5"><div className="mb-4 flex items-start justify-between"><div><h2 className="text-sm font-semibold">Canonical obligation draft</h2><p className="mt-1 text-xs text-amber-700">{extractionOriginLabel(selectedReview.extraction_origin)}</p></div><span className="rounded-full bg-amber-50 px-2 py-1 text-xs text-amber-800">{selectedReview.validation_status}</span></div><ReviewEditor payload={reviewDraft ?? selectedReview.canonical_payload} onChange={setReviewDraft} />{selectedReview.validation_findings.map((finding: any, i: number) => <p key={i} className="mt-2 text-xs text-rose-700">Validation: {typeof finding === "string" ? finding : `${finding.code ?? finding.message ?? "validation warning"} ${finding.field ? `· ${finding.field}` : ""}`}</p>)}{(reviewDraft?.uncertainty_reasons ?? []).map((reason: string, i: number) => <p key={i} className="mt-2 text-xs text-amber-800">Unresolved: {reason}</p>)}<label className="mt-4 block text-xs font-medium text-slate-600">Reviewer explanation<textarea value={reviewComment} onChange={(e) => setReviewComment(e.target.value)} rows={2} className="mt-1 w-full rounded-lg border border-slate-200 p-2" placeholder="Required to resolve flagged uncertainty." /></label>{isReviewer && <div className="mt-4 flex flex-wrap gap-2"><button disabled={busy} onClick={() => decideReview("approved")} className="rounded-lg bg-emerald-700 px-3 py-2 text-xs font-semibold text-white">Approve</button><button disabled={busy} onClick={() => decideReview("corrected")} className="rounded-lg bg-indigo-700 px-3 py-2 text-xs font-semibold text-white">Correct & approve</button><button disabled={busy} onClick={() => decideReview("rejected")} className="rounded-lg bg-rose-700 px-3 py-2 text-xs font-semibold text-white">Reject</button><button disabled={busy} onClick={() => decideReview("needs_information")} className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-semibold">Needs information</button></div>}</section></div>}
        </section>}

        {activeView === "register" && <section className="space-y-4"><div className="flex flex-wrap gap-3 rounded-2xl border border-slate-200 bg-white p-4"><input aria-label="Search obligations" value={registerSearch} onChange={(e) => setRegisterSearch(e.target.value)} placeholder="Search obligation or agreement" className="min-w-60 flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm" /><select aria-label="Category filter" value={registerCategory} onChange={(e) => setRegisterCategory(e.target.value)} className="rounded-lg border border-slate-200 px-3 py-2 text-sm"><option value="">All categories</option><option value="financial_covenant">Financial covenant</option><option value="reporting_obligation">Reporting obligation</option><option value="affirmative_covenant">Affirmative covenant</option><option value="negative_covenant">Negative covenant</option></select><button onClick={() => loadRegister()} className="rounded-lg bg-slate-900 px-4 py-2 text-sm text-white">Search</button></div><div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white"><table className="w-full text-left text-xs"><thead className="bg-slate-50 text-slate-500"><tr>{["Agreement", "Obligation", "Category", "Threshold", "Frequency", "Deadline", "Revision", "Approved"].map((x) => <th key={x} className="px-4 py-3 font-semibold">{x}</th>)}</tr></thead><tbody>{obligations.map((item) => <tr key={item.id} className="cursor-pointer border-t hover:bg-indigo-50" onClick={() => openRegisterItem(item)}><td className="px-4 py-3">{item.agreement_name}</td><td className="px-4 py-3 font-medium">{item.canonical_payload.obligation_description}</td><td className="px-4 py-3">{item.canonical_payload.obligation_category.replace(/_/g, " ")}</td><td className="px-4 py-3">{item.canonical_payload.threshold_value ?? "—"} {item.canonical_payload.threshold_unit ?? ""}</td><td className="px-4 py-3">{item.canonical_payload.testing_frequency ?? "—"}</td><td className="px-4 py-3">{item.canonical_payload.reporting_deadline ?? item.canonical_payload.deadline_calculation_rule ?? "—"}</td><td className="px-4 py-3">v{item.revision_number}</td><td className="px-4 py-3">{new Date(item.approved_at).toLocaleDateString()}</td></tr>)}</tbody></table>{obligations.length === 0 && <p className="p-8 text-center text-sm text-slate-500">No approved obligations match these filters.</p>}</div>{selectedRegister && <div className="rounded-2xl border border-slate-200 bg-white p-5"><div className="flex justify-between"><h2 className="text-sm font-semibold">{selectedRegister.canonical_payload.obligation_description}</h2><button onClick={() => setSelectedRegister(null)} className="text-xs text-slate-500">Close</button></div><p className="mt-2 text-xs text-slate-600">Source wording: {selectedRegister.canonical_payload.source_wording}</p>{revisionRows.map((revision) => <div key={revision.id} className="mt-3 rounded-lg bg-slate-50 p-3 text-xs"><strong>Revision {revision.revision_number} · {revision.status}</strong><p>Approved {new Date(revision.approved_at).toLocaleString()}</p>{revision.evidence.map((e: any, i: number) => <blockquote key={i} className="mt-2 border-l-2 border-indigo-300 pl-2">“{e.quote}” · page {e.page_number} · {e.evidence_role}</blockquote>)}</div>)}</div>}</section>}

        {activeView === "monitoring" && <section className="space-y-5"><form onSubmit={createMonitoringPeriod} className="grid gap-3 rounded-2xl border border-slate-200 bg-white p-5 md:grid-cols-3"><h2 className="md:col-span-3 text-sm font-semibold">Initialize an approved obligation period</h2><select aria-label="Monitoring agreement" value={monitorAgreement} onChange={(e) => { setMonitorAgreement(e.target.value); setMonitorObligation(""); }} className="rounded-lg border p-2 text-sm"><option value="">All agreements</option>{agreements.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</select><select aria-label="Approved obligation" value={monitorObligation} onChange={(e) => setMonitorObligation(e.target.value)} className="rounded-lg border p-2 text-sm"><option value="">Select approved obligation</option>{obligations.filter((o) => !monitorAgreement || o.agreement_id === monitorAgreement).map((o) => <option key={o.id} value={o.id}>{o.canonical_payload.obligation_description}</option>)}</select><input aria-label="Period label" required value={monitorLabel} onChange={(e) => setMonitorLabel(e.target.value)} placeholder="FY2026 Q4" className="rounded-lg border p-2 text-sm" /><input aria-label="Period start" type="date" required value={monitorStart} onChange={(e) => setMonitorStart(e.target.value)} className="rounded-lg border p-2 text-sm" /><input aria-label="Period end" type="date" required value={monitorEnd} onChange={(e) => setMonitorEnd(e.target.value)} className="rounded-lg border p-2 text-sm" /><input aria-label="Contractual due date" type="date" value={monitorDue} onChange={(e) => setMonitorDue(e.target.value)} className="rounded-lg border p-2 text-sm" /><button disabled={!monitorObligation || activeDevUser === "read_only"} className="rounded-lg bg-indigo-700 px-4 py-2 text-sm font-semibold text-white">Create monitoring period</button><p className="md:col-span-2 self-center text-xs text-slate-500">Unclear contractual rules stay in awaiting_setup until a reviewer configures a due date.</p></form><div className="flex flex-wrap gap-3"><select aria-label="Monitoring status filter" value={monitorFilter} onChange={(e) => { setMonitorFilter(e.target.value); setTimeout(() => loadMonitoring().catch((e) => setError(e.message)), 0); }} className="rounded-lg border p-2 text-sm"><option value="">All statuses</option><option value="overdue">Overdue (derived)</option>{MONITORING_STATUSES.map((s) => <option key={s}>{s}</option>)}</select><input aria-label="Reporting period filter" value={periodFilter} onChange={(e) => setPeriodFilter(e.target.value)} placeholder="Filter period label" className="rounded-lg border p-2 text-sm" /><button onClick={() => loadMonitoring()} className="rounded-lg border px-3 text-sm">Apply filters</button></div><div className="space-y-3">{monitoringRows.map((period) => <article key={period.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-4"><div><strong className="text-sm">{period.period_label}</strong><p className="mt-1 text-xs text-slate-500">{period.period_start} – {period.period_end} · due {period.due_date ?? "Needs configuration"}</p></div><div className="flex items-center gap-3"><span className={`text-xs font-semibold ${period.is_overdue ? "text-rose-700" : "text-slate-700"}`}>{period.is_overdue ? "Overdue · " : ""}{period.status}</span>{activeDevUser === "read_only" || (!isReviewer && !CONTRIBUTOR_MONITORING_STATUSES.includes(period.status)) ? <span className="text-xs text-slate-600">{period.status}{!isReviewer && activeDevUser !== "read_only" ? " (reviewer action)" : ""}</span> : <select aria-label={`Update ${period.period_label}`} value={period.status} onChange={(e) => setMonitoringStatus(period.id, e.target.value)} className="rounded border p-2 text-xs">{(isReviewer ? MONITORING_STATUSES : CONTRIBUTOR_MONITORING_STATUSES).map((s) => <option key={s}>{s}</option>)}</select>}</div></article>)}</div>{monitoringRows.length === 0 && <p className="rounded-2xl bg-white p-8 text-center text-sm text-slate-500">No monitoring periods yet.</p>}</section>}

        {activeView === "amendments" && <section className="space-y-5 rounded-2xl border border-slate-200 bg-white p-5"><h2 className="text-sm font-semibold">Compare approved obligations with an extracted amendment</h2><div className="grid gap-3 md:grid-cols-4"><select aria-label="Comparison agreement" value={comparisonAgreement} onChange={(e) => loadComparisonVersions(e.target.value)} className="rounded-lg border p-2 text-sm"><option value="">Select agreement</option>{agreements.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</select><select aria-label="Base agreement version" value={comparisonBase} onChange={(e) => setComparisonBase(e.target.value)} className="rounded-lg border p-2 text-sm">{comparisonVersions.map((v) => <option key={v.id} value={v.id}>{v.version_label}</option>)}</select><select aria-label="Amendment version" value={comparisonAmendment} onChange={(e) => setComparisonAmendment(e.target.value)} className="rounded-lg border p-2 text-sm">{comparisonVersions.map((v) => <option key={v.id} value={v.id}>{v.version_label}</option>)}</select><button disabled={busy || !comparisonBase || !comparisonAmendment || comparisonBase === comparisonAmendment || (activeDevUser !== "admin" && activeDevUser !== "contributor")} onClick={runComparison} className="rounded-lg bg-indigo-700 px-3 py-2 text-sm font-semibold text-white">{busy ? "Extracting and comparing…" : "Extract amendment & compare"}</button></div><p className="text-xs text-slate-500">Matching is deterministic and proposals require reviewer decisions. An accepted item creates a new revision; rejection and deferral leave the register unchanged.</p><label className="block text-xs text-slate-600">Reviewer comment (required to accept a removal)<textarea aria-label="Amendment reviewer comment" value={comparisonComment} onChange={(e) => setComparisonComment(e.target.value)} rows={2} className="mt-1 w-full rounded-lg border p-2" /></label><div className="space-y-3">{comparisonRows.map((item) => <article key={item.id} className="rounded-xl border border-slate-200 p-4"><div className="flex justify-between"><strong className="text-sm">{item.change_type.replace(/_/g, " ")}</strong><span className="text-xs">{item.status}</span></div><p className="my-2 text-xs text-slate-600">{item.rationale}</p><pre className="overflow-auto rounded bg-slate-50 p-3 text-xs">{JSON.stringify(item.proposed_changes, null, 2)}</pre>{item.full_document_review_required && <section className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4"><h3 className="text-xs font-semibold text-amber-950">Possible removal · full-document confirmation required</h3><p className="mt-1 text-xs text-amber-900">A missing extraction match does not establish contractual removal. Compare the original approved obligation and evidence with every page of the amendment before deciding.</p><p className="mt-2 text-xs font-semibold">Original approved obligation: {item.prior_obligation?.canonical_payload?.obligation_description}</p><p className="text-[11px] text-slate-600">{item.prior_obligation?.canonical_payload?.source_wording}</p>{item.prior_obligation?.evidence?.map((e: any, index: number) => <blockquote key={index} className="mt-2 border-l-2 border-indigo-300 pl-2 text-xs">“{e.quote}” · original page {e.page_number}</blockquote>)}<p className="mt-3 text-xs">Compared version: {item.amendment_version?.version_label} · {item.amendment_version?.page_count} pages · coverage {item.extraction_coverage?.complete ? "complete" : "incomplete"}</p>{!removalReview[item.id] ? <button onClick={() => openRemovalReview(item.id)} className="mt-3 rounded border border-amber-800 px-3 py-2 text-xs font-semibold">Load full amendment text and PDF</button> : <div className="mt-3"><a className="font-semibold text-indigo-800 underline" href={removalReview[item.id].pdfUrl} target="_blank" rel="noreferrer">Open original amendment PDF</a><div aria-label={`Full amendment text for ${item.id}`} className="mt-2 max-h-80 overflow-auto rounded border bg-white p-3">{removalReview[item.id].pages.map((page: any) => <article key={page.page_number} className="mb-4"><h4 className="text-xs font-semibold">Page {page.page_number}</h4><pre className="whitespace-pre-wrap text-xs">{page.text || "No text extracted from this page. Review the original PDF page."}</pre></article>)}</div><label className="mt-3 flex items-start gap-2 text-xs font-medium"><input type="checkbox" aria-label={`Confirm full-document review for ${item.id}`} checked={removalConfirmed[item.id] ?? false} onChange={(e) => setRemovalConfirmed((state) => ({ ...state, [item.id]: e.target.checked }))} />I opened and reviewed the complete original amendment PDF, including every page.</label></div>}</section>}{item.status === "pending" && isReviewer && <div className="mt-3 flex gap-2">{["accepted", "rejected", "deferred"].map((decision) => <button key={decision} disabled={decision === "accepted" && item.full_document_review_required && (!(removalConfirmed[item.id] ?? false) || !comparisonComment.trim())} onClick={() => decideComparison(item.id, decision)} className="rounded border px-3 py-1.5 text-xs disabled:opacity-40">{decision}</button>)}</div>}</article>)}</div></section>}

        {activeView === "audit" && <section className="space-y-4"><div className="flex gap-2"><input aria-label="Audit action filter" value={auditFilter} onChange={(e) => setAuditFilter(e.target.value)} placeholder="Filter by exact action" className="w-full rounded-lg border p-2 text-sm" /><button onClick={() => loadAudit()} className="rounded-lg bg-slate-900 px-4 text-sm text-white">Filter</button></div><div className="overflow-x-auto rounded-2xl border bg-white"><table className="w-full text-left text-xs"><thead className="bg-slate-50"><tr>{["Time", "Action", "Entity", "Actor", "Summary"].map((x) => <th key={x} className="p-3">{x}</th>)}</tr></thead><tbody>{auditRows.map((event) => <tr key={event.id} className="border-t"><td className="p-3">{new Date(event.occurred_at).toLocaleString()}</td><td className="p-3 font-semibold">{event.action}</td><td className="p-3">{event.entity_type} · {event.entity_id}</td><td className="p-3">{event.actor_user_id ?? "System"}</td><td className="p-3">{JSON.stringify(event.summary)}</td></tr>)}</tbody></table>{auditRows.length === 0 && <p className="p-8 text-center text-slate-500">No audit events.</p>}</div></section>}
        <footer className="mt-6 flex flex-wrap justify-between gap-2 text-[11px] text-slate-400"><span>Source documents are preserved; extracted text is for review.</span><span>AI results are drafts, require human review, and are not legal advice. OCR is not enabled.</span></footer>
      </main>
    </div>
  );
}

function Metric({ title, value, onClick }: { title: string; value: number; onClick: () => void }) {
  return <button onClick={onClick} className="rounded-2xl border border-slate-200 bg-white p-5 text-left shadow-sm"><span className="text-xs text-slate-500">{title}</span><strong className="mt-2 block text-3xl">{value}</strong></button>;
}

function ReviewEditor({ payload, onChange }: { payload: Record<string, any>; onChange: (value: Record<string, any>) => void }) {
  const set = (key: string, value: any) => onChange({ ...payload, [key]: value });
  const field = (label: string, key: string) => <label key={key} className="block text-xs font-medium text-slate-600">{label}<input value={payload[key] ?? ""} onChange={(e) => set(key, e.target.value || null)} className="mt-1 w-full rounded-lg border border-slate-200 p-2 text-sm" /></label>;
  const listField = (label: string, key: string, nullable = true) => <label key={key} className="block text-xs font-medium text-slate-600">{label} (one per line)<textarea value={(payload[key] ?? []).join("\n")} onChange={(e) => set(key, e.target.value ? e.target.value.split("\n").filter(Boolean) : (nullable ? null : []))} rows={2} className="mt-1 w-full rounded-lg border border-slate-200 p-2 text-xs" /></label>;
  return <div className="grid gap-3 sm:grid-cols-2"><label className="block text-xs font-medium text-slate-600">Obligation category<select aria-label="Obligation category" value={payload.obligation_category} onChange={(e) => set("obligation_category", e.target.value)} className="mt-1 w-full rounded-lg border p-2 text-sm">{["financial_covenant", "reporting_obligation", "affirmative_covenant", "negative_covenant"].map((category) => <option key={category}>{category}</option>)}</select></label>{field("Obligation description", "obligation_description")}{field("Source wording", "source_wording")}{field("Threshold value", "threshold_value")}<label className="block text-xs font-medium text-slate-600">Comparison operator<select aria-label="Comparison operator" value={payload.comparison_operator ?? ""} onChange={(e) => set("comparison_operator", e.target.value || null)} className="mt-1 w-full rounded-lg border p-2 text-sm"><option value="">Unavailable</option>{[">", ">=", "<", "<=", "=", "!="].map((operator) => <option key={operator}>{operator}</option>)}</select></label>{field("Threshold unit", "threshold_unit")}{field("Measurement basis", "measurement_basis")}{field("Testing frequency", "testing_frequency")}{field("Testing period", "testing_period")}{field("Reporting deadline", "reporting_deadline")}{field("Deadline calculation rule", "deadline_calculation_rule")}{listField("Conditions", "conditions")}{listField("Exceptions", "exceptions")}<label className="block text-xs font-medium text-slate-600">Referenced definitions (canonical JSON)<textarea value={JSON.stringify(payload.referenced_definitions)} onChange={(e) => { try { set("referenced_definitions", JSON.parse(e.target.value)); } catch { /* keep the last valid complete replacement */ } }} rows={3} className="mt-1 w-full rounded-lg border p-2 font-mono text-[10px]" /></label><label className="block text-xs font-medium text-slate-600">Cross-references (canonical JSON)<textarea value={JSON.stringify(payload.cross_references)} onChange={(e) => { try { set("cross_references", JSON.parse(e.target.value)); } catch { /* keep the last valid complete replacement */ } }} rows={3} className="mt-1 w-full rounded-lg border p-2 font-mono text-[10px]" /></label><label className="block text-xs font-medium text-slate-600 sm:col-span-2">Supporting evidence (canonical JSON)<textarea value={JSON.stringify(payload.supporting_evidence)} onChange={(e) => { try { set("supporting_evidence", JSON.parse(e.target.value)); } catch { /* keep the last valid complete replacement */ } }} rows={4} className="mt-1 w-full rounded-lg border p-2 font-mono text-[10px]" /></label>{listField("Uncertainty reasons", "uncertainty_reasons", false)}</div>;
}

function highlightQuotes(text: string, quotes: string[]) {
  let chunks: (string | { match: string })[] = [text];
  for (const quote of quotes.filter(Boolean)) {
    const escaped = quote.trim().split(/\s+/).map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("\\s+");
    if (!escaped) continue;
    const pattern = new RegExp(`(${escaped})`, "giu");
    chunks = chunks.flatMap((chunk) => typeof chunk === "string" ? chunk.split(pattern).map((part) => new RegExp(`^${escaped}$`, "iu").test(part) ? { match: part } : part) : [chunk]);
  }
  return chunks.map((part, index) => typeof part === "string" ? part : <mark key={index} className="rounded bg-yellow-200 px-0.5">{part.match}</mark>);
}
