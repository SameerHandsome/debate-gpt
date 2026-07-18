export default function VerdictBanner({ verdict }) {
  const isTie = verdict.winner === "tie";
  const winnerLabel = isTie
    ? "It's a tie"
    : `${verdict.winner === "pro" ? "Pro" : "Con"} wins the debate`;

  return (
    <section
      className={`mt-6 rounded-2xl p-6 ${
        isTie ? "bg-slate-700 text-white" : "bg-indigo-600 text-white"
      }`}
    >
      <div className="text-xs uppercase tracking-wider opacity-80 mb-1">
        Final verdict
      </div>
      <div className="text-3xl font-bold mb-4">{winnerLabel}</div>

      <div className="grid grid-cols-2 gap-4 max-w-md">
        <div className="bg-white/10 rounded-lg p-3">
          <div className="text-xs uppercase opacity-80">Pro total</div>
          <div className="text-2xl font-mono">{verdict.pro_total}</div>
        </div>
        <div className="bg-white/10 rounded-lg p-3">
          <div className="text-xs uppercase opacity-80">Con total</div>
          <div className="text-2xl font-mono">{verdict.con_total}</div>
        </div>
      </div>

      <div className="mt-4 text-xs opacity-70">
        Trace link:{" "}
        <span
          className="underline decoration-dotted cursor-not-allowed"
          title="LangSmith trace wiring is Day 6 — the verdict event does not include a trace_id."
        >
          coming soon
        </span>
      </div>
    </section>
  );
}
