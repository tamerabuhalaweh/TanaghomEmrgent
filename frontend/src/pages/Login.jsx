import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Sparkles, ArrowRight, Languages } from "lucide-react";
import { useI18n } from "../lib/i18n";
import { useAuth } from "../lib/auth";
import { toast } from "sonner";

export default function Login() {
  const { t, toggle } = useI18n();
  const { login, user } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("admin@campaign.ai");
  const [password, setPassword] = useState("Admin@12345");
  const [loading, setLoading] = useState(false);

  React.useEffect(() => {
    if (user) navigate("/");
  }, [user, navigate]);

  const onSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      await login(email, password);
      navigate("/");
    } catch (err) {
      toast.error(t("invalidCreds"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen surface grid lg:grid-cols-2" data-testid="login-page">
      {/* Left: form */}
      <div className="flex flex-col justify-between p-8 md:p-12">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-10 h-10 rounded-lg bg-slate-900 text-white grid place-items-center">
              <Sparkles className="w-4 h-4 text-orange-400" />
            </div>
            <div className="font-bold tracking-tight text-slate-900 text-lg">
              {t("appName")}
            </div>
          </div>
          <button
            onClick={toggle}
            className="btn btn-outline !py-1.5 !px-3"
            data-testid="login-language-toggle"
          >
            <Languages className="w-4 h-4" />
            <span className="mono text-xs">{t("language")}</span>
          </button>
        </div>

        <div className="max-w-md w-full mx-auto lg:mx-0">
          <div className="mb-1 text-xs font-semibold uppercase tracking-[0.2em] text-orange-600">
            {t("tagline")}
          </div>
          <h1 className="text-4xl sm:text-5xl font-black tracking-tight text-slate-900 leading-[1.05]">
            {t("login")}
          </h1>
          <p className="mt-3 text-sm text-slate-500">{t("signInHint")}</p>

          <form onSubmit={onSubmit} className="mt-8 space-y-4">
            <div>
              <label className="field-label">{t("email")}</label>
              <input
                type="email"
                className="field-input"
                value={email}
                required
                onChange={(e) => setEmail(e.target.value)}
                data-testid="login-email-input"
              />
            </div>
            <div>
              <label className="field-label">{t("password")}</label>
              <input
                type="password"
                className="field-input"
                value={password}
                required
                onChange={(e) => setPassword(e.target.value)}
                data-testid="login-password-input"
              />
            </div>
            <button
              disabled={loading}
              type="submit"
              className="btn btn-primary w-full !py-3"
              data-testid="login-submit-btn"
            >
              {loading ? "…" : t("signIn")}
              <ArrowRight className="w-4 h-4" />
            </button>
          </form>

          <div className="mt-6 p-3 rounded-md border border-slate-200 bg-white text-xs text-slate-600 mono">
            admin@campaign.ai / Admin@12345
          </div>
        </div>

        <div className="text-xs text-slate-500">
          {t("poweredBy")}
        </div>
      </div>

      {/* Right: hero */}
      <div className="hidden lg:block relative overflow-hidden">
        <img
          src="https://images.unsplash.com/photo-1762968274962-20c12e6e8ecd?crop=entropy&cs=srgb&fm=jpg&ixid=M3w3NDQ2NDF8MHwxfHNlYXJjaHwxfHxidXNpbmVzcyUyMGNvbmZlcmVuY2UlMjBzdGFnZXxlbnwwfHx8fDE3ODMxNTI3MTB8MA&ixlib=rb-4.1.0&q=85"
          alt="stage"
          className="w-full h-full object-cover"
        />
        <div className="absolute inset-0 bg-gradient-to-tr from-slate-900/85 via-slate-900/40 to-transparent" />
        <div className="absolute inset-x-10 bottom-10 text-white max-w-md">
          <div className="text-[11px] uppercase tracking-[0.2em] text-orange-300 font-semibold">
            AI × Marketing × Live Events
          </div>
          <div className="mt-3 text-3xl font-bold tracking-tight leading-tight">
            Plan · Predict · Publish · Perform.
          </div>
          <div className="mt-3 text-sm text-white/80">
            One command center for every event, every platform, every dollar.
          </div>
        </div>
      </div>
    </div>
  );
}
