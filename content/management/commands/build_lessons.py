"""
Génère des leçons QCM (non publiées) à partir des traductions VALIDÉES.

    python manage.py build_lessons --language wol --size 10
    python manage.py build_lessons --dry-run

- Une leçon = un thème + une langue ; les phrases faciles viennent en premier.
- Une traduction déjà utilisée dans un exercice n'est pas réutilisée (relançable).
- Les leçons restent non publiées : publiez-les depuis l'admin (action « Publier »).
"""
from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from ...models import Exercise, Language, Lesson, Theme, Translation

NATIVE_CODES = ("mey", "fuc", "snk", "wol")


class Command(BaseCommand):
    help = "Crée des leçons QCM non publiées à partir des traductions validées."

    def add_arguments(self, parser):
        parser.add_argument("--language", choices=NATIVE_CODES, help="Une seule langue (sinon les 4).")
        parser.add_argument("--size", type=int, default=10, help="Exercices par leçon (défaut 10).")
        parser.add_argument("--min-size", type=int, default=4, help="Minimum pour garder une dernière leçon incomplète (un QCM exige 4 choix).")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        size, min_size = opts["size"], opts["min_size"]
        if size < min_size:
            raise CommandError("--size doit être supérieur ou égal à --min-size.")

        codes = [opts["language"]] if opts["language"] else NATIVE_CODES
        languages = list(Language.objects.filter(code__in=codes))
        if not languages:
            raise CommandError("Aucune langue en base : lancez d'abord build_normalized.")

        stats = Counter()
        with transaction.atomic():
            for lang in languages:
                for theme in Theme.objects.all():
                    self.build_for(lang, theme, size, min_size, stats)
            if opts["dry_run"]:
                transaction.set_rollback(True)

        self.stdout.write(self.style.SUCCESS("\n=== Résumé ==="))
        for key, value in stats.items():
            self.stdout.write(f"{key:<32} {value}")
        if opts["dry_run"]:
            self.stdout.write(self.style.WARNING("\nSIMULATION : rien n'a été écrit."))

    def build_for(self, lang, theme, size, min_size, stats):
        todo = list(
            Translation.objects
            .filter(language=lang, status=Translation.Status.VALIDATED, source__theme=theme)
            .exclude(exercises__isnull=False)
            .select_related("source")
            .order_by("source__difficulty", "source_id")
        )
        if len(todo) < min_size:
            stats["thèmes ignorés (trop peu de phrases)"] += 1
            return

        position = Lesson.objects.filter(language=lang, theme=theme).count()
        for start in range(0, len(todo), size):
            chunk = todo[start:start + size]
            if len(chunk) < min_size:
                stats["phrases laissées de côté"] += len(chunk)
                break
            position += 1
            lesson = Lesson.objects.create(
                language=lang, theme=theme,
                title=f"{theme.name} {position}",
                level=max(t.source.difficulty for t in chunk),
                position=position, is_published=False,
            )
            Exercise.objects.bulk_create([
                Exercise(lesson=lesson, translation=t, exercise_type=Exercise.ExerciseType.MCQ, position=i)
                for i, t in enumerate(chunk, start=1)
            ])
            stats["leçons créées"] += 1
            stats["exercices créés"] += len(chunk)
