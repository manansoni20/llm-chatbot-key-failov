import React, { useState } from "react";

export default function ChatInput({ onSendMessage, isLoading }) {
  const [input, setInput] = useState("");

  const submitMessage = () => {
    const trimmed = input.trim();
    if (!trimmed || isLoading) {
      return;
    }
    setInput("");
    onSendMessage(trimmed);
  };

  const handleSubmit = (event) => {
    event.preventDefault();
    submitMessage();
  };

  const handleKeyDown = (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submitMessage();
    }
  };

  return (
    <form className="chat-composer" onSubmit={handleSubmit}>
      <div className="composer-box">
        <textarea
          className="composer-textarea"
          data-testid="chat-input"
          rows={1}
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask anything... (Press Enter to send, Shift+Enter for newline)"
          aria-label="Chat message input"
          disabled={isLoading}
        />
        <button
          type="submit"
          className="send-button"
          data-testid="send-button"
          disabled={isLoading || !input.trim()}
          aria-label="Send message"
        >
          {isLoading ? (
            <span className="button-spinner" aria-hidden="true" />
          ) : (
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <line x1="22" y1="2" x2="11" y2="13" />
              <polygon points="22 2 15 22 11 13 2 9 22 2" />
            </svg>
          )}
          <span>{isLoading ? "Sending" : "Send"}</span>
        </button>
      </div>
      <p className="composer-hint">
        Responses route through LiteLLM with Gemini key-pool failover and response caching.
      </p>
    </form>
  );
}
