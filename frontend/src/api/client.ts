import type {
  CheckAnswerRequest,
  CheckAnswerResponse,
  ExerciseQuestion,
  LanguageCode,
} from "./types";
import * as demo from "./demo";

const API_BASE: string = import.meta.env.VITE_API_BASE ?? "/api/v1";

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

/**
 * "api"  : le backend Django répond.
 * "demo" : backend injoignable → on bascule sur un petit jeu de données local
 *          (extrait de data/processed/app_ready.csv) pour que l'appli reste utilisable.
 */
export type Mode = "api" | "demo";
let mode: Mode | null = null;
const listeners = new Set<(m: Mode) => void>();

export function getMode(): Mode | null {
  return mode;
}
export function onModeChange(fn: (m: Mode) => void) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
function setMode(m: Mode) {
  if (mode !== m) {
    mode = m;
    listeners.forEach((fn) => fn(m));
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    ...init,
  });
  const isJson = res.headers.get("content-type")?.includes("application/json");
  // Un proxy Vite sans backend renvoie souvent du HTML ou un 502/504 : on le traite comme "injoignable".
  if (!isJson) throw new TypeError("Backend unreachable");
  const body = await res.json();
  if (!res.ok) throw new ApiError(body?.detail ?? `Erreur ${res.status}`, res.status);
  return body as T;
}

/** Essaie l'API ; en cas de panne réseau, passe en mode démo. Les erreurs métier (400/404) remontent. */
async function withFallback<T>(apiCall: () => Promise<T>, demoCall: () => T): Promise<T> {
  if (mode === "demo") return demoCall();
  try {
    const result = await apiCall();
    setMode("api");
    return result;
  } catch (err) {
    if (err instanceof ApiError) {
      setMode("api");
      throw err;
    }
    setMode("demo");
    return demoCall();
  }
}

export function fetchRandomExercise(language: LanguageCode): Promise<ExerciseQuestion> {
  return withFallback(
    () => request<ExerciseQuestion>(`/exercises/random/?language_code=${language}`),
    () => demo.randomExercise(language),
  );
}

export function checkAnswer(payload: CheckAnswerRequest): Promise<CheckAnswerResponse> {
  return withFallback(
    () =>
      request<CheckAnswerResponse>(`/exercises/check/`, {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    () => demo.checkAnswer(payload),
  );
}

/** Permet de retenter l'API après une bascule en mode démo. */
export function resetMode() {
  mode = null;
}
