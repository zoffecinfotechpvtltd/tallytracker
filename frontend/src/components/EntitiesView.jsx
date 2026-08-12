import { useEffect, useState } from "react";
import { api } from "../api.js";
import { fmtMoney, relativeTime } from "../format.js";
import { useSort } from "../hooks/useSort.js";
import { downloadCsv } from "../csv.js";
import { showToast } from "../toast.js";
import Pager from "./Pager.jsx";
import SortableHeader from "./SortableHeader.jsx";

const PAGE_SIZE = 50;

export default function EntitiesView({ tick, onOpenEntity }) {
  const [typeFilter, setTypeFilter] = useState("");
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const { sortColumn, sortDir, toggleSort } = useSort("name");
  const [page, setPage] = useState(1);
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => setPage(1), [typeFilter, debouncedSearch, sortColumn, sortDir]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .entities({
        type: typeFilter,
        search: debouncedSearch,
        sortBy: sortColumn,
        sortDir,
        page,
        pageSize: PAGE_SIZE,
      })
      .then((envelope) => {
        if (cancelled) return;
        setRows(envelope.data);
        setTotal(envelope.total ?? envelope.data.length);
        setLoading(false);
      })
      .catch(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [typeFilter, debouncedSearch, sortColumn, sortDir, page, tick]);

  async function handleExport() {
    if (total === 0) return;
    const envelope = await api.entities({
      type: typeFilter, search: debouncedSearch, sortBy: sortColumn, sortDir, page: 1, pageSize: 100000,
    });
    downloadCsv(
      `entities-${new Date().toISOString().slice(0, 10)}.csv`,
      ["Name", "Type", "Balance", "Balance Type", "Open Bills", "Overdue Bills", "Last Changed"],
      envelope.data.map((r) => [
        r.name, r.type, r.current_balance, r.balance_type, r.open_bill_count, r.overdue_bill_count, r.last_changed_at,
      ]),
    );
    showToast(`Exported ${envelope.data.length} rows`);
  }

  const headerProps = { sortColumn, sortDir, onSort: toggleSort };

  return (
    <section className="panel entities-panel">
      <div className="panel-header">
        <h2>Entities</h2>
        <div className="panel-controls">
          <div className="seg" role="tablist" aria-label="Entity type">
            {[
              { v: "", label: "All" },
              { v: "customer", label: "Customers" },
              { v: "vendor", label: "Vendors" },
            ].map((opt) => (
              <button
                key={opt.v}
                type="button"
                className={"seg-btn" + (typeFilter === opt.v ? " active" : "")}
                role="tab"
                aria-selected={typeFilter === opt.v}
                onClick={() => setTypeFilter(opt.v)}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <input
            className="search-input"
            type="search"
            placeholder="Search ledger…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <button className="pager-btn" type="button" onClick={handleExport} disabled={total === 0}>
            Export CSV
          </button>
        </div>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <SortableHeader column="name" label="Name" {...headerProps} />
              <SortableHeader column="type" label="Type" {...headerProps} />
              <SortableHeader column="balance" label="Balance" numeric {...headerProps} />
              <SortableHeader column="open_bills" label="Open Bills" numeric {...headerProps} />
              <SortableHeader column="overdue_bills" label="Overdue Bills" numeric {...headerProps} />
              <SortableHeader column="last_changed" label="Last Changed" {...headerProps} />
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr className="empty-row">
                <td colSpan={6}>{loading ? "Loading…" : "No entities match."}</td>
              </tr>
            ) : (
              rows.map((r) => (
                <tr
                  key={r.id}
                  className={"clickable" + (r.overdue_bill_count > 0 ? " row-overdue" : "")}
                  onClick={() => onOpenEntity(r.id)}
                >
                  <td className="truncate" title={r.name}>
                    {r.name}
                  </td>
                  <td>{r.type || "—"}</td>
                  <td className="num">
                    {fmtMoney(r.current_balance)}{" "}
                    <span className={"pill " + (r.balance_type === "Cr" ? "cr" : "dr")}>{r.balance_type || "-"}</span>
                  </td>
                  <td className="num">{r.open_bill_count}</td>
                  <td className="num">{r.overdue_bill_count}</td>
                  <td>{relativeTime(r.last_changed_at)}</td>
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
