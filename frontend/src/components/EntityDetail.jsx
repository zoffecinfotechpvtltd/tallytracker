import { useEffect, useState } from "react";
import { Line } from "react-chartjs-2";
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Filler,
  Tooltip,
} from "chart.js";
import { api } from "../api.js";
import { fmtMoney, relativeTime } from "../format.js";
import { showToast } from "../toast.js";

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Filler, Tooltip);

const STATUS_OPTIONS = ["pending", "contacted", "resolved"];

export default function EntityDetail({ entityId, onClose }) {
  const [detail, setDetail] = useState(null);
  const [vouchers, setVouchers] = useState(null); // null = loading, [] = loaded empty
  const [vouchersOffline, setVouchersOffline] = useState(false);
  const [note, setNote] = useState("");
  const [status, setStatus] = useState("pending");

  useEffect(() => {
    let cancelled = false;
    setDetail(null);
    setVouchers(null);
    setVouchersOffline(false);
    setStatus("pending");

    api.entityDetail(entityId).then((env) => {
      if (!cancelled) setDetail(env.data);
    });

    api
      .entityVouchers(entityId)
      .then((env) => {
        if (cancelled) return;
        if (!env.tally_reachable) {
          setVouchersOffline(true);
          setVouchers([]);
        } else {
          setVouchers(env.data);
        }
      })
      .catch(() => !cancelled && setVouchers([]));

    return () => {
      cancelled = true;
    };
  }, [entityId]);

  async function submitFollowup(e) {
    e.preventDefault();
    if (!note.trim()) return;
    try {
      const created = await api.postFollowup(entityId, note.trim(), status);
      setDetail((d) => ({ ...d, followups: [created, ...d.followups] }));
      setNote("");
      showToast("Followup added");
    } catch (err) {
      showToast("Couldn't save that followup — try again", "error");
    }
  }

  useEffect(() => {
    function onKey(e) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!detail) {
    return (
      <div className="detail-overlay">
        <div className="detail-scrim" onClick={onClose}></div>
        <aside className="detail-panel" role="dialog" aria-modal="true" aria-label="Entity detail">
          <button className="detail-close" type="button" aria-label="Close" onClick={onClose}>
            ×
          </button>
          <p style={{ color: "var(--ink-faint)" }}>Loading…</p>
        </aside>
      </div>
    );
  }

  const { entity, bills, balance_history, followups } = detail;

  const chartData = {
    labels: balance_history.map((h) => new Date(h.taken_at).toLocaleDateString()),
    datasets: [
      {
        label: "Balance",
        data: balance_history.map((h) => h.balance),
        borderColor: "#a3352b",
        backgroundColor: "rgba(163,53,43,0.08)",
        tension: 0.15,
        pointRadius: 2,
        fill: true,
      },
    ],
  };

  return (
    <div className="detail-overlay">
      <div className="detail-scrim" onClick={onClose}></div>
      <aside className="detail-panel" role="dialog" aria-modal="true" aria-label="Entity detail">
        <button className="detail-close" type="button" aria-label="Close" onClick={onClose}>
          ×
        </button>
        <div className="detail-head">
          <div className="detail-name">{entity.name}</div>
          <div className="detail-balance">
            {fmtMoney(entity.current_balance)}{" "}
            <span className={"pill " + (entity.balance_type === "Cr" ? "cr" : "dr")}>{entity.balance_type || "-"}</span>
          </div>
        </div>

        <div className="detail-section">
          <h3>Bills</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Ref</th>
                  <th>Details</th>
                  <th>Date</th>
                  <th>Due</th>
                  <th className="num">Outstanding</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {bills.length === 0 ? (
                  <tr className="empty-row">
                    <td colSpan={6}>No bills.</td>
                  </tr>
                ) : (
                  bills.map((b) => (
                    <tr key={b.bill_ref} className={b.status === "overdue" ? "row-overdue" : ""}>
                      <td>{b.bill_ref}</td>
                      <td className="truncate" title={b.narration || ""}>
                        {b.narration || "—"}
                      </td>
                      <td>{b.bill_date || "—"}</td>
                      <td>{b.due_date || "—"}</td>
                      <td className="num">{fmtMoney(b.amount_outstanding)}</td>
                      <td>
                        <span className={"status-badge " + b.status}>{b.status}</span>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="detail-section">
          <h3>Transactions</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Type</th>
                  <th>No.</th>
                  <th className="num">Amount</th>
                  <th>Narration</th>
                </tr>
              </thead>
              <tbody>
                {vouchers === null ? (
                  <tr className="empty-row">
                    <td colSpan={5}>Loading…</td>
                  </tr>
                ) : vouchersOffline ? (
                  <tr className="empty-row">
                    <td colSpan={5}>Tally offline — can't load transactions right now.</td>
                  </tr>
                ) : vouchers.length === 0 ? (
                  <tr className="empty-row">
                    <td colSpan={5}>No transactions found.</td>
                  </tr>
                ) : (
                  vouchers.map((v, i) => (
                    <tr key={i}>
                      <td>{v.date || "—"}</td>
                      <td>{v.voucher_type}</td>
                      <td>{v.voucher_number}</td>
                      <td className="num">{fmtMoney(v.amount)}</td>
                      <td className="truncate" title={v.narration}>
                        {v.narration}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="detail-section">
          <h3>Balance History</h3>
          {balance_history.length > 0 ? (
            <Line data={chartData} options={{ responsive: true, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } }} height={120} />
          ) : (
            <p style={{ color: "var(--ink-faint)", fontSize: 13 }}>Not enough history yet.</p>
          )}
        </div>

        <div className="detail-section">
          <h3>Followups</h3>
          <ul className="followups-list">
            {followups.length === 0 ? (
              <li className="empty-row">No followups yet.</li>
            ) : (
              followups.map((f) => (
                <li key={f.id}>
                  <span className="fu-status">{f.status}</span>
                  {f.note}
                  <span className="fu-time">{relativeTime(f.created_at)}</span>
                </li>
              ))
            )}
          </ul>
          <form className="followup-form" onSubmit={submitFollowup}>
            <textarea
              placeholder="Called, promised payment by Friday…"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              required
            />
            <div className="followup-row">
              <div className="seg" role="tablist" aria-label="Followup status">
                {STATUS_OPTIONS.map((s) => (
                  <button
                    key={s}
                    type="button"
                    className={"seg-btn" + (status === s ? " active" : "")}
                    role="tab"
                    aria-selected={status === s}
                    onClick={() => setStatus(s)}
                  >
                    {s.charAt(0).toUpperCase() + s.slice(1)}
                  </button>
                ))}
              </div>
              <button type="submit">Add note</button>
            </div>
          </form>
        </div>
      </aside>
    </div>
  );
}
