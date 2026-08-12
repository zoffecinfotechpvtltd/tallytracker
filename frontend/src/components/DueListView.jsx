import { useEffect, useState } from "react";
import { api } from "../api.js";
import { fmtMoney, dueTone, dueLabel } from "../format.js";

const COPY = {
  payable: {
    title: "Payable",
    subtitle: "Vendors you owe — soonest due first",
    entityLabel: "Vendor",
  },
  receivable: {
    title: "Receivable",
    subtitle: "Customers who owe you — soonest due first",
    entityLabel: "Customer",
  },
};

export default function DueListView({ direction, tick, onOpenEntity }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const copy = COPY[direction];

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .billsDue(direction)
      .then((envelope) => {
        if (cancelled) return;
        setRows(envelope.data);
        setLoading(false);
      })
      .catch(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [direction, tick]);

  const totalAmount = rows.reduce((sum, r) => sum + (r.amount_outstanding || 0), 0);
  const overdueCount = rows.filter((r) => r.days_until_due !== null && r.days_until_due < 0).length;

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <h2>{copy.title}</h2>
          <p className="panel-sub">{copy.subtitle}</p>
        </div>
        <div className="panel-controls">
          <span className="pager-info">
            {rows.length} bills · {fmtMoney(totalAmount)} total
            {overdueCount > 0 ? ` · ${overdueCount} overdue` : ""}
          </span>
        </div>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{copy.entityLabel}</th>
              <th>Bill Ref</th>
              <th>Bill Date</th>
              <th>Status</th>
              <th className="num">Amount</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr className="empty-row">
                <td colSpan={5}>{loading ? "Loading…" : `No open ${direction} bills.`}</td>
              </tr>
            ) : (
              rows.map((r) => (
                <tr
                  key={`${r.entity_id}-${r.bill_ref}`}
                  className={"clickable" + (r.days_until_due !== null && r.days_until_due < 0 ? " row-overdue" : "")}
                  onClick={() => onOpenEntity(r.entity_id)}
                >
                  <td className="truncate" title={r.entity_name}>
                    {r.entity_name}
                  </td>
                  <td>{r.bill_ref || "—"}</td>
                  <td>{r.bill_date || "—"}</td>
                  <td>
                    <span className={"due-badge " + dueTone(r.days_until_due)}>{dueLabel(r.days_until_due)}</span>
                  </td>
                  <td className="num">{fmtMoney(r.amount_outstanding)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
