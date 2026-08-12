import { fmtMoney } from "../format.js";

export default function OverviewTiles({ data }) {
  const d = data || {};
  const netClass = (d.net_position ?? 0) >= 0 ? "debit" : "credit";
  return (
    <section className="overview" aria-label="Overview">
      <div className="tile">
        <div className="tile-label">Total Receivables</div>
        <div className="tile-value debit">{fmtMoney(d.total_receivables)}</div>
      </div>
      <div className="tile">
        <div className="tile-label">Total Payables</div>
        <div className="tile-value credit">{fmtMoney(d.total_payables)}</div>
      </div>
      <div className="tile">
        <div className="tile-label">Net Position</div>
        <div className={"tile-value " + netClass}>{fmtMoney(d.net_position)}</div>
      </div>
      <div className="tile">
        <div className="tile-label">Overdue Entities</div>
        <div className="tile-value">{d.overdue_entity_count ?? "—"}</div>
      </div>
    </section>
  );
}
