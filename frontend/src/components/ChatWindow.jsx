import React, { useEffect, useRef, useState } from "react";

import ChatInput from "./ChatInput";
import MessageBubble from "./MessageBubble";

const STARTER_PROMPTS = [
  "Explain how LLM response caching reduces latency and token cost.",
  "What is API key failover and why does it improve reliability?",
  "Summarize the difference between LIVE_INFERENCE and LLM_CACHE.",
];

export default function ChatWindow({
  sessionId,
  messages,
  isLoading,
  isHistoryLoading,
  onSendMessage,
  onToggleSidebar,
}) {
  const bottomRef = useRef(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  const handleCopySession = async () => {
    try {
      await navigator.clipboard.writeText(sessionId);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      // Clipboard API may be unavailable in non-HTTPS contexts
    }
  };

  return (
    <main className="chat-main">
      <header className="chat-header">
        <div className="chat-header__left">
          <button
            type="button"
            className="mobile-menu-btn"
            onClick={onToggleSidebar}
            aria-label="Toggle sidebar"
          >
            <svg
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <line x1="3" y1="6" x2="21" y2="6" />
              <line x1="3" y1="12" x2="21" y2="12" />
              <line x1="3" y1="18" x2="21" y2="18" />
            </svg>
          </button>
          <div>
            <h1 className="chat-header__title">AI Gateway Chat</h1>
            <p className="chat-header__subtitle">
              Session{" "}
              <code className="session-pill" title={sessionId}>
                {sessionId}
              </code>
            </p>
          </div>
        </div>

        <div className="chat-header__right">
          <button
            type="button"
            className="copy-session-btn"
            onClick={handleCopySession}
            title="Copy session ID"
          >
            {copied ? "Copied" : "Copy ID"}
          </button>
        </div>
      </header>

      <section className="messages-viewport" aria-label="Conversation messages">
        {isHistoryLoading ? (
          <div className="empty-state">
            <div className="typing-indicator" aria-label="Loading session history">
              <span />
              <span />
              <span />
            </div>
            <p className="empty-state__subtitle">Loading conversation history...</p>
          </div>
        ) : messages.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state__icon" aria-hidden="true">
              <svg
                width="28"
                height="28"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
              </svg>
            </div>
            <h2 className="empty-state__title">Start a new conversation</h2>
            <p className="empty-state__subtitle">
              Every assistant reply surfaces real-time LiteLLM telemetry: inference source
              (<code>LIVE_INFERENCE</code> vs <code>LLM_CACHE</code>), model, latency,
              token usage, key ID, and fallback attempts.
            </p>
            <div className="starter-grid">
              {STARTER_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  type="button"
                  className="starter-chip"
                  onClick={() => onSendMessage(prompt)}
                  disabled={isLoading}
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="messages-list">
            {messages.map((msg) => (
              <MessageBubble key={msg.id} message={msg} />
            ))}

            {isLoading && (
              <div className="message-row message-row--assistant" role="status" aria-live="polite">
                <div className="loading-card">
                  <span className="assistant-avatar" aria-hidden="true">
                    AI
                  </span>
                  <div className="loading-card__body">
                    <div className="typing-indicator" aria-hidden="true">
                      <span />
                      <span />
                      <span />
                    </div>
                    <span className="loading-text">Waiting for response...</span>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
        <div ref={bottomRef} />
      </section>

      <ChatInput onSendMessage={onSendMessage} isLoading={isLoading} />
    </main>
  );
}
