import React, { useCallback, useEffect, useState } from "react";

import {
  ApiError,
  fetchHealth,
  fetchSessionMessages,
  sendChatMessage,
} from "./api/chatApi";
import ChatWindow from "./components/ChatWindow";
import Sidebar from "./components/Sidebar";
import "./App.css";

function generateSessionId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `session-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function createInitialSession() {
  return {
    id: generateSessionId(),
    title: "New Chat",
  };
}

export default function App() {
  const [initialSession] = useState(() => createInitialSession());
  const [sessions, setSessions] = useState([initialSession]);
  const [activeSessionId, setActiveSessionId] = useState(initialSession.id);
  const [messagesBySession, setMessagesBySession] = useState({
    [initialSession.id]: [],
  });
  const [isLoading, setIsLoading] = useState(false);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  const [healthState, setHealthState] = useState({
    loading: true,
    status: "unknown",
    data: null,
    error: null,
  });

  const refreshHealth = useCallback(async () => {
    setHealthState((prev) => ({ ...prev, loading: true, error: null }));
    try {
      const data = await fetchHealth();
      setHealthState({
        loading: false,
        status: data?.status || "ok",
        data,
        error: null,
      });
    } catch (err) {
      const payload = err instanceof ApiError ? err.detail : null;
      setHealthState({
        loading: false,
        status: payload?.status || "unavailable",
        data: payload,
        error: err.message || "Unable to reach backend",
      });
    }
  }, []);

  useEffect(() => {
    refreshHealth();
  }, [refreshHealth]);

  const handleNewSession = () => {
    if (isLoading) return;
    const nextSession = createInitialSession();
    setSessions((prev) => [nextSession, ...prev]);
    setMessagesBySession((prev) => ({
      ...prev,
      [nextSession.id]: [],
    }));
    setActiveSessionId(nextSession.id);
  };

  const handleSelectSession = async (sessionId) => {
    if (sessionId === activeSessionId || isLoading) return;
    setActiveSessionId(sessionId);
    setIsHistoryLoading(true);
    try {
      const data = await fetchSessionMessages(sessionId);
      const persistedMessages = Array.isArray(data?.messages) ? data.messages : [];
      setMessagesBySession((prev) => ({
        ...prev,
        [sessionId]: persistedMessages,
      }));
    } catch (err) {
      const errorMsg = {
        id: `err-${Date.now()}`,
        role: "error",
        status: err instanceof ApiError ? err.status : null,
        content: err.message || "Failed to load session history.",
        created_at: new Date().toISOString(),
      };
      setMessagesBySession((prev) => ({
        ...prev,
        [sessionId]: [...(prev[sessionId] || []), errorMsg],
      }));
    } finally {
      setIsHistoryLoading(false);
    }
  };

  const handleSendMessage = async (text) => {
    const targetSessionId = activeSessionId;
    const nowIso = new Date().toISOString();

    const userMessage = {
      id: `user-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      session_id: targetSessionId,
      role: "user",
      content: text,
      metadata: null,
      created_at: nowIso,
    };

    setMessagesBySession((prev) => ({
      ...prev,
      [targetSessionId]: [...(prev[targetSessionId] || []), userMessage],
    }));

    setSessions((prev) =>
      prev.map((session) =>
        session.id === targetSessionId && session.title === "New Chat"
          ? {
              ...session,
              title: text.length > 36 ? `${text.slice(0, 36)}...` : text,
            }
          : session
      )
    );

    setIsLoading(true);

    try {
      const result = await sendChatMessage({
        sessionId: targetSessionId,
        message: text,
      });

      const assistantMessage = {
        id: `assistant-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
        session_id: result.session_id || targetSessionId,
        role: "assistant",
        content: result.reply,
        metadata: result.metadata,
        created_at: new Date().toISOString(),
      };

      setMessagesBySession((prev) => ({
        ...prev,
        [targetSessionId]: [...(prev[targetSessionId] || []), assistantMessage],
      }));
    } catch (err) {
      const status = err instanceof ApiError ? err.status : null;
      const content =
        err instanceof ApiError
          ? err.message
          : "Network error: unable to reach the backend service.";

      const errorMessage = {
        id: `error-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
        role: "error",
        status,
        content,
        created_at: new Date().toISOString(),
      };

      setMessagesBySession((prev) => ({
        ...prev,
        [targetSessionId]: [...(prev[targetSessionId] || []), errorMessage],
      }));
    } finally {
      setIsLoading(false);
    }
  };

  const activeMessages = messagesBySession[activeSessionId] || [];

  return (
    <div className="app-shell">
      <Sidebar
        sessions={sessions}
        activeSessionId={activeSessionId}
        onNewSession={handleNewSession}
        onSelectSession={handleSelectSession}
        healthState={healthState}
        onRefreshHealth={refreshHealth}
        isOpen={isSidebarOpen}
        onClose={() => setIsSidebarOpen(false)}
      />

      <ChatWindow
        sessionId={activeSessionId}
        messages={activeMessages}
        isLoading={isLoading}
        isHistoryLoading={isHistoryLoading}
        onSendMessage={handleSendMessage}
        onToggleSidebar={() => setIsSidebarOpen((prev) => !prev)}
      />
    </div>
  );
}
