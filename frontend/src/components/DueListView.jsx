import { useEffect, useState } from "react";
import { api } from "../api.js";
import { fmtMoney, dueTone, dueLabel } from "../format.js";
import { useSort } from "../hooks/useSort.js";
import { downloadCsv } from "../csv.js";
import { showToast } from "../toast.js";
import Pager from "./Pager.jsx";
import SortableHeader from "./SortableHeader.jsx";

const PAGE_SIZE = 50;

const COPY = {
  payable: {
    title: "Payable",
    subtitle: "Vendors you owe",
    entityLabel: "Vendor",
  },
  receivable: {
    title: "Receivable",
    subtitle: "Customers who owe you",
    entityLabel: "Customer",
  },
};

export default function DueListView({ direction, tick, onOpenEntity }) {
  const { sortColumn, sortDir, toggleSort } = useSort("due");
  const [page, setPage] = useState(1);
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [totalAmount, setTotalAmount] = useState(0);
  const [overdueCount, setOverdueCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const copy = COPY[direction];

  useEffect(() => setPage(1), [direction, sortColumn, sortDir]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .billsDue(direction, { sortBy: sortColumn, sortDir, page, pageSize: PAGE_SIZE })
      .then((envelope) => {
        if (cancelled) return;
        setRows(envelope.data);
        setTotal(envelope.total ?? envelope.data.length);
        setTotalAmount(envelope.total_amount ?? 0);
        setOverdueCount(envelope.overdue_count ?? 0);
        setLoading(false);
      })
      .catch(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [direction, sortColumn, sortDir, page, tick]);

  async function handleExport() {
    if (total === 0) return;
    const envelope = await api.billsDue(direction, { sortBy: sortColumn, sortDir, page: 1, pageSize: 100000 });
    downloadCsv(
      `${direction}-${new Date().toISOString().slice(0, 10)}.csv`,
      [copy.entityLabel, "Bill Ref", "Bill Date", "Due Date", "Days Until Due", "Amount Outstanding"],
      envelope.data.map((r) => [r.entity_name, r.bill_ref, r.bill_date, r.due_date, r.days_until_due, r.amount_outstanding]),
    );
    showToast(`Exported ${envelope.data.length} rows`);
  }

  const headerProps = { sortColumn, sortDir, onSort: toggleSort };

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <h2>{copy.title}</h2>
          <p className="panel-sub">{copy.subtitle} — click a column to sort</p>
        </div>
        <div className="panel-controls">
          <span className="pager-info">
            {total} bills · {fmtMoney(totalAmount)} total
            {overdueCount > 0 ? ` · ${overdueCount} overdue` : ""}
          </span>
          <button className="pager-btn" type="button" onClick={handleExport} disabled={total === 0}>
            Export CSV
          </button>
        </div>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <SortableHeader column="entity_name" label={copy.entityLabel} {...headerProps} />
              <SortableHeader column="bill_ref" label="Bill Ref" {...headerProps} />
              <SortableHeader column="bill_date" label="Bill Date" {...headerProps} />
              <SortableHeader column="due" label="Status" {...headerProps} />
              <SortableHeader column="amount" label="Amount" numeric {...headerProps} />
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
      <Pager page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />
    </section>
  );
}
