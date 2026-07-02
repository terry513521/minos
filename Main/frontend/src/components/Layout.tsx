import { useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { api } from "../api/client";
import { AddWorkerModal } from "./AddWorkerModal";

const sections = [
  { hash: "#candidates", label: "Candidates" },
  { hash: "#history", label: "History" },
];

export function Layout() {
  const location = useLocation();
  const [health, setHealth] = useState("…");
  const [workerModalOpen, setWorkerModalOpen] = useState(false);

  useEffect(() => {
    api.health().then((h) => setHealth(h.status)).catch(() => {});
  }, []);

  const activeHash = location.hash || "#candidates";

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="topbar-left">
          <div className="brand">
            <img
              src="/effortless-avatar.png"
              alt=""
              className="brand-avatar"
              width={36}
              height={36}
            />
            <div className="brand-text">
              <span className="brand-mark">Effortless</span>
              <span className="brand-sub">Candidate Finder</span>
            </div>
          </div>
          <nav className="section-nav" aria-label="Sections">
            {sections.map((s) => (
              <a
                key={s.hash}
                href={s.hash}
                className={`section-nav-link${activeHash === s.hash ? " active" : ""}`}
              >
                {s.label}
              </a>
            ))}
          </nav>
        </div>
        <div className="topbar-right">
          <button
            type="button"
            className="button primary topbar-add-worker"
            onClick={() => setWorkerModalOpen(true)}
          >
            Add worker
          </button>
          <span className={`status-pill ${health === "ok" ? "ok" : "bad"}`}>
            <span className="status-dot" />
            API {health}
          </span>
        </div>
      </header>
      <AddWorkerModal open={workerModalOpen} onClose={() => setWorkerModalOpen(false)} />
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
