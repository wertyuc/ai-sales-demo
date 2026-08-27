import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { KeyRound, Loader2, Zap } from "lucide-react";
import { api } from "../lib/api";
import { Card, ErrorState } from "../components/ui";

export default function Login() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/api/auth/login", { username, password });
      navigate("/live");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось войти");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid min-h-screen place-items-center px-6">
      <div className="w-full max-w-sm animate-fade-in">
        <div className="mb-7 flex flex-col items-center text-center">
          <div className="grid h-12 w-12 place-items-center rounded-2xl bg-gradient-to-br from-brand-500 to-sky-500 shadow-[0_10px_30px_-10px_rgba(99,102,241,.9)]">
            <Zap size={22} className="text-white" />
          </div>
          <h1 className="mt-4 text-xl font-semibold text-slate-100">AI Sales Suite</h1>
          <p className="mt-1 text-xs text-slate-500">
            AI-продавец для Avito · демонстрационная среда
          </p>
        </div>

        <Card className="p-6">
          <form onSubmit={submit} className="space-y-4">
            <label className="block space-y-1.5">
              <span className="text-xs font-medium text-slate-400">Логин</span>
              <input
                className="w-full"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                autoComplete="username"
              />
            </label>
            <label className="block space-y-1.5">
              <span className="text-xs font-medium text-slate-400">Пароль</span>
              <input
                className="w-full"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
                autoFocus
              />
            </label>
            {error && <ErrorState message={error} />}
            <button type="submit" className="btn-primary w-full" disabled={busy}>
              {busy ? <Loader2 size={15} className="animate-spin" /> : <KeyRound size={15} />}
              Войти
            </button>
          </form>
        </Card>

        <p className="mt-4 text-center text-[11px] text-slate-600">
          Учётные данные задаются переменными <span className="font-mono">ADMIN_USERNAME</span> и{" "}
          <span className="font-mono">ADMIN_PASSWORD</span>.
        </p>
      </div>
    </div>
  );
}
