import { relativeTime } from "../format.js";

export default function Header({ syncInfo, live, onRefresh, refreshing }) {
  const offline = syncInfo ? !syncInfo.tally_reachable : false;

  return (
    <>
      {offline && (
        <div className="offline-banner" role="status">
          <span className="offline-dot"></span>
          Tally offline — showing data as of{" "}
          {syncInfo?.last_synced_at ? new Date(syncInfo.last_synced_at).toLocaleString() : "unknown"}
        </div>
      )}
      <header className="ledger-header">
        <div className="sync-status">
          <span className={"sync-dot" + (offline ? " offline" : "") + (live ? " live" : "")}></span>
          <span>
            {offline ? "Offline — last synced " : "Synced "}
            {relativeTime(syncInfo?.last_synced_at)}
            {live && !offline ? " · live" : ""}
          </span>
        </div>
        <button className="btn-refresh" type="button" disabled={refreshing} onClick={onRefresh}>
          {refreshing ? "Syncing…" : "Refresh now"}
        </button>
      </header>
    </>
  );
}
