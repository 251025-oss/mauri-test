import { useCallback, useEffect, useRef, useState } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { ApiError, checkAnswer, fetchRandomExercise } from "../api/client";
import type { CheckAnswerResponse, ExerciseQuestion, LanguageCode } from "../api/types";
import { getLanguage, QUESTIONS_PER_LESSON } from "../state/languages";
import { MAX_HEARTS, PERFECT_BONUS, useProgress, XP_PER_CORRECT } from "../state/progress";
import { Bolt, Check, Cross, Emblem, Heart, Target } from "../components/Icons";

const LEVEL_LABEL: Record<string, string> = { word: "Mot", phrase: "Expression", sentence: "Phrase", paragraph: "Paragraphe" };
const PRAISE = ["Excellent !", "Bravo !", "Parfait !", "Bien joué !", "Super !"];

type Phase = "loading" | "answering" | "feedback" | "finished" | "error";

/** Récupère une question jamais vue dans cette leçon (quelques essais, puis on accepte un doublon). */
async function fetchFresh(lang: LanguageCode, seen: Set<string>) {
  let q = await fetchRandomExercise(lang);
  for (let i = 0; i < 3 && seen.has(q.question_id); i++) q = await fetchRandomExercise(lang);
  return q;
}

export default function Lesson() {
  const { index } = useParams();
  const lessonIndex = Number(index ?? 0);
  const navigate = useNavigate();
  const { state, recordLesson } = useProgress();
  const language = state.language;

  const [phase, setPhase] = useState<Phase>("loading");
  const [question, setQuestion] = useState<ExerciseQuestion | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [result, setResult] = useState<CheckAnswerResponse | null>(null);
  const [hearts, setHearts] = useState(MAX_HEARTS);
  const [solved, setSolved] = useState(0);
  const [answered, setAnswered] = useState(0);
  const [mistakes, setMistakes] = useState(0);
  const [combo, setCombo] = useState(0);
  const [error, setError] = useState("");
  const [shake, setShake] = useState(false);

  const seen = useRef(new Set<string>());
  const freshCount = useRef(0);
  const retryQueue = useRef<ExerciseQuestion[]>([]); // questions ratées, reposées plus tard
  const prefetch = useRef<Promise<ExerciseQuestion> | null>(null);
  const recorded = useRef(false);

  const loadNext = useCallback(async () => {
    if (!language) return;
    setSelected(null);
    setResult(null);
    try {
      let next: ExerciseQuestion | undefined;
      if (freshCount.current < QUESTIONS_PER_LESSON) {
        next = await (prefetch.current ?? fetchFresh(language, seen.current));
        prefetch.current = null;
        freshCount.current += 1;
      } else {
        next = retryQueue.current.shift();
      }
      if (!next) return;
      seen.current.add(next.question_id);
      setQuestion(next);
      setPhase("answering");
      // Pré-charge la question suivante pendant que l'élève réfléchit.
      if (freshCount.current < QUESTIONS_PER_LESSON) prefetch.current = fetchFresh(language, seen.current);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Impossible de charger l'exercice.");
      setPhase("error");
    }
  }, [language]);

  // Garde : en mode StrictMode (dev), React exécute les effets deux fois.
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    loadNext();
  }, [loadNext]);

  const onCheck = useCallback(async () => {
    if (!question || !selected || phase !== "answering") return;
    setPhase("loading");
    try {
      const res = await checkAnswer({ question_id: question.question_id, selected_id: selected });
      setResult(res);
      setAnswered((n) => n + 1);
      if (res.correct) {
        setSolved((n) => n + 1);
        setCombo((c) => c + 1);
      } else {
        setHearts((h) => h - 1);
        setMistakes((m) => m + 1);
        setCombo(0);
        retryQueue.current.push(question);
        setShake(true);
        setTimeout(() => setShake(false), 400);
      }
      setPhase("feedback");
    } catch {
      setError("La vérification a échoué. Réessaie.");
      setPhase("answering");
    }
  }, [question, selected, phase]);

  const finished = solved >= QUESTIONS_PER_LESSON || hearts <= 0;

  const onContinue = useCallback(() => {
    if (finished) setPhase("finished");
    else loadNext();
  }, [finished, loadNext]);

  // Enregistre le résultat une seule fois.
  useEffect(() => {
    if (phase !== "finished" || recorded.current || !language) return;
    recorded.current = true;
    const passed = hearts > 0;
    const xpEarned = solved * XP_PER_CORRECT + (passed && mistakes === 0 ? PERFECT_BONUS : 0);
    recordLesson({ language, xpEarned, answered, correct: solved, passed, lessonIndex });
  }, [phase, hearts, solved, mistakes, answered, language, lessonIndex, recordLesson]);

  // Raccourcis clavier : 1-4 pour choisir, Entrée pour vérifier / continuer.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (phase === "answering" && question) {
        const n = Number(e.key);
        if (n >= 1 && n <= question.options.length) setSelected(question.options[n - 1].id);
        if (e.key === "Enter") onCheck();
      } else if (phase === "feedback" && e.key === "Enter") {
        onContinue();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [phase, question, onCheck, onContinue]);

  if (!language) return <Navigate to="/" replace />;
  const lang = getLanguage(language);

  // ---------- Écran de fin ----------
  if (phase === "finished") {
    const passed = hearts > 0;
    const accuracy = answered ? Math.round((solved / answered) * 100) : 0;
    const xpEarned = solved * XP_PER_CORRECT + (passed && mistakes === 0 ? PERFECT_BONUS : 0);
    return (
      <div className={`result ${passed ? "" : "fail"}`}>
        <Emblem size={110} color={passed ? "var(--gold)" : "var(--red)"} />
        <h1>{passed ? (mistakes === 0 ? "Leçon parfaite !" : "Leçon terminée !") : "Plus de cœurs…"}</h1>
        <p>{passed ? `Tu progresses en ${lang.name}. Continue comme ça !` : "Pas grave, chaque erreur t'apprend quelque chose. Réessaie !"}</p>
        <div className="result-stats">
          <div className="rstat gold"><div className="lbl">XP gagnés</div><div className="val"><Bolt /> {xpEarned}</div></div>
          <div className="rstat green"><div className="lbl">Précision</div><div className="val"><Target /> {accuracy}%</div></div>
          <div className="rstat red"><div className="lbl">Cœurs</div><div className="val"><Heart /> {Math.max(hearts, 0)}</div></div>
        </div>
        <div className="result-actions">
          <button className="btn block" onClick={() => navigate("/apprendre")}>Continuer</button>
          {!passed && (
            <button className="btn ghost block" onClick={() => navigate(0)}>Réessayer</button>
          )}
        </div>
      </div>
    );
  }

  const progressPct = (solved / QUESTIONS_PER_LESSON) * 100;
  const isFeedback = phase === "feedback" && result;
  const optionDir = lang.dir;

  return (
    <div className="lesson">
      <div className="flag-stripe" />
      <div className="lesson-top">
        <button className="icon-btn" onClick={() => navigate("/apprendre")} aria-label="Quitter la leçon">
          <Cross size={26} />
        </button>
        <div className="progress" role="progressbar" aria-valuenow={solved} aria-valuemin={0} aria-valuemax={QUESTIONS_PER_LESSON}>
          <div style={{ width: `${Math.max(progressPct, 3)}%` }} />
        </div>
        <span className="stat hearts" aria-label={`${hearts} cœurs restants`}><Heart size={26} /> {hearts}</span>
      </div>

      <main className="lesson-body">
        {phase === "error" ? (
          <div className="center" style={{ textAlign: "center", gap: 16 }}>
            <div className="notice error">{error}</div>
            <button className="btn" onClick={() => { setPhase("loading"); loadNext(); }}>Réessayer</button>
          </div>
        ) : !question ? (
          <div className="center"><div className="spinner" aria-label="Chargement" /></div>
        ) : (
          <>
            {combo >= 3 && <div className="combo">🔥 {combo} BONNES RÉPONSES D'AFFILÉE</div>}
            <h2>Comment dit-on cela en {lang.name} ?</h2>

            <div className="prompt-row">
              <div className="prompt-avatar"><Emblem size={44} /></div>
              <div className="prompt-bubble">
                <div className="ar" dir="rtl" lang="ar">{question.prompt}</div>
                <div className="prompt-meta">
                  {question.level && <span className="tag">{LEVEL_LABEL[question.level] ?? question.level}</span>}
                  {question.category && <span className="tag gold">{question.category}</span>}
                </div>
              </div>
            </div>

            <div className={`options ${shake ? "shake" : ""}`} role="radiogroup" aria-label="Réponses possibles">
              {question.options.map((opt, i) => {
                let cls = "";
                if (isFeedback) {
                  if (opt.id === result.correct_answer.id || opt.text === result.correct_answer.text) cls = "correct";
                  else if (opt.id === selected) cls = "wrong";
                } else if (opt.id === selected) cls = "selected";
                return (
                  <button
                    key={opt.id}
                    role="radio"
                    aria-checked={opt.id === selected}
                    className={`option ${cls}`}
                    disabled={phase !== "answering"}
                    onClick={() => setSelected(opt.id)}
                  >
                    <span className="key">{i + 1}</span>
                    <span className={`text ${optionDir === "rtl" ? "ar" : ""}`} dir={optionDir}>{opt.text}</span>
                  </button>
                );
              })}
            </div>
          </>
        )}
      </main>

      <footer className={`lesson-foot ${isFeedback ? (result.correct ? "ok" : "ko") : ""}`}>
        <div className="foot-inner">
          {isFeedback ? (
            <>
              <div className="feedback" aria-live="polite">
                <span className="badge" style={{ color: result.correct ? "var(--green)" : "var(--red)" }}>
                  {result.correct ? <Check size={34} /> : <Cross size={30} />}
                </span>
                <div>
                  <h3>{result.correct ? PRAISE[answered % PRAISE.length] : "Bonne réponse :"}</h3>
                  {!result.correct && (
                    <p className={optionDir === "rtl" ? "ar" : ""} dir={optionDir} style={{ fontSize: 17 }}>
                      {result.correct_answer.text}
                    </p>
                  )}
                  {result.translations.french && <p>Français : {result.translations.french}</p>}
                </div>
              </div>
              <button className={`btn ${result.correct ? "" : "red"}`} onClick={onContinue} autoFocus>
                Continuer
              </button>
            </>
          ) : (
            <>
              <button className="btn ghost" onClick={() => { if (question) { retryQueue.current.push(question); loadNext(); } }} disabled={phase !== "answering" || freshCount.current >= QUESTIONS_PER_LESSON}>
                Passer
              </button>
              <button className="btn" onClick={onCheck} disabled={!selected || phase !== "answering"}>
                Vérifier
              </button>
            </>
          )}
        </div>
      </footer>
    </div>
  );
}
