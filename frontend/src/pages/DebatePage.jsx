import { useLocation, useParams } from "react-router-dom";
import useDebateStream from "../hooks/useDebateStream.js";
import RoundCard from "../components/RoundCard.jsx";
import VerdictBanner from "../components/VerdictBanner.jsx";

export default function DebatePage() {
  const { id } = useParams();
  const location = useLocation();
  const initialTopic =
    location.state && typeof location.state.topic === "string"
      ? location.state.topic
      : undefined;

  const { status, topic, rounds, verdict, error } = useDebateStream(id, {
    topic: initialTopic,
  });

  return (
    <div className="max-w-5xl mx-auto">
      <header className="mb-6">
        <div className="text-xs uppercase tracking-wider text-slate-500">
          Debate session
        </div>
        <h1 className="text-xl font-semibold break-words">
          {topic || <span className="text-slate-400">Loading topic…</span>}
        </h1>
        <div className="text-xs text-slate-400 font-mono mt-1 break-all">
          {id}
        </div>
      </header>

      {error && (
        <div className="mb-4 p-3 rounded border border-red-200 bg-red-50 text-red-800 text-sm">
          {error}
        </div>
      )}

      <div className="space-y-6">
        {rounds.map((r) => (
          <RoundCard key={r.round} roundData={r} />
        ))}
      </div>

      {verdict && <VerdictBanner verdict={verdict} />}

      {status === "streaming" && (
        <div className="mt-6 text-sm text-slate-500 animate-pulse">
          Streaming…
        </div>
      )}
      {status === "complete" && !verdict && (
        <div className="mt-6 text-sm text-slate-500">
          Debate ended without a verdict event.
        </div>
      )}
    </div>
  );
}
