import React from "react";

export default function Sidebar({
  sessions,
  activeSessionId,
  onNewSession,
  onSelectSession,
  healthState,
  onRefreshHealth,
  isOpen,
  onClose,
}) {
  const isHealthy = healthState.status === "ok";

  return (
    <>
      {isOpen && (
        <div
          className="sidebar-backdrop"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      <aside className={`sidebar ${isOpen ? "sidebar--open" : ""}`} aria-label="Chat sidebar">
        <div className="sidebar__top">
          <div className="brand">
            <div className="brand__logo" aria-hidden="true">
              L
            </div>
            <div>
              <div className="brand__name">Lyftr AI</div>
              <div className="brand__tagline">LiteLLM Gateway UI</div>
            </div>
          </div>

          <button
            type="button"
            className="sidebar-close-btn"
            onClick={onClose}
            aria-label="Close sidebar"
          >
            &times;
          </button>
        </div>

        <div className="sidebar__actions">
          <button
            type="button"
            className="new-chat-btn"
            onClick={() => {
              onNewSession();
              onClose();
            }}
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
            <span>New Session</span>
          </button>
        </div>

        <div className="sidebar__section">
          <div className="sidebar__section-label">Sessions</div>
          <ul className="session-list">
            {sessions.map((session) => {
              const isActive = session.id === activeSessionId;
              return (
                <li key={session.id}>
                  <button
                    type="button"
                    className={`session-item ${isActive ? "session-item--active" : ""}`}
                    onClick={() => {
                      onSelectSession(session.id);
                      onClose();
                    }}
                    title={session.id}
                  >
                    <span className="session-item__title">{session.title}</span>
                    <span className="session-item__id">{session.id}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>

        <div className="sidebar__footer">
          <div className="health-card">
            <div className="health-card__header">
              <span className="health-card__title">Gateway Readiness</span>
              <button
                type="button"
                className="health-refresh-btn"
                onClick={onRefreshHealth}
                title="Refresh /health status"
              >
                Refresh
              </button>
            </div>

            <div className="health-status-row">
              <span
                className={`health-dot ${
                  healthState.loading
                    ? "health-dot--loading"
                    : isHealthy
                      ? "health-dot--ok"
                      : "health-dot--error"
                }`}
                aria-hidden="true"
              />
              <span className="health-status-text">
                {healthState.loading
                  ? "Checking..."
                  : isHealthy
                    ? "Ready (ok)"
                    : "Unavailable"}
              </span>
            </div>

            {healthState.data && (
              <div className="health-details">
                <div>Keys configured: {healthState.data.keys_configured ?? "—"}</div>
                <div>
                  Cache: {healthState.data.cache_enabled ? "Enabled" : "Disabled"}
                </div>
              </div>
            )}

            {healthState.error && (
              <div className="health-error">{healthState.error}</div>
            )}
          </div>
        </div>
      </aside>
    </>
  );
}
