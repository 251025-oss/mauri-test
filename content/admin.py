"""apps/content/admin.py — nécessite Django 3.2+ (décorateurs admin.display / admin.action)."""
from django.contrib import admin
from django.utils import timezone

from .models import (
    Attempt, Badge, Contribution, DataSource, Exercise, Language, Lesson,
    MasterPhrase, PointEvent, Profile, Report, ReviewCard, SourceSentence,
    Theme, Translation, UserBadge, UserProgress,
)


def _short(text, n=60):
    text = text or ""
    return text if len(text) <= n else text[:n] + "…"


# ------------------------------------------------------------ table brute
@admin.register(MasterPhrase)
class MasterPhraseAdmin(admin.ModelAdmin):
    list_display = ("master_id", "language_code", "level", "category", "native_short", "is_lesson_ready")
    list_filter = ("language_code", "level", "is_lesson_ready", "category")
    search_fields = ("master_id", "text_native", "text_arabic", "text_french", "text_english")
    list_editable = ("is_lesson_ready",)
    list_per_page = 50

    @admin.display(description="Texte natif")
    def native_short(self, obj):
        return _short(obj.text_native)


# ------------------------------------------------------------ référentiels
@admin.register(Language)
class LanguageAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "script", "direction")
    search_fields = ("code", "name")


@admin.register(Theme)
class ThemeAdmin(admin.ModelAdmin):
    list_display = ("name", "position")
    list_editable = ("position",)
    search_fields = ("name",)


@admin.register(DataSource)
class DataSourceAdmin(admin.ModelAdmin):
    list_display = ("name", "url", "license")
    search_fields = ("name", "url")


# ------------------------------------------------------------ contenu
class TranslationInline(admin.TabularInline):
    model = Translation
    extra = 0
    fields = ("language", "text", "status", "data_source")
    raw_id_fields = ("data_source",)


@admin.register(SourceSentence)
class SourceSentenceAdmin(admin.ModelAdmin):
    list_display = ("id", "arabic_short", "theme", "unit_type", "word_count", "difficulty")
    list_filter = ("theme", "unit_type", "difficulty")
    search_fields = ("arabic_text",)
    list_select_related = ("theme",)
    inlines = [TranslationInline]

    @admin.display(description="Texte arabe")
    def arabic_short(self, obj):
        return _short(obj.arabic_text)


@admin.register(Translation)
class TranslationAdmin(admin.ModelAdmin):
    list_display = ("id", "language", "text_short", "status", "data_source", "updated_at")
    list_filter = ("language", "status")
    search_fields = ("text", "source__arabic_text")
    list_select_related = ("language", "data_source")
    raw_id_fields = ("source", "data_source")
    actions = ["mark_validated", "mark_flagged", "mark_raw"]

    @admin.display(description="Texte")
    def text_short(self, obj):
        return _short(obj.text)

    def _set_status(self, request, queryset, status, label):
        # update() ne déclenche pas auto_now : on renseigne updated_at nous-mêmes.
        n = queryset.update(status=status, updated_at=timezone.now())
        self.message_user(request, f"{n} traduction(s) marquée(s) « {label} ».")

    @admin.action(description="Marquer comme validée")
    def mark_validated(self, request, queryset):
        self._set_status(request, queryset, Translation.Status.VALIDATED, "validée")

    @admin.action(description="Marquer comme signalée")
    def mark_flagged(self, request, queryset):
        self._set_status(request, queryset, Translation.Status.FLAGGED, "signalée")

    @admin.action(description="Remettre en brute")
    def mark_raw(self, request, queryset):
        self._set_status(request, queryset, Translation.Status.RAW, "brute")


# ------------------------------------------------------------ leçons
class ExerciseInline(admin.TabularInline):
    model = Exercise
    extra = 0
    fields = ("position", "exercise_type", "translation")
    raw_id_fields = ("translation",)


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ("title", "language", "theme", "level", "position", "is_published")
    list_filter = ("language", "theme", "is_published", "level")
    search_fields = ("title",)
    list_select_related = ("language", "theme")
    inlines = [ExerciseInline]
    actions = ["publish_lessons", "unpublish_lessons"]

    @admin.action(description="Publier (si toutes les traductions sont validées)")
    def publish_lessons(self, request, queryset):
        done, refused = 0, 0
        for lesson in queryset.prefetch_related("exercises__translation"):
            exercises = list(lesson.exercises.all())
            if exercises and all(e.translation.status == Translation.Status.VALIDATED for e in exercises):
                lesson.is_published = True
                lesson.save(update_fields=["is_published", "updated_at"])
                done += 1
            else:
                refused += 1
        self.message_user(request, f"{done} leçon(s) publiée(s), {refused} refusée(s) (vide ou traduction non validée).")

    @admin.action(description="Dépublier")
    def unpublish_lessons(self, request, queryset):
        n = queryset.update(is_published=False, updated_at=timezone.now())
        self.message_user(request, f"{n} leçon(s) dépubliée(s).")


@admin.register(Exercise)
class ExerciseAdmin(admin.ModelAdmin):
    list_display = ("lesson", "position", "exercise_type", "translation")
    list_filter = ("exercise_type", "lesson__language")
    list_select_related = ("lesson", "translation")
    raw_id_fields = ("lesson", "translation")


# ------------------------------------------------------------ suivi élèves
@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "xp_total")
    list_filter = ("role",)
    search_fields = ("user__username", "user__email")
    raw_id_fields = ("user",)


@admin.register(UserProgress)
class UserProgressAdmin(admin.ModelAdmin):
    list_display = ("user", "lesson", "status", "best_score", "updated_at")
    list_filter = ("status",)
    raw_id_fields = ("user", "lesson")


@admin.register(Attempt)
class AttemptAdmin(admin.ModelAdmin):
    list_display = ("user", "translation", "is_correct", "created_at")
    list_filter = ("is_correct",)
    raw_id_fields = ("user", "translation", "exercise")


@admin.register(ReviewCard)
class ReviewCardAdmin(admin.ModelAdmin):
    list_display = ("user", "translation", "box", "due_at", "reps", "lapses")
    list_filter = ("box",)
    raw_id_fields = ("user", "translation")


# ------------------------------------------------------------ communauté
@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("id", "translation", "user", "status", "created_at")
    list_filter = ("status",)
    raw_id_fields = ("user", "translation")


@admin.register(Contribution)
class ContributionAdmin(admin.ModelAdmin):
    list_display = ("id", "language", "user", "status", "reviewer", "created_at")
    list_filter = ("status", "language")
    raw_id_fields = ("user", "reviewer", "source")


# ------------------------------------------------------------ gamification
@admin.register(Badge)
class BadgeAdmin(admin.ModelAdmin):
    list_display = ("name",)


@admin.register(UserBadge)
class UserBadgeAdmin(admin.ModelAdmin):
    list_display = ("user", "badge", "awarded_at")
    raw_id_fields = ("user",)


@admin.register(PointEvent)
class PointEventAdmin(admin.ModelAdmin):
    list_display = ("user", "points", "reason", "created_at")
    raw_id_fields = ("user", "attempt")
