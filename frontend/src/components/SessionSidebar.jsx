import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api.js";

function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString();
}

function winnerChip(winner) {
  if (!winner) {
    return (
      <span className="text-[10px] text-slate-400">in progress</span>
    );
  }
  if (winner === "tie") {
    return (
      <span className="text-[10px] bg-slate-200 text-slate-700 rounded-full px-1.5 py-0.5">
        tie
      </span>
    );
  }
  const cls =
    winner === "pro"
      ? "bg-emerald-100 text-emerald-800"
      : "bg-rose-100 text-rose-800";
  return (
    <span
      className={`text-[10px] ${cls} rounded-full px-1.5 py-0.5`}
    >
      {winner}
    </span>
  );
}

export default function SessionSidebar() {
  const [debates, setDebates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [pendingDelete, setPendingDelete] = useState(null);
  const navigate = useNavigate();
  const location = useLocation();

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      const { items } = await api.listDebates(1, 20);
      setDebates(items);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  useEffect(() => {
    if (location.pathname === "/") refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname]);

  async function handleDelete(e, id) {
    e.preventDefault();
    e.stopPropagation();
    if (pendingDelete) return;
    setPendingDelete(id);
    const snapshot = debates;
    setDebates(snapshot.filter((d) => d.id !== id));
    try {
      await api.deleteDebate(id);
    } catch (err) {
      setDebates(snapshot);
      setError(`Delete failed: ${err.message}`);
    } finally {
      setPendingDelete(null);
    }
  }

  return (
    <div className="h-full flex flex-col">
      <div className="p-4 border-b border-slate-200">
        <Link
          to="/"
          className="text-base font-semibold text-slate-900 hover:text-indigo-600"
        >
          Debate-GPT
        </Link>
        <div className="text-xs text-slate-500 mt-0.5">Past debates</div>
      </div>

      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {loading && (
          <div className="text-xs text-slate-400 p-2">Loading…</div>
        )}
        {error && (
          <div className="text-xs text-red-700 bg-red-50 border border-red-200 rounded p-2 m-1">
            {error}
          </div>
        )}
        {!loading && !error && debates.length === 0 && (
          <div className="text-xs text-slate-400 p-2">
            No past debates yet.
          </div>
        )}
        {debates.map((d) => {
          const isActive = location.pathname === `/debate/${d.id}`;
          return (
            <div
              key={d.id}
              onClick={() => navigate(`/debate/${d.id}`)}
              className={`group rounded p-2 cursor-pointer hover:bg-slate-50 ${
                isActive ? "bg-indigo-50" : ""
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <div
                    className="text-sm text-slate-800 truncate"
                    title={d.topic}
                  >
                    {d.topic}
                  </div>
                  <div className="flex items-center gap-2 mt-1">
                    {winnerChip(d.winner)}
                    <span className="text-[10px] text-slate-400">
                      {fmtDate(d.created_at)}
                    </span>
                  </div>
                </div>
                <button
                  type="button"
                  aria-label="Delete debate"
                  disabled={pendingDelete === d.id}
                  onClick={(e) => handleDelete(e, d.id)}
                  className="opacity-0 group-hover:opacity-100 text-slate-400 hover:text-red-600 text-xs px-1 disabled:opacity-30"
                >
                  {/* Trash glyph (text-only to avoid an icon-font dependency) */}
                  {"\u{1F5D1}"}
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
