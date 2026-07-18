import { useState } from "react";
import { api } from "../api.js";

const PERSONAS = [
  { id: "oxford", label: "Oxford Debater" },
  { id: "academic", label: "Academic" },
  { id: "street", label: "Street" },
];

export default function DebateForm({ onStarted }) {
  const [topic, setTopic] = useState("");
  const [persona, setPersona] = useState("oxford");
  const [maxRounds, setMaxRounds] = useState(3);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const valid = topic.trim().length >= 3 && topic.trim().length <= 500;

  async function handleSubmit(e) {
    e.preventDefault();
    if (!valid || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      // persona is intentionally NOT sent — the current StartDebateRequest
      // (api.py:63-65) doesn't accept it. Day 6 will wire it.
      const { session_id } = await api.startDebate({
        topic: topic.trim(),
        max_rounds: maxRounds,
      });
      onStarted(session_id, { topic: topic.trim() });
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-2xl bg-white border border-slate-200 shadow-sm p-5 space-y-4"
    >
      <div>
        <label className="block text-sm font-medium mb-1" htmlFor="topic">
          Topic
        </label>
        <textarea
          id="topic"
          rows={3}
          className="w-full rounded border border-slate-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          placeholder="e.g. Universal basic income should be adopted worldwide"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
        />
        <div className="text-xs text-slate-500 mt-1">
          {topic.trim().length}/500
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium mb-1" htmlFor="persona">
            Persona{" "}
            <span className="text-slate-400 font-normal">
              (UI only — Day 6 wires it)
            </span>
          </label>
          <select
            id="persona"
            className="w-full rounded border border-slate-300 px-3 py-2"
            value={persona}
            onChange={(e) => setPersona(e.target.value)}
          >
            {PERSONAS.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium mb-1" htmlFor="rounds">
            Rounds
          </label>
          <select
            id="rounds"
            className="w-full rounded border border-slate-300 px-3 py-2"
            value={maxRounds}
            onChange={(e) => setMaxRounds(Number(e.target.value))}
          >
            {[2, 3, 4, 5].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && (
        <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded p-2">
          {error}
        </div>
      )}

      <button
        type="submit"
        disabled={!valid || submitting}
        className="w-full rounded bg-indigo-600 text-white py-2 font-medium hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {submitting ? "Starting…" : "Start debate"}
      </button>
    </form>
  );
}
