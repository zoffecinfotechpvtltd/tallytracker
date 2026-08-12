export default function SortableHeader({ column, label, sortColumn, sortDir, onSort, numeric = false }) {
  const active = sortColumn === column;
  return (
    <th
      className={(numeric ? "num " : "") + "sortable" + (active ? " sorted" + (sortDir === "asc" ? " asc" : "") : "")}
      onClick={() => onSort(column)}
    >
      {label}
    </th>
  );
}
