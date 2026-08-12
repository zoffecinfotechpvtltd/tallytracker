import { useEffect, useState } from "react";
import { api } from "../api.js";
import { fmtMoney, relativeTime } from "../format.js";
import Pager from "./Pager.jsx";

const PAGE_SIZE = 50;

export default function EntitiesView({ tick, onOpenEntity }) {
  const [typeFilter, setTypeFilter] = useState("");
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [sortColumn, setSortColumn] = useState("name");
  const [sortDir, setSortDir] = useState("asc");
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
        sort: sortColumn === "balance" ? "balance_desc" : "name_asc",
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

  function toggleSort(column) {
    if (sortColumn === column) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortColumn(column);
      setSortDir("asc");
    }
  }

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
        </div>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th
                className={"sortable" + (sortColumn === "name" ? " sorted" + (sortDir === "asc" ? " asc" : "") : "")}
                onClick={() => toggleSort("name")}
              >
                Name
              </th>
              <th>Type</th>
              <th
                className={"num sortable" + (sortColumn === "balance" ? " sorted" + (sortDir === "asc" ? " asc" : "") : "")}
                onClick={() => toggleSort("balance")}
              >
                Balance
              </th>
              <th className="num">Open Bills</th>
              <th className="num">Overdue Bills</th>
              <th>Last Changed</th>
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
