// Types alignés sur content/serializers.py et content/views.py du backend Django.

export type LanguageCode = "mey" | "fuc" | "snk" | "wol";

export interface ExerciseOption {
  id: string;   // master_id
  text: string; // text_native
}

/** GET /api/v1/exercises/random/?language_code=mey */
export interface ExerciseQuestion {
  question_id: string;
  language_code: LanguageCode;
  prompt: string;            // texte arabe
  prompt_language: string;   // "ar"
  level: string;             // word | phrase | sentence
  category: string;
  options: ExerciseOption[];
}

/** POST /api/v1/exercises/check/ */
export interface CheckAnswerRequest {
  question_id: string;
  selected_id: string;
}

export interface CheckAnswerResponse {
  correct: boolean;
  question_id: string;
  selected_id: string;
  correct_answer: { id: string; text: string };
  translations: { arabic: string; french: string; english: string };
}
