import { useEffect, useState } from "react";
import { api } from "../api.js";
import { relativeTime } from "../format.js";

export default function ActivityView({ tick }) {
  const [changes, setChanges] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    api
      .changes(50)
      .then((env) => {
        if (!cancelled) {
          setChanges(env.data);
          setLoading(false);
        }
      })
      .catch(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [tick]);

  return (
    <aside className="margin-notes full-width" aria-label="Recent changes">
      <h2>Recent Activity</h2>
      <p className="margin-sub">Newest changes first</p>
      <ul className="changes-list">
        {changes.length === 0 ? (
          <li className="empty-row">{loading ? "Loading…" : "No changes yet."}</li>
        ) : (
          changes.map((c) => (
            <li key={c.id}>
              <span className="change-msg">{c.message}</span>
              <span className="change-time">{relativeTime(c.detected_at)}</span>
            </li>
          ))
        )}
      </ul>
    </aside>
  );
}
