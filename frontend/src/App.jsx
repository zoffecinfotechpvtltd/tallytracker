import { useEffect, useState } from "react";
import { api } from "./api.js";
import { useLiveUpdates } from "./hooks/useLiveUpdates.js";
import { showToast } from "./toast.js";
import Header from "./components/Header.jsx";
import OverviewTiles from "./components/OverviewTiles.jsx";
import Sidebar from "./components/Sidebar.jsx";
import EntitiesView from "./components/EntitiesView.jsx";
import StockView from "./components/StockView.jsx";
import DueListView from "./components/DueListView.jsx";
import ReconciliationView from "./components/ReconciliationView.jsx";
import ActivityView from "./components/ActivityView.jsx";
import EntityDetail from "./components/EntityDetail.jsx";
import ErrorBoundary from "./components/ErrorBoundary.jsx";
import ToastContainer from "./components/ToastContainer.jsx";

export default function App() {
  const { tick, connected } = useLiveUpdates();
  const [activeTab, setActiveTab] = useState("entities");
  const [overview, setOverview] = useState(null);
  const [syncInfo, setSyncInfo] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [openEntityId, setOpenEntityId] = useState(null);

  useEffect(() => {
    let cancelled = false;
    api.overview().then((env) => {
      if (cancelled) return;
      setOverview(env.data);
      setSyncInfo(env);
    });
    return () => {
      cancelled = true;
    };
  }, [tick]);

  async function handleRefresh() {
    setRefreshing(true);
    try {
      const result = await api.refresh();
      if (!result.tally_reachable) {
        showToast("Tally isn't reachable right now — showing last known data", "error");
      } else {
        showToast(result.changes_detected > 0 ? `Synced — ${result.changes_detected} change${result.changes_detected === 1 ? "" : "s"}` : "Synced — nothing new");
      }
    } catch (e) {
      showToast("Refresh failed — try again", "error");
    } finally {
      setRefreshing(false);
    }
  }

  return (
    <>
      <div className="app-shell">
        <Sidebar active={activeTab} onChange={setActiveTab} companyName={syncInfo?.company_name} />
        <div className="content-column">
          <Header syncInfo={syncInfo} live={connected} onRefresh={handleRefresh} refreshing={refreshing} />
          <main className="layout">
            <OverviewTiles data={overview} />

            <ErrorBoundary key={activeTab}>
              {activeTab === "entities" && <EntitiesView tick={tick} onOpenEntity={setOpenEntityId} />}
              {activeTab === "stock" && <StockView tick={tick} />}
              {activeTab === "payable" && <DueListView direction="payable" tick={tick} onOpenEntity={setOpenEntityId} />}
              {activeTab === "receivable" && <DueListView direction="receivable" tick={tick} onOpenEntity={setOpenEntityId} />}
              {activeTab === "reconciliation" && <ReconciliationView />}
              {activeTab === "activity" && <ActivityView tick={tick} />}
            </ErrorBoundary>
          </main>
        </div>
      </div>

      {openEntityId !== null && (
        <ErrorBoundary>
          <EntityDetail entityId={openEntityId} onClose={() => setOpenEntityId(null)} />
        </ErrorBoundary>
      )}

      <ToastContainer />
    </>
  );
}
