export const fmtMoney = (v) =>
  "₹" + Number(v || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const fmtNum = (v) => Number(v || 0).toLocaleString("en-IN", { maximumFractionDigits: 2 });

export function relativeTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  const diffMs = Date.now() - d.getTime();
  const mins = Math.round(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

// Payable/Receivable due-list badge tone - overdue is always red regardless
// of magnitude, "due soon" window is configurable, everything else reads calm.
export function dueTone(daysUntilDue) {
  if (daysUntilDue === null || daysUntilDue === undefined) return "unknown";
  if (daysUntilDue < 0) return "overdue";
  if (daysUntilDue <= 7) return "soon";
  return "later";
}

export function dueLabel(daysUntilDue) {
  if (daysUntilDue === null || daysUntilDue === undefined) return "No due date";
  if (daysUntilDue < 0) return `${Math.abs(daysUntilDue)}d overdue`;
  if (daysUntilDue === 0) return "Due today";
  return `Due in ${daysUntilDue}d`;
}
