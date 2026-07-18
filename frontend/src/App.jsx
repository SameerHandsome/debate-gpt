import { Outlet } from "react-router-dom";
import SessionSidebar from "./components/SessionSidebar.jsx";

export default function App() {
  return (
    <div className="min-h-screen flex">
      <aside className="w-72 shrink-0 border-r border-slate-200 bg-white">
        <SessionSidebar />
      </aside>
      <main className="flex-1 min-w-0 p-6">
        <Outlet />
      </main>
    </div>
  );
}
