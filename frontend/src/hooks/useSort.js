import { useState } from "react";

export function useSort(defaultColumn, defaultDir = "asc") {
  const [sortColumn, setSortColumn] = useState(defaultColumn);
  const [sortDir, setSortDir] = useState(defaultDir);

  function toggleSort(column) {
    if (sortColumn === column) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortColumn(column);
      setSortDir("asc");
    }
  }

  return { sortColumn, sortDir, toggleSort };
}
