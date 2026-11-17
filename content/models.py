"""
apps/content/models.py  —  version complète et corrigée.

⚠ NE SUPPRIMEZ PAS MasterPhrase : c'est la table d'import brute.
  Si elle disparaît de ce fichier, `makemigrations` propose un DeleteModel
  (= DROP TABLE content_master_phrase). Vérifiez toujours avec `sqlmigrate`.
"""
import hashlib
import re
import unicodedata
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Sum
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone


# ============================================================
# 0. CHOIX COMMUNS + TABLE D'IMPORT BRUTE (inchangée)
# ============================================================

class LanguageCode(models.TextChoices):
    HASSANIYA = "mey", "Hassaniya"
    PULAAR = "fuc", "Pulaar"
    SONINKE = "snk", "Soninke"
    WOLOF = "wol", "Wolof"


class Level(models.TextChoices):
    WORD = "word", "Word"
    PHRASE = "phrase", "Phrase"
    SENTENCE = "sentence", "Sentence"
    PARAGRAPH = "paragraph", "Paragraph"


class MasterPhrase(models.Model):
    """Table brute alimentée par ingest_master. Source de la copie normalisée."""
    master_id = models.CharField(max_length=64, unique=True)
    language_code = models.CharField(max_length=3, choices=LanguageCode.choices)

    text_native = models.TextField()
    text_arabic = models.TextField(blank=True, default="")
    text_french = models.TextField(blank=True, default="")
    text_english = models.TextField(blank=True, default="")

    category = models.CharField(max_length=100, blank=True, default="")
    level = models.CharField(max_length=20, choices=Level.choices, blank=True, default="")

    source_name = models.CharField(max_length=255, blank=True, default="")
    source_url = models.URLField(max_length=1000, blank=True, default="")

    is_lesson_ready = models.BooleanField(default=False, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "content_master_phrase"
        indexes = [
            models.Index(fields=["language_code", "level"], name="mp_lang_level_idx"),
            models.Index(fields=["language_code", "is_lesson_ready"], name="mp_lang_ready_idx"),
        ]

    def __str__(self):
        return f"[{self.language_code}] {self.text_native[:40]}"


# ============================================================
# OUTILS DE NORMALISATION
# ============================================================
# Pourquoi des empreintes (hash) ? Un index B-tree PostgreSQL refuse les valeurs
# de plus de ~2,7 Ko : une contrainte unique directement sur un TextField échoue
# dès qu'un paragraphe (histoire, conte) est long. On indexe donc l'empreinte.

_SPACES = re.compile(r"\s+")
_ARABIC_MARKS = re.compile("[\u0640\u064B-\u065F\u0670]") # tatweel + voyelles brèves


def normalize_text(value):
    """Unicode NFC, espaces multiples réduits, bords retirés."""
    return _SPACES.sub(" ", unicodedata.normalize("NFC", value or "")).strip()


def arabic_key(value):
    """Clé de comparaison de l'arabe : sans voyelles brèves ni tatweel."""
    return _ARABIC_MARKS.sub("", normalize_text(value))


def translation_key(value):
    """Clé de comparaison d'une traduction : insensible à la casse."""
    return normalize_text(value).casefold()


def text_digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def estimate_unit_type(word_count):
    """Seuils indicatifs, à ajuster selon vos données."""
    if word_count <= 1:
        return Level.WORD
    if word_count <= 4:
        return Level.PHRASE
    if word_count <= 30:
        return Level.SENTENCE
    return Level.PARAGRAPH

def estimate_difficulty(word_count):
    """Difficulté 1 à 5 selon la longueur (heuristique simple)."""
    for limit, score in ((1, 1), (4, 2), (10, 3), (25, 4)):
        if word_count <= limit:
            return score
    return 5


class Profile(models.Model):

    class Role(models.TextChoices):
        LEARNER = "learner", "Apprenant"
        CONTRIBUTOR = "contributor", "Contributeur"
        REVIEWER = "reviewer", "Validateur"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.LEARNER)

    # Total mis en cache ; la vérité reste l'historique PointEvent.
    xp_total = models.PositiveIntegerField(default=0)

    def recompute_xp(self):
        total = self.user.point_events.aggregate(total=Sum("points"))["total"] or 0
        self.xp_total = max(total, 0)
        self.save(update_fields=["xp_total"])

    def __str__(self):
        return f"Profil de {self.user}"


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.get_or_create(user=instance)


# ============================================================
# 2. LANGUES
# ============================================================

class Language(models.Model):

    class Script(models.TextChoices):
        ARABIC = "arabic", "Arabe"
        LATIN = "latin", "Latin"
        OTHER = "other", "Autre"

    class Direction(models.TextChoices):
        RTL = "rtl", "Droite vers gauche"
        LTR = "ltr", "Gauche vers droite"

    code = models.CharField(max_length=10, unique=True)
    name = models.CharField(max_length=100)
    script = models.CharField(max_length=20, choices=Script.choices, default=Script.LATIN)
    direction = models.CharField(max_length=3, choices=Direction.choices, default=Direction.LTR)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})"


# ============================================================
# 3. THEMES
# ============================================================

class Theme(models.Model):

    name = models.CharField(max_length=100, unique=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return self.name


# ============================================================
# 4. PROVENANCE DES DONNEES
# ============================================================
# Remplace source_name / source_url de MasterPhrase (absents du schéma initial).

class DataSource(models.Model):

    name = models.CharField(max_length=255)
    url = models.URLField(max_length=1000, blank=True, default="")
    license = models.CharField(max_length=100, blank=True, default="")

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["name", "url"], name="uniq_datasource_name_url")
        ]

    def __str__(self):
        return self.name


# ============================================================
# 5. PHRASES SOURCES (pivot arabe)
# ============================================================

class SourceSentence(models.Model):

    arabic_text = models.TextField()

    # Unicité portée par l'empreinte (voir plus haut). Calculée dans save().
    text_hash = models.CharField(max_length=64, unique=True, editable=False)

    theme = models.ForeignKey(Theme, on_delete=models.PROTECT, related_name="source_sentences")

    unit_type = models.CharField(max_length=20, choices=Level.choices, blank=True, default="")
    word_count = models.PositiveIntegerField(default=0)
    difficulty = models.PositiveSmallIntegerField(
        default=1, validators=[MinValueValidator(1), MaxValueValidator(5)]
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        indexes = [
            models.Index(fields=["theme", "difficulty"], name="src_theme_diff_idx"),
        ]

    def save(self, *args, **kwargs):
        self.arabic_text = normalize_text(self.arabic_text)
        self.text_hash = text_digest(arabic_key(self.arabic_text))
        if not self.word_count:
            self.word_count = len(self.arabic_text.split())
        if not self.unit_type:
            self.unit_type = estimate_unit_type(self.word_count)
        fields = kwargs.get("update_fields")
        if fields is not None and "arabic_text" in fields:
            kwargs["update_fields"] = set(fields) | {"text_hash"}
        super().save(*args, **kwargs)

    def __str__(self):
        return self.arabic_text[:80]


# ============================================================
# 6. TRADUCTIONS
# ============================================================

class Translation(models.Model):

    class Status(models.TextChoices):
        RAW = "raw", "Brute"
        VALIDATED = "validated", "Validée"
        FLAGGED = "flagged", "Signalée"

    source = models.ForeignKey(SourceSentence, on_delete=models.PROTECT, related_name="translations")
    language = models.ForeignKey(Language, on_delete=models.PROTECT, related_name="translations")

    text = models.TextField()
    text_hash = models.CharField(max_length=64, editable=False)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RAW)

    data_source = models.ForeignKey(
        DataSource, null=True, blank=True, on_delete=models.SET_NULL, related_name="translations"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "language", "text_hash"],
                name="uniq_trans_source_lang_hash",
            )
        ]
        indexes = [
            models.Index(fields=["language", "status"], name="trans_lang_status_idx"),
        ]

    def save(self, *args, **kwargs):
        self.text = normalize_text(self.text)
        self.text_hash = text_digest(translation_key(self.text))
        fields = kwargs.get("update_fields")
        if fields is not None and "text" in fields:
            kwargs["update_fields"] = set(fields) | {"text_hash"}
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.language.code}: {self.text[:60]}"


# ============================================================
# 7. LECONS
# ============================================================

class Lesson(models.Model):

    language = models.ForeignKey(Language, on_delete=models.PROTECT, related_name="lessons")
    theme = models.ForeignKey(Theme, on_delete=models.PROTECT, related_name="lessons")

    title = models.CharField(max_length=200)
    level = models.PositiveSmallIntegerField(default=1)
    position = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Tri explicite : trier sur une clé étrangère reprendrait le tri
        # du modèle lié et ajouterait des jointures à chaque requête.
        ordering = ["language__code", "theme__position", "position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["language", "theme", "position"],
                name="uniq_lesson_lang_theme_pos",
            )
        ]

    def __str__(self):
        return self.title


# ============================================================
# 8. EXERCICES
# ============================================================

class Exercise(models.Model):

    class ExerciseType(models.TextChoices):
        VOCAB = "vocab", "Vocabulaire"
        MCQ = "mcq", "QCM"
        BUILD = "build", "Construction de phrase"
        TRANSLATE = "translate", "Traduction"

    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="exercises")
    translation = models.ForeignKey(Translation, on_delete=models.PROTECT, related_name="exercises")

    exercise_type = models.CharField(max_length=20, choices=ExerciseType.choices)

    # Pas de valeur par défaut : deux exercices à 0 violeraient l'unicité.
    position = models.PositiveIntegerField()

    class Meta:
        ordering = ["lesson_id", "position"]
        constraints = [
            models.UniqueConstraint(fields=["lesson", "position"], name="uniq_exercise_lesson_pos")
        ]

    def clean(self):
        super().clean()
        if self.lesson_id and self.translation_id:
            lesson = self.lesson
            translation = self.translation

            if lesson.language_id != translation.language_id:
                raise ValidationError({
                    "translation": "La langue de la traduction doit correspondre à celle de la leçon."
                })
            if lesson.theme_id != translation.source.theme_id:
                raise ValidationError({
                    "translation": "Le thème de la phrase source doit correspondre au thème de la leçon."
                })
            if lesson.is_published and translation.status != Translation.Status.VALIDATED:
                raise ValidationError({
                    "translation": "Une leçon publiée doit utiliser une traduction validée."
                })

    def __str__(self):
        return f"{self.lesson.title} - Exercice {self.position}"


# ============================================================
# 9. PROGRESSION PAR LECON
# ============================================================

class UserProgress(models.Model):

    class Status(models.TextChoices):
        NOT_STARTED = "not_started", "Non commencée"
        IN_PROGRESS = "in_progress", "En cours"
        COMPLETED = "completed", "Terminée"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="progress")
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="user_progress")

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.IN_PROGRESS)
    best_score = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "lesson"], name="uniq_progress_user_lesson")
        ]

    def __str__(self):
        return f"{self.user} - {self.lesson.title}"


# ============================================================
# 10. TENTATIVES
# ============================================================
# `translation` est obligatoire : il permet de suivre la réussite PAR MOT,
# y compris en exercice libre (sans leçon). `exercise` est facultatif.

class Attempt(models.Model):

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="attempts")

    translation = models.ForeignKey(Translation, on_delete=models.PROTECT, related_name="attempts")

    exercise = models.ForeignKey(
        Exercise, null=True, blank=True, on_delete=models.SET_NULL, related_name="attempts"
    )

    answer = models.TextField(blank=True)

    # NULL = réponse pas encore évaluée.
    is_correct = models.BooleanField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "created_at"], name="attempt_user_date_idx"),
            models.Index(fields=["user", "translation"], name="attempt_user_trans_idx"),
        ]

    def clean(self):
        super().clean()
        if self.exercise_id and self.translation_id:
            if self.exercise.translation_id != self.translation_id:
                raise ValidationError({
                    "translation": "La traduction doit être celle de l'exercice."
                })

    def save(self, *args, **kwargs):
        if self.exercise_id and not self.translation_id:
            self.translation_id = self.exercise.translation_id
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Tentative de {self.user}"


# ============================================================
# 11. REPETITION ESPACEE (Leitner) — une carte par élève et par mot
# ============================================================

LEITNER_INTERVALS = {1: 1, 2: 2, 3: 4, 4: 8, 5: 16}  # boîte -> jours avant revue


class ReviewCard(models.Model):

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="review_cards")
    translation = models.ForeignKey(Translation, on_delete=models.CASCADE, related_name="review_cards")

    box = models.PositiveSmallIntegerField(
        default=1, validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    due_at = models.DateTimeField(default=timezone.now)
    reps = models.PositiveIntegerField(default=0)
    lapses = models.PositiveIntegerField(default=0)
    last_reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["due_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "translation"], name="uniq_card_user_translation")
        ]
        indexes = [
            models.Index(fields=["user", "due_at"], name="card_user_due_idx"),
        ]

    def review(self, correct):
        """Bonne réponse : boîte suivante. Erreur : retour à la boîte 1."""
        now = timezone.now()
        if correct:
            self.box = min(self.box + 1, 5)
            self.reps += 1
        else:
            self.box = 1
            self.lapses += 1
        self.due_at = now + timedelta(days=LEITNER_INTERVALS[self.box])
        self.last_reviewed_at = now
        self.save()

    def __str__(self):
        return f"{self.user} - boîte {self.box}"


# ============================================================
# 12. SIGNALEMENTS
# ============================================================

class Report(models.Model):

    class Status(models.TextChoices):
        PENDING = "pending", "En attente"
        IN_REVIEW = "in_review", "En cours de vérification"
        RESOLVED = "resolved", "Résolu"
        REJECTED = "rejected", "Rejeté"

    # SET_NULL : on garde le signalement même si le compte est supprimé.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="reports",
    )
    translation = models.ForeignKey(Translation, on_delete=models.PROTECT, related_name="reports")

    message = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"], name="report_status_date_idx"),
        ]

    def __str__(self):
        return f"Signalement #{self.pk}"


# ============================================================
# 13. BADGES
# ============================================================

class Badge(models.Model):

    name = models.CharField(max_length=100, unique=True)

    # Exemple : {"event": "lessons_completed", "count": 5}
    rule = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return self.name


class UserBadge(models.Model):

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="user_badges")
    badge = models.ForeignKey(Badge, on_delete=models.PROTECT, related_name="awards")

    awarded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-awarded_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "badge"], name="uniq_user_badge")
        ]

    def __str__(self):
        return f"{self.user} - {self.badge.name}"


# ============================================================
# 14. HISTORIQUE DES POINTS
# ============================================================

class PointEvent(models.Model):

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="point_events")

    attempt = models.ForeignKey(
        Attempt, null=True, blank=True, on_delete=models.SET_NULL, related_name="point_events"
    )

    # Valeurs négatives autorisées (corrections, retraits).
    points = models.IntegerField()
    reason = models.CharField(max_length=255)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "created_at"], name="points_user_date_idx"),
        ]

    def __str__(self):
        return f"{self.user}: {self.points} points"


# ============================================================
# 15. CONTRIBUTIONS (fonctionnalité future)
# ============================================================

class Contribution(models.Model):

    class Status(models.TextChoices):
        PENDING = "pending", "En attente"
        APPROVED = "approved", "Approuvée"
        REJECTED = "rejected", "Rejetée"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="contributions")
    language = models.ForeignKey(Language, on_delete=models.PROTECT, related_name="contributions")

    source = models.ForeignKey(
        SourceSentence, null=True, blank=True, on_delete=models.SET_NULL, related_name="contributions"
    )

    proposed_text = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)

    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="reviewed_contributions",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"], name="contrib_status_date_idx"),
        ]

    def clean(self):
        super().clean()
        if self.user_id and self.reviewer_id and self.user_id == self.reviewer_id:
            raise ValidationError({
                "reviewer": "Un utilisateur ne peut pas valider sa propre contribution."
            })
        if self.status != self.Status.PENDING and not self.reviewer_id:
            raise ValidationError({
                "reviewer": "Un validateur est obligatoire pour traiter une contribution."
            })

    def __str__(self):
        return f"Contribution #{self.pk} - {self.status}"
