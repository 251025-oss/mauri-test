import { useEffect, useState } from "react";
import { Link, NavLink, Outlet } from "react-router-dom";
import { getMode, onModeChange } from "../api/client";
import type { Mode } from "../api/client";
import { useProgress } from "../state/progress";
import { getLanguage } from "../state/languages";
import { Bolt, Flame, Globe, Home, User } from "./Icons";

export function LangBadge({ code, size = 32 }: { code: Parameters<typeof getLanguage>[0]; size?: number }) {
  const l = getLanguage(code);
  return (
    <span
      className={l.dir === "rtl" ? "ar" : undefined}
      style={{
        width: size, height: size, borderRadius: size * 0.3, background: l.color, color: "#fff",
        display: "grid", placeItems: "center", fontSize: size * 0.4, fontWeight: 900, flexShrink: 0,
      }}
    >
      {l.short}
    </span>
  );
}

export function TopBar() {
  const { state } = useProgress();
  const lang = state.language ? getLanguage(state.language) : null;
  return (
    <header className="topbar">
      <div className="flag-stripe" />
      <div className="topbar-inner">
        <Link to="/langues" className="lang-chip" aria-label="Changer de langue">
          {lang ? <LangBadge code={lang.code} size={26} /> : <Globe />}
          <span className="name">{lang ? lang.name : "Langue"}</span>
        </Link>
        <div className="stats">
          <span className={`stat streak ${state.streak ? "" : "muted"}`} title="Série de jours">
            <Flame /> {state.streak}
          </span>
          <span className="stat xp" title="Points d'expérience">
            <Bolt /> {state.xp}
          </span>
        </div>
      </div>
    </header>
  );
}

export function useApiMode() {
  const [mode, setMode] = useState<Mode | null>(getMode());
  useEffect(() => {
    const off = onModeChange(setMode);
    return () => { off(); };
  }, []);
  return mode;
}

export default function Layout() {
  return (
    <div className="app-shell">
      <TopBar />
      <Outlet />
      <nav className="bottomnav" aria-label="Navigation principale">
        <div className="bottomnav-inner">
          <NavLink to="/apprendre"><Home />Apprendre</NavLink>
          <NavLink to="/langues"><Globe />Langues</NavLink>
          <NavLink to="/profil"><User />Profil</NavLink>
        </div>
      </nav>
    </div>
  );
}
