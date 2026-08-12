// Thin fetch wrappers - one function per endpoint. No client-side caching
// library on purpose (keeps the bundle small); useLiveUpdates + each view's
// own effect handle refetching.

async function request(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

export const api = {
  overview: () => request("/api/overview"),

  entities: ({ type = "", search = "", sort = "name_asc", page = 1, pageSize = 50 } = {}) => {
    const params = new URLSearchParams();
    if (type) params.set("type", type);
    if (search) params.set("search", search);
    params.set("sort", sort);
    params.set("page", String(page));
    params.set("page_size", String(pageSize));
    return request("/api/entities?" + params.toString());
  },

  entityDetail: (id) => request(`/api/entities/${id}`),

  entityVouchers: (id) => request(`/api/entities/${id}/vouchers`),

  postFollowup: (id, note, status) =>
    request(`/api/entities/${id}/followup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note, status }),
    }),

  stock: ({ lowStockOnly = false, page = 1, pageSize = 50 } = {}) => {
    const params = new URLSearchParams();
    if (lowStockOnly) params.set("low_stock_only", "true");
    params.set("page", String(page));
    params.set("page_size", String(pageSize));
    return request("/api/stock?" + params.toString());
  },

  billsDue: (direction) => request(`/api/bills-due?direction=${direction}`),

  changes: (limit = 50) => request(`/api/changes?limit=${limit}`),

  refresh: () => request("/api/refresh", { method: "POST" }),

  reconciliationStatements: () => request("/api/reconciliation/statements"),

  reconciliationTransactions: (statementId) =>
    request(`/api/reconciliation/statements/${statementId}/transactions`),

  uploadBankStatement: (file) => {
    const form = new FormData();
    form.append("file", file);
    return request("/api/reconciliation/upload", { method: "POST", body: form });
  },

  confirmMatch: (transactionId, entityId, billRef) =>
    request(`/api/reconciliation/transactions/${transactionId}/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entity_id: entityId, bill_ref: billRef }),
    }),

  ignoreTransaction: (transactionId) =>
    request(`/api/reconciliation/transactions/${transactionId}/ignore`, { method: "POST" }),
};
