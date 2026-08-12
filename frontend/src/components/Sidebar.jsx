import { useEffect, useState } from "react";

const NAV_ITEMS = [
  { id: "entities", label: "Entities" },
  { id: "stock", label: "Stock" },
  { id: "payable", label: "Payable" },
  { id: "receivable", label: "Receivable" },
  { id: "reconciliation", label: "Reconciliation" },
  { id: "activity", label: "Activity" },
];

const COLLAPSE_KEY = "tt_sidebar_collapsed";
const DEFAULT_SUBTITLE = "Precision in every entry. Confidence in every balance.";

export default function Sidebar({ active, onChange, companyName }) {
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(COLLAPSE_KEY) === "1");

  useEffect(() => {
    localStorage.setItem(COLLAPSE_KEY, collapsed ? "1" : "0");
  }, [collapsed]);

  const subtitle = companyName && companyName !== "Your Company Name" ? companyName : DEFAULT_SUBTITLE;

  return (
    <nav className={"sidebar" + (collapsed ? " collapsed" : "")} aria-label="Sections">
      <div className="sidebar-brand">
        <span className="sidebar-brand-mark">{collapsed ? "Z" : "Zoffec Tally Ledger"}</span>
        {!collapsed && <span className="sidebar-brand-sub">{subtitle}</span>}
      </div>

      <ul className="sidebar-list">
        {NAV_ITEMS.map((item) => (
          <li key={item.id}>
            <button
              type="button"
              className={"sidebar-btn" + (active === item.id ? " active" : "")}
              onClick={() => onChange(item.id)}
              title={collapsed ? item.label : undefined}
            >
              <span className="sidebar-dot" aria-hidden="true"></span>
              {!collapsed && <span className="sidebar-label">{item.label}</span>}
            </button>
          </li>
        ))}
      </ul>

      <button
        type="button"
        className="sidebar-toggle"
        onClick={() => setCollapsed((c) => !c)}
        aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        title={collapsed ? "Expand" : "Collapse"}
      >
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ transform: collapsed ? "rotate(180deg)" : "none" }}>
          <polyline points="15 18 9 12 15 6"></polyline>
        </svg>
        {!collapsed && <span>Collapse</span>}
      </button>
    </nav>
  );
}
