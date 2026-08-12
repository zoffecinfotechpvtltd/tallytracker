import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { fmtMoney } from "../format.js";

function confidenceTier(confidence) {
  if (confidence === null || confidence === undefined) return "low";
  if (confidence >= 85) return "high";
  if (confidence >= 40) return "medium";
  return "low";
}

function TransactionRow({ txn, onConfirm, onIgnore }) {
  const [overriding, setOverriding] = useState(false);
  const [query, setQuery] = useState("");
  const [candidates, setCandidates] = useState([]);
  const [pickedEntity, setPickedEntity] = useState(null);
  const [bills, setBills] = useState([]);
  const [pickedBillRef, setPickedBillRef] = useState("");

  useEffect(() => {
    if (!overriding || query.length < 2) {
      setCandidates([]);
      return;
    }
    let cancelled = false;
    const t = setTimeout(() => {
      api.entities({ search: query, pageSize: 8 }).then((env) => {
        if (!cancelled) setCandidates(env.data);
      });
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [query, overriding]);

  function pickEntity(entity) {
    setPickedEntity(entity);
    setCandidates([]);
    setQuery(entity.name);
    api.entityDetail(entity.id).then((env) => setBills(env.data.bills.filter((b) => b.status !== "closed")));
  }

  const alreadyDecided = txn.match_status !== "unmatched";
  const suggestion = txn.matched_entity_id
    ? { entityId: txn.matched_entity_id, entityName: txn.matched_entity_name, billRef: txn.matched_bill_ref }
    : null;

  return (
    <tr>
      <td>{txn.txn_date || "—"}</td>
      <td className="truncate" title={txn.narration}>
        {txn.narration}
      </td>
      <td className="num">{fmtMoney(txn.amount)}</td>
      <td>
        {alreadyDecided ? (
          <span className={"status-badge " + (txn.match_status === "confirmed" ? "open" : "closed")}>
            {txn.match_status}
          </span>
        ) : suggestion ? (
          <div className="confidence-bar">
            <div className="confidence-track">
              <div
                className={"confidence-fill " + confidenceTier(txn.match_confidence)}
                style={{ width: `${Math.min(100, txn.match_confidence)}%` }}
              />
            </div>
            {txn.match_confidence}%
          </div>
        ) : (
          <span style={{ color: "var(--ink-faint)" }}>no match</span>
        )}
      </td>
      <td className="truncate" title={suggestion?.entityName || ""}>
        {suggestion ? `${suggestion.entityName} · ${suggestion.billRef}` : "—"}
      </td>
      <td>
        {alreadyDecided ? null : overriding ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 220 }}>
            <input
              className="search-input"
              style={{ width: "100%" }}
              placeholder="Search entity…"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setPickedEntity(null);
              }}
            />
            {candidates.length > 0 && (
              <select size={Math.min(4, candidates.length)} onChange={(e) => pickEntity(candidates[e.target.selectedIndex])}>
                {candidates.map((c) => (
                  <option key={c.id}>{c.name}</option>
                ))}
              </select>
            )}
            {pickedEntity && bills.length > 0 && (
              <select value={pickedBillRef} onChange={(e) => setPickedBillRef(e.target.value)}>
                <option value="">Select bill…</option>
                {bills.map((b) => (
                  <option key={b.bill_ref} value={b.bill_ref}>
                    {b.bill_ref} ({fmtMoney(b.amount_outstanding)})
                  </option>
                ))}
              </select>
            )}
            <div className="recon-actions">
              <button
                type="button"
                className="confirm"
                disabled={!pickedEntity || !pickedBillRef}
                onClick={() => {
                  onConfirm(txn.id, pickedEntity.id, pickedBillRef);
                  setOverriding(false);
                }}
              >
                Confirm this
              </button>
              <button type="button" onClick={() => setOverriding(false)}>
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div className="recon-actions">
            {suggestion && (
              <button
                type="button"
                className="confirm"
                onClick={() => onConfirm(txn.id, suggestion.entityId, suggestion.billRef)}
              >
                Confirm
              </button>
            )}
            <button type="button" onClick={() => setOverriding(true)}>
              {suggestion ? "Change" : "Pick manually"}
            </button>
            <button type="button" className="ignore" onClick={() => onIgnore(txn.id)}>
              Ignore
            </button>
          </div>
        )}
      </td>
    </tr>
  );
}

export default function ReconciliationView() {
  const [statements, setStatements] = useState([]);
  const [activeStatementId, setActiveStatementId] = useState(null);
  const [transactions, setTransactions] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState(null);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef(null);

  function loadStatements() {
    api.reconciliationStatements().then((rows) => {
      setStatements(rows);
      if (rows.length > 0 && activeStatementId === null) setActiveStatementId(rows[0].id);
    });
  }

  useEffect(loadStatements, []);

  useEffect(() => {
    if (activeStatementId === null) return;
    api.reconciliationTransactions(activeStatementId).then(setTransactions);
  }, [activeStatementId]);

  async function handleFile(file) {
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const result = await api.uploadBankStatement(file);
      loadStatements();
      setActiveStatementId(result.statement_id);
      const rows = await api.reconciliationTransactions(result.statement_id);
      setTransactions(rows);
    } catch (e) {
      setError("Could not process that file — make sure it's a .xlsx bank statement export with Date/Narration/Debit/Credit columns.");
    } finally {
      setUploading(false);
    }
  }

  async function refreshTransactions() {
    if (activeStatementId === null) return;
    setTransactions(await api.reconciliationTransactions(activeStatementId));
  }

  async function handleConfirm(transactionId, entityId, billRef) {
    await api.confirmMatch(transactionId, entityId, billRef);
    refreshTransactions();
  }

  async function handleIgnore(transactionId) {
    await api.ignoreTransaction(transactionId);
    refreshTransactions();
  }

  const unresolvedCount = transactions.filter((t) => t.match_status === "unmatched").length;

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <h2>Bank Reconciliation</h2>
          <p className="panel-sub">Upload a bank statement, review suggested matches, confirm or correct each one.</p>
        </div>
        {statements.length > 0 && (
          <select
            className="search-input"
            value={activeStatementId ?? ""}
            onChange={(e) => setActiveStatementId(Number(e.target.value))}
          >
            {statements.map((s) => (
              <option key={s.id} value={s.id}>
                {s.filename} ({s.row_count} rows)
              </option>
            ))}
          </select>
        )}
      </div>

      <div
        className={"upload-zone" + (dragOver ? " dragover" : "")}
        onClick={() => fileInputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          handleFile(e.dataTransfer.files?.[0]);
        }}
      >
        <div className="upload-zone-label">{uploading ? "Processing…" : "Click or drop a .xlsx bank statement here"}</div>
        <div className="upload-zone-hint">Any standard export works — column names are auto-detected</div>
        <input
          ref={fileInputRef}
          type="file"
          accept=".xlsx"
          onChange={(e) => handleFile(e.target.files?.[0])}
        />
      </div>
      {error && (
        <p style={{ color: "var(--red)", padding: "0 26px 16px", fontSize: 13 }}>{error}</p>
      )}

      {activeStatementId !== null && (
        <>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Narration</th>
                  <th className="num">Amount</th>
                  <th>Confidence</th>
                  <th>Suggested Match</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {transactions.length === 0 ? (
                  <tr className="empty-row">
                    <td colSpan={6}>No transactions.</td>
                  </tr>
                ) : (
                  transactions.map((t) => (
                    <TransactionRow key={t.id} txn={t} onConfirm={handleConfirm} onIgnore={handleIgnore} />
                  ))
                )}
              </tbody>
            </table>
          </div>
          {transactions.length > 0 && (
            <p className="pager-info" style={{ padding: "12px 26px" }}>
              {unresolvedCount} of {transactions.length} still need review
            </p>
          )}
        </>
      )}
    </section>
  );
}
