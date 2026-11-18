// Mode démo : reproduit le comportement de RandomExerciseView / CheckAnswerView
// avec un échantillon local, quand le backend n'est pas lancé.
import data from "../data/demo.json";
import type {
  CheckAnswerRequest,
  CheckAnswerResponse,
  ExerciseQuestion,
  LanguageCode,
} from "./types";

interface Row {
  id: string;
  native: string;
  arabic: string;
  french: string;
  english: string;
  level: string;
  category: string;
}

const rows = data as Record<LanguageCode, Row[]>;
const byId = new Map<string, Row>();
Object.values(rows).forEach((list) => list.forEach((r) => byId.set(r.id, r)));

function shuffle<T>(arr: T[]): T[] {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

export function randomExercise(language: LanguageCode): ExerciseQuestion {
  const pool = rows[language];
  const target = pool[Math.floor(Math.random() * pool.length)];
  const others = pool.filter(
    (r) => r.id !== target.id && r.native !== target.native && r.arabic !== target.arabic,
  );
  const sameLevel = shuffle(others.filter((r) => r.level === target.level));
  const candidates = [...sameLevel, ...shuffle(others.filter((r) => r.level !== target.level))];

  const seen = new Set([target.native]);
  const distractors: Row[] = [];
  for (const c of candidates) {
    if (seen.has(c.native)) continue;
    seen.add(c.native);
    distractors.push(c);
    if (distractors.length === 3) break;
  }

  return {
    question_id: target.id,
    language_code: language,
    prompt: target.arabic,
    prompt_language: "ar",
    level: target.level,
    category: target.category,
    options: shuffle([target, ...distractors]).map((r) => ({ id: r.id, text: r.native })),
  };
}

export function checkAnswer({ question_id, selected_id }: CheckAnswerRequest): CheckAnswerResponse {
  const target = byId.get(question_id)!;
  const selected = byId.get(selected_id);
  const correct = selected_id === question_id || selected?.native === target.native;
  return {
    correct,
    question_id,
    selected_id,
    correct_answer: { id: target.id, text: target.native },
    translations: { arabic: target.arabic, french: target.french, english: target.english },
  };
}
