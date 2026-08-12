export default function Pager({ page, pageSize, total, onPageChange }) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="pager">
      <button className="pager-btn" type="button" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>
        &#8249; Prev
      </button>
      <span className="pager-info">
        Page {page} of {totalPages} ({total})
      </span>
      <button className="pager-btn" type="button" disabled={page >= totalPages} onClick={() => onPageChange(page + 1)}>
        Next &#8250;
      </button>
    </div>
  );
}
