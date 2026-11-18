// Progression de l'apprenant, gardée dans le navigateur (localStorage).
// Quand le backend exposera Profile / PointEvent / UserProgress, il suffira
// de remplacer les fonctions de ce fichier par des appels API.
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import type { LanguageCode } from "../api/types";

export const MAX_HEARTS = 5;
export const XP_PER_CORRECT = 10;
export const PERFECT_BONUS = 15;

export interface ProgressState {
  name: string;
  language: LanguageCode | null;
  xp: number;
  streak: number;
  lastActiveDay: string | null;        // AAAA-MM-JJ
  activeDays: string[];                // 30 derniers jours d'activité
  dailyGoal: number;
  dailyXp: Record<string, number>;     // XP par jour
  completed: Partial<Record<LanguageCode, number>>; // nb de leçons terminées par langue
  answered: number;
  correct: number;
}

const STORAGE_KEY = "maurilingo:progress:v1";

const initialState: ProgressState = {
  name: "Apprenant",
  language: null,
  xp: 0,
  streak: 0,
  lastActiveDay: null,
  activeDays: [],
  dailyGoal: 50,
  dailyXp: {},
  completed: {},
  answered: 0,
  correct: 0,
};

export function today(d = new Date()): string {
  const off = d.getTimezoneOffset() * 60000;
  return new Date(d.getTime() - off).toISOString().slice(0, 10);
}
function dayDiff(a: string, b: string) {
  return Math.round((Date.parse(b) - Date.parse(a)) / 86400000);
}

function load(): ProgressState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return initialState;
    const s = { ...initialState, ...JSON.parse(raw) } as ProgressState;
    // La série est perdue si un jour entier a été manqué.
    if (s.lastActiveDay && dayDiff(s.lastActiveDay, today()) > 1) s.streak = 0;
    return s;
  } catch {
    return initialState;
  }
}

interface LessonResult {
  language: LanguageCode;
  xpEarned: number;
  answered: number;
  correct: number;
  passed: boolean;
  lessonIndex: number;
}

interface ProgressApi {
  state: ProgressState;
  todayXp: number;
  setLanguage: (code: LanguageCode) => void;
  setName: (name: string) => void;
  setDailyGoal: (goal: number) => void;
  recordLesson: (r: LessonResult) => void;
  reset: () => void;
}

const Ctx = createContext<ProgressApi | null>(null);

export function ProgressProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<ProgressState>(load);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch {
      /* stockage indisponible (navigation privée) : on reste en mémoire */
    }
  }, [state]);

  const setLanguage = useCallback((code: LanguageCode) => setState((s) => ({ ...s, language: code })), []);
  const setName = useCallback((name: string) => setState((s) => ({ ...s, name })), []);
  const setDailyGoal = useCallback((dailyGoal: number) => setState((s) => ({ ...s, dailyGoal })), []);
  const reset = useCallback(() => setState(initialState), []);

  const recordLesson = useCallback((r: LessonResult) => {
    setState((s) => {
      const d = today();
      let streak = s.streak;
      if (s.lastActiveDay !== d) {
        streak = s.lastActiveDay && dayDiff(s.lastActiveDay, d) === 1 ? s.streak + 1 : 1;
      }
      const done = s.completed[r.language] ?? 0;
      return {
        ...s,
        xp: s.xp + r.xpEarned,
        streak,
        lastActiveDay: d,
        activeDays: Array.from(new Set([...s.activeDays, d])).slice(-30),
        dailyXp: { ...s.dailyXp, [d]: (s.dailyXp[d] ?? 0) + r.xpEarned },
        completed: {
          ...s.completed,
          // On ne débloque la leçon suivante que si la leçon courante est réussie.
          [r.language]: r.passed && r.lessonIndex >= done ? r.lessonIndex + 1 : done,
        },
        answered: s.answered + r.answered,
        correct: s.correct + r.correct,
      };
    });
  }, []);

  const value = useMemo<ProgressApi>(
    () => ({
      state,
      todayXp: state.dailyXp[today()] ?? 0,
      setLanguage,
      setName,
      setDailyGoal,
      recordLesson,
      reset,
    }),
    [state, setLanguage, setName, setDailyGoal, recordLesson, reset],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useProgress() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useProgress doit être utilisé dans <ProgressProvider>");
  return ctx;
}
