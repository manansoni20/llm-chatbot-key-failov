const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/+$/, "");

export class ApiError extends Error {
  constructor(status, message, detail = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function buildUrl(path) {
  return `${API_BASE_URL}${path}`;
}

function formatErrorDetail(detail, fallbackMessage) {
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }
  if (Array.isArray(detail) && detail.length > 0) {
    return detail
      .map((item) => {
        if (typeof item === "string") return item;
        const field = Array.isArray(item?.loc) ? item.loc[item.loc.length - 1] : null;
        return field ? `${field}: ${item.msg}` : item?.msg || JSON.stringify(item);
      })
      .join("; ");
  }
  return fallbackMessage;
}

async function parseJsonSafe(response) {
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    return null;
  }
  try {
    return await response.json();
  } catch {
    return null;
  }
}

export async function fetchHealth() {
  const response = await fetch(buildUrl("/health"), {
    method: "GET",
    headers: { Accept: "application/json" },
  });
  const payload = await parseJsonSafe(response);

  if (!response.ok) {
    const message = formatErrorDetail(
      payload?.detail,
      `Health check failed (${response.status})`
    );
    throw new ApiError(response.status, message, payload);
  }

  return payload;
}

export async function sendChatMessage({ sessionId, message }) {
  const response = await fetch(buildUrl("/chat"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify({
      session_id: sessionId,
      message,
    }),
  });

  const payload = await parseJsonSafe(response);

  if (!response.ok) {
    if (response.status === 422) {
      const detailText = formatErrorDetail(
        payload?.detail,
        "Please enter a valid non-empty message."
      );
      throw new ApiError(422, `Validation error (422): ${detailText}`, payload);
    }

    if (response.status === 503) {
      const detailText = formatErrorDetail(
        payload?.detail,
        "all providers unavailable"
      );
      throw new ApiError(
        503,
        `Service unavailable (503): ${detailText}. Your failed request was not saved to history.`,
        payload
      );
    }

    const fallback = formatErrorDetail(
      payload?.detail,
      `Request failed with status ${response.status}`
    );
    throw new ApiError(response.status, fallback, payload);
  }

  if (!payload || typeof payload.reply !== "string") {
    throw new ApiError(
      response.status,
      "Unexpected response from backend. Verify VITE_API_BASE_URL."
    );
  }

  return payload;
}

export async function fetchSessionMessages(sessionId) {
  const encodedId = encodeURIComponent(sessionId);
  const response = await fetch(buildUrl(`/sessions/${encodedId}/messages`), {
    method: "GET",
    headers: { Accept: "application/json" },
  });

  const payload = await parseJsonSafe(response);

  if (!response.ok) {
    const message = formatErrorDetail(
      payload?.detail,
      `Unable to load session history (${response.status})`
    );
    throw new ApiError(response.status, message, payload);
  }

  return payload;
}
