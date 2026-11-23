import { Navigate, useNavigate } from "react-router-dom";
import { useProgress } from "../state/progress";
import { getLanguage, LESSONS_PER_UNIT, UNITS } from "../state/languages";
import { useApiMode } from "../components/Layout";
import { Check, Lock, Star, Trophy } from "../components/Icons";

// Décalage horizontal des nœuds pour dessiner un chemin sinueux.
const OFFSETS = [0, 44, 70, 44, 0, -44, -70, -44];

export default function Learn() {
  const { state, todayXp } = useProgress();
  const navigate = useNavigate();
  const mode = useApiMode();
  if (!state.language) return <Navigate to="/" replace />;

  const lang = getLanguage(state.language);
  const done = state.completed[lang.code] ?? 0;
  const goalPct = Math.min(100, Math.round((todayXp / state.dailyGoal) * 100));

  return (
    <main className="page">
      {mode === "demo" && (
        <div className="notice" role="status" style={{ marginBottom: 14 }}>
          <span>⚠️</span>
          <span>
            Mode démo : le serveur Django ne répond pas, les exercices viennent d'un échantillon local.
            Lance <code>python manage.py runserver</code> pour utiliser la vraie base.
          </span>
        </div>
      )}

      <div className="card" style={{ padding: "14px 16px", display: "flex", gap: 14, alignItems: "center" }}>
        <span style={{ color: "var(--gold-dark)" }}><Trophy size={34} /></span>
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 15 }}>
            <span>Objectif du jour</span>
            <span style={{ color: "var(--ink-soft)" }}>{Math.min(todayXp, state.dailyGoal)} / {state.dailyGoal} XP</span>
          </div>
          <div className="goal-bar"><div style={{ width: `${goalPct}%` }} /></div>
        </div>
      </div>

      {UNITS.map((unit, u) => {
        const first = u * LESSONS_PER_UNIT;
        return (
          <section key={unit.title} aria-label={`Unité ${u + 1}`}>
            <div className={`unit-header unit-${unit.tone}`}>
              <div>
                <p style={{ margin: 0, fontSize: 13, letterSpacing: "0.08em", textTransform: "uppercase" }}>
                  Unité {u + 1} · {lang.name}
                </p>
                <h2>{unit.title}</h2>
                <p>{unit.subtitle}</p>
              </div>
            </div>
            <div className="path">
              {Array.from({ length: LESSONS_PER_UNIT }, (_, i) => {
                const idx = first + i;
                const status = idx < done ? "done" : idx === done ? "current" : "locked";
                const isTrophy = i === LESSONS_PER_UNIT - 1;
                return (
                  <div key={idx} className="node-wrap" style={{ transform: `translateX(${OFFSETS[idx % OFFSETS.length]}px)` }}>
                    {status === "current" && <span className="start-bubble">COMMENCER</span>}
                    <button
                      className={`node ${status}`}
                      disabled={status === "locked"}
                      onClick={() => navigate(`/lecon/${idx}`)}
                      aria-label={`Leçon ${idx + 1}${status === "locked" ? " (verrouillée)" : status === "done" ? " (terminée)" : ""}`}
                    >
                      {status === "locked" ? <Lock /> : status === "done" ? <Check /> : isTrophy ? <Trophy /> : <Star />}
                    </button>
                  </div>
                );
              })}
            </div>
          </section>
        );
      })}
    </main>
  );
}
