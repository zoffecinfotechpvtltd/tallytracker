import { useEffect, useState } from "react";
import { api } from "../api.js";
import { fmtMoney, fmtNum } from "../format.js";
import Pager from "./Pager.jsx";

const PAGE_SIZE = 50;

export default function StockView({ tick }) {
  const [lowStockOnly, setLowStockOnly] = useState(false);
  const [page, setPage] = useState(1);
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => setPage(1), [lowStockOnly]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .stock({ lowStockOnly, page, pageSize: PAGE_SIZE })
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
  }, [lowStockOnly, page, tick]);

  return (
    <section className="panel stock-panel">
      <div className="panel-header">
        <h2>Stock</h2>
        <label className="toggle">
          <input type="checkbox" checked={lowStockOnly} onChange={(e) => setLowStockOnly(e.target.checked)} />
          <span>Low stock only</span>
        </label>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Item</th>
              <th className="num">Qty</th>
              <th>Unit</th>
              <th className="num">Value</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr className="empty-row">
                <td colSpan={4}>{loading ? "Loading…" : "No stock items."}</td>
              </tr>
            ) : (
              rows.map((item) => (
                <tr key={item.item_name} className={item.low_stock ? "row-low-stock" : ""}>
                  <td className="truncate" title={item.item_name}>
                    {item.item_name}
                  </td>
                  <td className="num">{fmtNum(item.qty)}</td>
                  <td>{item.unit || ""}</td>
                  <td className="num">{fmtMoney(item.value)}</td>
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
