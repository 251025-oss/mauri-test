import { useProgress, today } from "../state/progress";
import { getLanguage, LANGUAGES, TOTAL_LESSONS } from "../state/languages";
import { LangBadge } from "../components/Layout";
import { Bolt, Flame, Target, Trophy } from "../components/Icons";

const DAY_LETTERS = ["D", "L", "M", "M", "J", "V", "S"];
const GOALS = [
  { xp: 20, label: "Tranquille" },
  { xp: 50, label: "Régulier" },
  { xp: 100, label: "Sérieux" },
  { xp: 200, label: "Intense" },
];

export default function Profile() {
  const { state, todayXp, setName, setDailyGoal, reset } = useProgress();
  const accuracy = state.answered ? Math.round((state.correct / state.answered) * 100) : 0;
  const lessonsDone = Object.values(state.completed).reduce((a, b) => a + (b ?? 0), 0);

  // 7 derniers jours
  const week = Array.from({ length: 7 }, (_, i) => {
    const d = new Date();
    d.setDate(d.getDate() - (6 - i));
    const key = today(d);
    return { key, letter: DAY_LETTERS[d.getDay()], on: state.activeDays.includes(key) };
  });

  return (
    <main className="page">
      <div className="card profile-head">
        <div className="avatar">{(state.name || "A").charAt(0).toUpperCase()}</div>
        <div style={{ flex: 1 }}>
          <input value={state.name} onChange={(e) => setName(e.target.value)} aria-label="Ton prénom" maxLength={30} />
          <p style={{ margin: "6px 0 0", color: "var(--ink-soft)", fontSize: 14 }}>
            {state.language ? `Apprend le ${getLanguage(state.language).name}` : "Aucune langue choisie"}
          </p>
        </div>
      </div>

      <h2 className="section-title">Statistiques</h2>
      <div className="stat-grid">
        <div className="card stat-card"><span style={{ color: "#f08a00" }}><Flame size={30} /></span><div><b>{state.streak}</b><span>Jours de série</span></div></div>
        <div className="card stat-card"><span style={{ color: "var(--gold-dark)" }}><Bolt size={30} /></span><div><b>{state.xp}</b><span>XP au total</span></div></div>
        <div className="card stat-card"><span style={{ color: "var(--green)" }}><Trophy size={30} /></span><div><b>{lessonsDone}</b><span>Leçons terminées</span></div></div>
        <div className="card stat-card"><span style={{ color: "var(--red)" }}><Target size={30} /></span><div><b>{accuracy}%</b><span>Précision</span></div></div>
      </div>

      <h2 className="section-title">Cette semaine</h2>
      <div className="card" style={{ padding: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <span>Aujourd'hui</span>
          <span style={{ color: "var(--ink-soft)" }}>{todayXp} / {state.dailyGoal} XP</span>
        </div>
        <div className="goal-bar"><div style={{ width: `${Math.min(100, (todayXp / state.dailyGoal) * 100)}%` }} /></div>
        <div className="week">
          {week.map((d) => (
            <div key={d.key}>{d.letter}<div className={`dot ${d.on ? "on" : ""}`}>{d.on ? <Flame size={16} /> : null}</div></div>
          ))}
        </div>
      </div>

      <h2 className="section-title">Objectif quotidien</h2>
      <div className="stat-grid">
        {GOALS.map((g) => (
          <button
            key={g.xp}
            className={`card stat-card ${state.dailyGoal === g.xp ? "lang-card selected" : ""}`}
            style={{ textAlign: "left", fontFamily: "inherit" }}
            onClick={() => setDailyGoal(g.xp)}
          >
            <div><b style={{ fontSize: 17 }}>{g.label}</b><span>{g.xp} XP / jour</span></div>
          </button>
        ))}
      </div>

      <h2 className="section-title">Mes langues</h2>
      <div className="card" style={{ padding: "6px 16px" }}>
        {LANGUAGES.map((l, i) => {
          const done = state.completed[l.code] ?? 0;
          return (
            <div key={l.code} style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 0", borderTop: i ? "2px solid var(--line)" : 0 }}>
              <LangBadge code={l.code} size={36} />
              <div style={{ flex: 1 }}>
                <div>{l.name}</div>
                <div className="goal-bar" style={{ height: 10, marginTop: 6 }}>
                  <div style={{ width: `${(done / TOTAL_LESSONS) * 100}%`, background: "var(--green)" }} />
                </div>
              </div>
              <span style={{ color: "var(--ink-soft)", fontSize: 14 }}>{done}/{TOTAL_LESSONS}</span>
            </div>
          );
        })}
      </div>

      <div style={{ textAlign: "center", marginTop: 30 }}>
        <button
          className="btn ghost"
          style={{ color: "var(--red)" }}
          onClick={() => { if (window.confirm("Effacer toute ta progression ?")) reset(); }}
        >
          Réinitialiser la progression
        </button>
      </div>
    </main>
  );
}
