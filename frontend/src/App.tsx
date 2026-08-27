import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { api } from "./lib/api";
import { Shell } from "./components/Shell";
import Login from "./pages/Login";
import LiveSales from "./pages/LiveSales";
import CRM from "./pages/CRM";
import Inventory from "./pages/Inventory";
import FollowUps from "./pages/FollowUps";
import Analytics from "./pages/Analytics";
import Insights from "./pages/Insights";
import ControlCenter from "./pages/ControlCenter";
import KnowledgeBase from "./pages/KnowledgeBase";
import Logs from "./pages/Logs";

interface Session {
  authenticated: boolean;
  username?: string;
  role?: string;
  display_name?: string;
}

export default function App() {
  const location = useLocation();
  const [session, setSession] = useState<Session | null>(null);

  useEffect(() => {
    let active = true;
    api
      .get<Session>("/api/auth/me")
      .then((data) => active && setSession(data))
      .catch(() => active && setSession({ authenticated: false }));
    return () => {
      active = false;
    };
  }, [location.pathname]);

  if (session === null) {
    return (
      <div className="grid min-h-screen place-items-center">
        <Loader2 size={22} className="animate-spin text-brand-400" />
      </div>
    );
  }

  if (!session.authenticated) {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  return (
    <Shell>
      <Routes>
        <Route path="/" element={<Navigate to="/live" replace />} />
        <Route path="/login" element={<Navigate to="/live" replace />} />
        <Route path="/live" element={<LiveSales />} />
        <Route path="/crm" element={<CRM />} />
        <Route path="/inventory" element={<Inventory />} />
        <Route path="/followups" element={<FollowUps />} />
        <Route path="/analytics" element={<Analytics />} />
        <Route path="/insights" element={<Insights />} />
        <Route path="/control" element={<ControlCenter />} />
        <Route path="/kb" element={<KnowledgeBase />} />
        <Route path="/logs" element={<Logs />} />
        <Route path="*" element={<Navigate to="/live" replace />} />
      </Routes>
    </Shell>
  );
}
