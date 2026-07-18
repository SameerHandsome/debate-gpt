import { useState } from "react";

function Bar({ label, value, color }) {
  return (
    <div className="text-xs">
      <div className="flex justify-between mb-0.5">
        <span className="text-slate-600">{label}</span>
        <span className="font-mono">{value}/10</span>
      </div>
      <div className="h-1.5 bg-slate-100 rounded overflow-hidden">
        <div
          className={`h-full ${color} transition-all duration-500`}
          style={{ width: `${value * 10}%` }}
        />
      </div>
    </div>
  );
}

// The judge_score payload has `pro_score` / `con_score` populated by the
// backend (agents.py:174-175). The per-criterion fields are still
// A/B-labeled. Decide which side is Pro by comparing A/B sums to
// pro_score — robust because the judge node guarantees pro_score equals
// the sum of whichever side is Pro (verdict.py:23-39).
function pickProSide(score) {
  const sumA =
    score.speaker_a_logic +
    score.speaker_a_evidence +
    score.speaker_a_persuasion;
  const sumB =
    score.speaker_b_logic +
    score.speaker_b_evidence +
    score.speaker_b_persuasion;
  return sumA === score.pro_score ? "a" : "b";
}

function proFields(score) {
  const side = pickProSide(score);
  return {
    logic: side === "a" ? score.speaker_a_logic : score.speaker_b_logic,
    evidence:
      side === "a" ? score.speaker_a_evidence : score.speaker_b_evidence,
    persuasion:
      side === "a" ? score.speaker_a_persuasion : score.speaker_b_persuasion,
  };
}

function conFields(score) {
  const side = pickProSide(score) === "a" ? "b" : "a";
  return {
    logic: side === "a" ? score.speaker_a_logic : score.speaker_b_logic,
    evidence:
      side === "a" ? score.speaker_a_evidence : score.speaker_b_evidence,
    persuasion:
      side === "a" ? score.speaker_a_persuasion : score.speaker_b_persuasion,
  };
}

export default function JudgeScorecard({ score }) {
  const [showReasoning, setShowReasoning] = useState(false);
  const isPro = score.round_winner === "pro";
  const isTie = score.round_winner === "tie";
  const chipClass = isTie
    ? "bg-slate-200 text-slate-700"
    : isPro
    ? "bg-emerald-100 text-emerald-800"
    : "bg-rose-100 text-rose-800";
  const chipLabel = isTie
    ? "Tie"
    : `${score.round_winner === "pro" ? "Pro" : "Con"} wins`;

  return (
    <div
      className="rounded-lg border border-slate-200 bg-slate-50 p-3 cursor-pointer select-none"
      onClick={() => setShowReasoning((s) => !s)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          setShowReasoning((s) => !s);
        }
      }}
    >
      <div className="flex items-center justify-between mb-3">
        <div className="text-sm font-semibold text-slate-700">Judge</div>
        <span
          className={`text-xs font-semibold rounded-full px-2 py-0.5 ${chipClass}`}
        >
          {chipLabel}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <div className="text-xs font-semibold text-emerald-700">
            Pro · {score.pro_score}
          </div>
          <Bar
            label="Logic"
            value={proFields(score).logic}
            color="bg-emerald-500"
          />
          <Bar
            label="Evidence"
            value={proFields(score).evidence}
            color="bg-emerald-500"
          />
          <Bar
            label="Persuasion"
            value={proFields(score).persuasion}
            color="bg-emerald-500"
          />
        </div>
        <div className="space-y-2">
          <div className="text-xs font-semibold text-rose-700">
            Con · {score.con_score}
          </div>
          <Bar
            label="Logic"
            value={conFields(score).logic}
            color="bg-rose-500"
          />
          <Bar
            label="Evidence"
            value={conFields(score).evidence}
            color="bg-rose-500"
          />
          <Bar
            label="Persuasion"
            value={conFields(score).persuasion}
            color="bg-rose-500"
          />
        </div>
      </div>

      {showReasoning && (
        <div className="mt-3 text-sm text-slate-700 border-t border-slate-200 pt-3">
          {score.reasoning}
        </div>
      )}

      <div className="mt-2 text-[10px] text-slate-400 uppercase tracking-wider">
        {showReasoning ? "Click to hide reasoning" : "Click for reasoning"}
      </div>
    </div>
  );
}
