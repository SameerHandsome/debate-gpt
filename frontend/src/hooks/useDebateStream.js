// useDebateStream — subscribes to the SSE stream for a debate session
// and accumulates round-by-round state for the UI to render.
//
// SSE event shape (from src/debate_gpt/api.py:188-197):
//   data: { event: "pro_token" | "con_token" | "judge_score" | "verdict" | "error",
//           round: number,
//           content: string }
// Where `content` is:
//   - plain text for pro_token / con_token
//   - a JSON-stringified object for judge_score / verdict / error
//     (runtime.py:51 does json.dumps before XADD). Must JSON.parse it.

import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";

const INITIAL_STATUS = "idle";

function safeParse(s) {
  if (typeof s !== "string") return null;
  try {
    return JSON.parse(s);
  } catch {
    return null;
  }
}

function emptyRound(n) {
  return { round: n, proText: "", conText: "", judgeScore: null };
}

export default function useDebateStream(id, { topic: initialTopic } = {}) {
  const [status, setStatus] = useState(INITIAL_STATUS);
  const [topic, setTopic] = useState(initialTopic || null);
  const [rounds, setRounds] = useState([]);
  const [verdict, setVerdict] = useState(null);
  const [error, setError] = useState(null);
  const esRef = useRef(null);
  const verdictSeenRef = useRef(false);

  // Lazy-load topic from /result if not provided via route state.
  useEffect(() => {
    let cancelled = false;
    if (initialTopic) {
      setTopic(initialTopic);
      return undefined;
    }
    (async () => {
      try {
        const data = await api.getResult(id);
        if (!cancelled && data && data.debate) setTopic(data.debate.topic);
      } catch {
        // /result may 404 mid-stream — fine, keep null.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id, initialTopic]);

  useEffect(() => {
    if (!id) return undefined;
    setStatus("streaming");
    setError(null);

    const es = new EventSource(api.streamUrl(id));
    esRef.current = es;

    es.onmessage = (ev) => {
      let data;
      try {
        data = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (!data || !data.event) return;

      if (data.event === "pro_token" || data.event === "con_token") {
        const idx = (data.round || 1) - 1;
        const text = typeof data.content === "string" ? data.content : "";
        setRounds((rs) => {
          const next = rs.slice();
          while (next.length <= idx) {
            next.push(emptyRound(next.length + 1));
          }
          const cur = { ...next[idx] };
          if (data.event === "pro_token") {
            cur.proText = (cur.proText || "") + text;
          } else {
            cur.conText = (cur.conText || "") + text;
          }
          next[idx] = cur;
          return next;
        });
        return;
      }

      if (data.event === "judge_score") {
        const parsed = safeParse(data.content);
        if (!parsed) return;
        const idx = (data.round || 1) - 1;
        setRounds((rs) => {
          const next = rs.slice();
          while (next.length <= idx) {
            next.push(emptyRound(next.length + 1));
          }
          next[idx] = { ...next[idx], judgeScore: parsed };
          return next;
        });
        return;
      }

      if (data.event === "verdict") {
        const parsed = safeParse(data.content);
        if (parsed && typeof parsed === "object") setVerdict(parsed);
        verdictSeenRef.current = true;
        setStatus("complete");
        return;
      }

      if (data.event === "error") {
        const parsed = safeParse(data.content);
        setError(
          parsed && parsed.message ? parsed.message : "Unknown server error"
        );
        setStatus("error");
      }
    };

    es.onerror = () => {
      // readyState 0 = CONNECTING (browser will auto-retry), 2 = CLOSED.
      if (es.readyState === EventSource.CLOSED) {
        if (verdictSeenRef.current) {
          setStatus("complete");
        } else {
          setError("Connection closed before the debate finished.");
          setStatus("error");
        }
        es.close();
      }
    };

    return () => {
      es.close();
      esRef.current = null;
    };
  }, [id]);

  return { status, topic, rounds, verdict, error, traceId: null };
}
