import { useNavigate } from "react-router-dom";
import { LANGUAGES } from "../state/languages";
import { useProgress } from "../state/progress";
import { Emblem } from "../components/Icons";
import type { LanguageCode } from "../api/types";

function LanguageGrid({ onPick }: { onPick: (c: LanguageCode) => void }) {
  const { state } = useProgress();
  return (
    <div className="lang-grid">
      {LANGUAGES.map((l) => (
        <button
          key={l.code}
          className={`card lang-card ${state.language === l.code ? "selected" : ""}`}
          onClick={() => onPick(l.code)}
        >
          <span className={`lang-badge ${l.dir === "rtl" ? "ar" : ""}`} style={{ background: l.color }}>
            {l.short}
          </span>
          <span>
            <h3>{l.name}</h3>
            <p>{l.description}</p>
            <p className={`native ${l.dir === "rtl" ? "ar" : ""}`} dir={l.dir}>
              {l.nativeName}
              {state.completed[l.code] ? ` · ${state.completed[l.code]} leçon(s)` : ""}
            </p>
          </span>
        </button>
      ))}
    </div>
  );
}

/** Écran d'accueil : présentation + choix de la première langue. */
export function Welcome() {
  const { setLanguage } = useProgress();
  const navigate = useNavigate();
  return (
    <div className="app-shell" style={{ background: "#fff" }}>
      <section className="hero">
        <Emblem size={84} />
        <h1>Mauri<span>Lingo</span></h1>
        <p>Apprends le hassaniya, le pulaar, le soninké et le wolof, quelques minutes par jour.</p>
      </section>
      <main className="page" style={{ paddingBottom: 40 }}>
        <h2 className="section-title">Quelle langue veux-tu apprendre ?</h2>
        <LanguageGrid
          onPick={(c) => {
            setLanguage(c);
            navigate("/apprendre");
          }}
        />
        <p style={{ color: "var(--ink-soft)", fontWeight: 600, fontSize: 14, marginTop: 24, textAlign: "center" }}>
          Les questions sont posées en arabe : tu choisis la bonne traduction dans la langue apprise.
        </p>
      </main>
    </div>
  );
}

/** Page "Langues" accessible depuis la navigation. */
export default function Languages() {
  const { setLanguage } = useProgress();
  const navigate = useNavigate();
  return (
    <main className="page">
      <h2 className="section-title" style={{ marginTop: 6 }}>Choisis ta langue</h2>
      <LanguageGrid
        onPick={(c) => {
          setLanguage(c);
          navigate("/apprendre");
        }}
      />
    </main>
  );
}
