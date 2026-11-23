# MauriLingo — Frontend

Interface d'apprentissage façon Duolingo pour les langues de Mauritanie
(hassaniya, pulaar, soninké, wolof), aux couleurs du drapeau national :
**vert** `#00843D`, **or** `#FFC72C`, **rouge** `#D21034`.

Stack : React 18 + TypeScript + Vite + React Router. Aucune librairie UI : tout le style est dans `src/styles/theme.css`.

## Installation

Place ce dossier à la racine du projet, à côté de `manage.py` :

```
mauri-test/
├── config/  content/  data/  manage.py ...
└── frontend/        ← ici
```

```bash
cd frontend
npm install
cp .env.example .env      # facultatif
npm run dev               # http://localhost:5173
```

Dans un autre terminal, lance le backend :

```bash
python manage.py runserver   # http://127.0.0.1:8000
```

En développement, Vite redirige `/api/*` vers Django (voir `vite.config.ts`) :
**aucune configuration CORS n'est nécessaire.**

### Mode démo

Si Django ne répond pas, l'appli bascule automatiquement sur un échantillon local
(`src/data/demo.json`, 90 phrases par langue tirées de `data/processed/app_ready.csv`)
et affiche un bandeau jaune. Pratique pour travailler le design sans base de données.

## Fonctionnalités

| Écran | Contenu |
|---|---|
| Accueil `/` | Présentation + choix de la langue |
| Apprendre `/apprendre` | Objectif du jour, parcours de 4 unités × 5 leçons, leçons débloquées une à une |
| Leçon `/lecon/:n` | 8 questions QCM, 5 cœurs, barre de progression, combo, les erreurs sont reposées en fin de leçon, raccourcis clavier (1-4, Entrée) |
| Fin de leçon | XP gagnés, précision, cœurs restants ; bonus +15 XP si leçon parfaite |
| Langues `/langues` | Changer de langue à tout moment |
| Profil `/profil` | Prénom, série de jours, XP, précision, semaine, objectif quotidien, progression par langue |

Le hassaniya (écrit en alphabet arabe dans les données) est affiché de droite à gauche avec une police arabe.

## Lien avec l'API Django

Utilisé aujourd'hui (`content/urls.py`) :

| Méthode | Route | Usage |
|---|---|---|
| GET | `/api/v1/exercises/random/?language_code=mey` | Une question : texte arabe + 4 propositions |
| POST | `/api/v1/exercises/check/` | `{question_id, selected_id}` → correct/incorrect + traductions |

Les types TypeScript correspondants sont dans `src/api/types.ts`.

### Ce qui est stocké côté navigateur (pour l'instant)

XP, série, objectif et leçons terminées sont gardés dans `localStorage`
(`src/state/progress.tsx`), car l'API n'expose pas encore les utilisateurs.
Les modèles existent déjà dans `content/models.py` ; quand ces routes seront prêtes,
il suffira de remplacer les fonctions de `progress.tsx` par des appels API :

- `POST /api/v1/auth/register|login/` → `User` + `Profile`
- `GET /api/v1/languages/`, `GET /api/v1/lessons/?language=mey` → `Language`, `Lesson`, `Theme`
- `GET /api/v1/lessons/<id>/exercises/` → `Exercise`
- `POST /api/v1/attempts/` → `Attempt` + `PointEvent` + `ReviewCard.review()`
- `GET /api/v1/me/` → `Profile.xp_total`, `UserProgress`, `UserBadge`

Les leçons du parcours sont aujourd'hui des séries de questions aléatoires ;
avec `GET /lessons/`, chaque nœud du chemin pourra pointer vers une vraie `Lesson`.

## Production

```bash
npm run build     # génère dist/
```

Deux options :
1. **Même domaine** (recommandé) : servir `dist/` derrière Nginx et proxyfier `/api/` vers Django. Rien à changer.
2. **Domaines séparés** : définir `VITE_API_BASE=https://api.exemple.mr/api/v1` avant le build,
   et ajouter `django-cors-headers` côté backend avec l'origine du frontend.

Pense à rediriger toutes les routes inconnues vers `index.html` (routage côté client).

## Structure

```
src/
├── api/          client.ts (appels + bascule démo), demo.ts, types.ts
├── components/   Layout (barre du haut, navigation), Icons (SVG, emblème du drapeau)
├── pages/        Languages (+ Welcome), Learn, Lesson, Profile
├── state/        languages.ts (langues, unités), progress.tsx (XP, série, leçons)
├── data/         demo.json
└── styles/       theme.css (palette du drapeau)
```
