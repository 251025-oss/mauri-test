import type { LanguageCode } from "../api/types";

export interface LanguageInfo {
  code: LanguageCode;
  name: string;
  nativeName: string;
  short: string;
  description: string;
  color: string;
  /** Sens d'écriture du texte natif (le hassaniya est écrit en alphabet arabe dans les données). */
  dir: "rtl" | "ltr";
}

// Codes identiques à LanguageCode dans content/models.py
export const LANGUAGES: LanguageInfo[] = [
  {
    code: "mey",
    name: "Hassaniya",
    nativeName: "الحسانية",
    short: "حس",
    description: "L'arabe dialectal parlé dans toute la Mauritanie",
    color: "var(--green)",
    dir: "rtl",
  },
  {
    code: "fuc",
    name: "Pulaar",
    nativeName: "Pulaar",
    short: "PU",
    description: "Langue peule de la vallée du fleuve Sénégal",
    color: "var(--gold-dark)",
    dir: "ltr",
  },
  {
    code: "snk",
    name: "Soninké",
    nativeName: "Sooninkanxanne",
    short: "SO",
    description: "Langue du Guidimakha et de l'empire du Ghana",
    color: "var(--red)",
    dir: "ltr",
  },
  {
    code: "wol",
    name: "Wolof",
    nativeName: "Wolof",
    short: "WO",
    description: "Parlé au sud-ouest, de Rosso à Nouakchott",
    color: "var(--green-deep)",
    dir: "ltr",
  },
];

export const getLanguage = (code: LanguageCode) =>
  LANGUAGES.find((l) => l.code === code) ?? LANGUAGES[0];

// Parcours : 4 unités de 5 leçons (les leçons côté backend ne sont pas encore exposées par l'API).
export const LESSONS_PER_UNIT = 5;
export const QUESTIONS_PER_LESSON = 8;
export const UNITS = [
  { title: "Premiers pas", subtitle: "Mots et expressions du quotidien", tone: "green" },
  { title: "Conversations", subtitle: "Comprendre des phrases courtes", tone: "gold" },
  { title: "Culture & société", subtitle: "Phrases plus riches", tone: "red" },
  { title: "Maîtrise", subtitle: "Révisions et défis", tone: "deep" },
] as const;
export const TOTAL_LESSONS = UNITS.length * LESSONS_PER_UNIT;
