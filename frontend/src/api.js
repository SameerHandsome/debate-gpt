// Frontend API client for the Day 3 FastAPI backend.
// Uses native fetch (no axios) and exports an SSE URL helper for EventSource.

const BASE = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");

/**
 * @typedef {Object} StartDebateReq
 * @property {string} topic        3..500 chars
 * @property {number} [max_rounds] 2..5
 *
 * @typedef {Object} StartDebateRes
 * @property {string} session_id
 * @property {"pending"} status
 *
 * @typedef {Object} RoundScore
 * @property {number} speaker_a_logic
 * @property {number} speaker_a_evidence
 * @property {number} speaker_a_persuasion
 * @property {number} speaker_b_logic
 * @property {number} speaker_b_evidence
 * @property {number} speaker_b_persuasion
 * @property {"pro"|"con"|"tie"} round_winner   // already translated by the backend
 * @property {number} pro_score                  // derived total
 * @property {number} con_score                  // derived total
 * @property {string} reasoning
 *
 * @typedef {Object} Verdict
 * @property {number} pro_total
 * @property {number} con_total
 * @property {"pro"|"con"|"tie"} winner
 *
 * @typedef {Object} DebateListItem
 * @property {string} id
 * @property {string} topic
 * @property {"pending"|"running"|"complete"|"error"} status
 * @property {"pro"|"con"|"tie"|null} winner
 * @property {string} created_at
 * @property {string|null} completed_at
 */

async function jsonFetch(path, opts = {}) {
  const res = await fetch(BASE + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body && body.detail) detail += `: ${body.detail}`;
    } catch (_) {
      /* ignore parse errors on the error body */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  /** @returns {Promise<StartDebateRes>} */
  startDebate(body) {
    return jsonFetch("/debate/start", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  /** @returns {Promise<{debate: object, rounds: object[]}>} */
  getResult(id) {
    return jsonFetch(`/debate/${id}/result`);
  },

  /** @returns {Promise<{page:number, page_size:number, total:number, items: DebateListItem[]}>} */
  listDebates(page = 1, pageSize = 20) {
    return jsonFetch(`/debates?page=${page}&page_size=${pageSize}`);
  },

  /** @returns {Promise<null>} 204 on success */
  deleteDebate(id) {
    return jsonFetch(`/debate/${id}`, { method: "DELETE" });
  },

  /** @returns {string} the SSE URL — caller wraps in EventSource */
  streamUrl(id) {
    return `${BASE}/debate/${id}/stream`;
  },
};

export { BASE };
