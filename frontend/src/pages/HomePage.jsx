import { useLocation, useNavigate } from "react-router-dom";
import DebateForm from "../components/DebateForm.jsx";

export default function HomePage() {
  const navigate = useNavigate();
  const location = useLocation();

  function handleStarted(sessionId, state) {
    navigate(`/debate/${sessionId}`, { state });
  }

  return (
    <div className="max-w-2xl mx-auto" key={location.pathname}>
      <h1 className="text-2xl font-semibold mb-1">Start a debate</h1>
      <p className="text-slate-600 mb-6">
        Two models argue opposing sides; a judge scores each round. Results
        stream live below.
      </p>
      <DebateForm onStarted={handleStarted} />
      <div className="mt-10 p-4 rounded-lg border border-dashed border-slate-300 text-slate-500 text-sm">
        Or pick a past debate from the sidebar to view its final transcript.
      </div>
    </div>
  );
}
