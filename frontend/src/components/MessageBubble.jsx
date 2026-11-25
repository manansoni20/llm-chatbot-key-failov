import React from "react";

function formatTimestamp(isoString) {
  if (!isoString) return "";
  try {
    return new Date(isoString).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "";
  }
}

export default function MessageBubble({ message }) {
  if (message.role === "error") {
    return (
      <div className="message-row message-row--error" role="alert">
        <div className="error-card">
          <div className="error-card__header">
            <span className="error-badge">
              {message.status ? `HTTP ${message.status}` : "Request Error"}
            </span>
            <span className="message-time">{formatTimestamp(message.created_at)}</span>
          </div>
          <p className="error-card__text">{message.content}</p>
        </div>
      </div>
    );
  }

  if (message.role === "user") {
    return (
      <div className="message-row message-row--user">
        <div className="user-bubble">
          <div className="bubble-meta-top">
            <span className="role-label role-label--user">You</span>
            {message.created_at && (
              <span className="message-time">{formatTimestamp(message.created_at)}</span>
            )}
          </div>
          <div className="bubble-content">{message.content}</div>
        </div>
      </div>
    );
  }

  const meta = message.metadata || {};
  const resolutionSource = meta.resolution_source || "UNKNOWN";
  const isCacheHit = resolutionSource === "LLM_CACHE";
  const sourceClass = isCacheHit
    ? "source-badge source-badge--cache"
    : "source-badge source-badge--live";

  const keyDisplay =
    meta.key_id === null || meta.key_id === undefined ? "null" : String(meta.key_id);
  const fallbackDisplay =
    meta.fallback_attempts === undefined || meta.fallback_attempts === null
      ? "0"
      : String(meta.fallback_attempts);

  return (
    <div className="message-row message-row--assistant">
      <article className="assistant-card" data-testid="assistant-message">
        <div className="bubble-meta-top">
          <div className="assistant-identity">
            <span className="assistant-avatar" aria-hidden="true">
              AI
            </span>
            <span className="role-label">Assistant</span>
          </div>
          <div className="assistant-top-right">
            <span className={sourceClass} data-testid="meta-source">
              <span className="source-dot" aria-hidden="true" />
              {resolutionSource}
            </span>
            {message.created_at && (
              <span className="message-time">{formatTimestamp(message.created_at)}</span>
            )}
          </div>
        </div>

        <div className="bubble-content bubble-content--assistant">
          {message.content}
        </div>

        {message.metadata && (
          <dl className="telemetry-grid" aria-label="Response metadata">
            <div className="telemetry-item">
              <dt>Model</dt>
              <dd data-testid="meta-model">{meta.model ?? "—"}</dd>
            </div>
            <div className="telemetry-item">
              <dt>Latency</dt>
              <dd data-testid="meta-latency">
                {meta.latency_ms !== undefined && meta.latency_ms !== null
                  ? `${meta.latency_ms} ms`
                  : "—"}
              </dd>
            </div>
            <div className="telemetry-item">
              <dt>Input Tokens</dt>
              <dd data-testid="meta-input-tokens">
                {meta.input_tokens ?? "—"}
              </dd>
            </div>
            <div className="telemetry-item">
              <dt>Output Tokens</dt>
              <dd data-testid="meta-output-tokens">
                {meta.output_tokens ?? "—"}
              </dd>
            </div>
            <div className="telemetry-item">
              <dt>Key ID</dt>
              <dd data-testid="meta-key-id">{keyDisplay}</dd>
            </div>
            <div className="telemetry-item">
              <dt>Fallback Attempts</dt>
              <dd data-testid="meta-fallback-attempts">{fallbackDisplay}</dd>
            </div>
          </dl>
        )}
      </article>
    </div>
  );
}
