import { useState } from "react";
import JudgeScorecard from "./JudgeScorecard.jsx";

export default function RoundCard({ roundData }) {
  const { round, proText, conText, judgeScore } = roundData;
  const [collapsed, setCollapsed] = useState(false);

  return (
    <section className="rounded-2xl bg-white border border-slate-200 shadow-sm p-5">
      <header className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-500">
          Round {round}
        </h2>
        {judgeScore && (
          <button
            type="button"
            aria-expanded={!collapsed}
            onClick={() => setCollapsed((c) => !c)}
            className="text-xs text-indigo-600 hover:underline"
          >
            {collapsed ? "Show arguments" : "Hide arguments"}
          </button>
        )}
      </header>

      {!collapsed && (
        <div className="grid grid-cols-2 gap-4">
          <div>
            <div className="text-xs font-semibold text-emerald-700 mb-1">
              Pro
            </div>
            <div className="whitespace-pre-wrap text-slate-800 text-sm min-h-[3rem]">
              {proText || <span className="text-slate-400">…</span>}
            </div>
          </div>
          <div>
            <div className="text-xs font-semibold text-rose-700 mb-1">Con</div>
            <div className="whitespace-pre-wrap text-slate-800 text-sm min-h-[3rem]">
              {conText || <span className="text-slate-400">…</span>}
            </div>
          </div>
        </div>
      )}

      {judgeScore && (
        <div className="mt-4">
          <JudgeScorecard score={judgeScore} />
        </div>
      )}
    </section>
  );
}
