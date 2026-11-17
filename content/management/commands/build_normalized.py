"""
Copie content_master_phrase -> tables normalisées.

    python manage.py build_normalized --dry-run     # simulation (rien n'est écrit)
    python manage.py build_normalized               # exécution réelle

- Ne modifie jamais content_master_phrase.
- Relançable sans risque : les doublons sont ignorés (empreintes + contraintes uniques).
- Seules les lignes AVEC texte arabe entrent (l'arabe est le pivot) ; c'est déjà
  la règle de lesson_queryset. Les autres restent dans content_master_phrase.
"""
from collections import Counter

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from ...models import (
    DataSource, Language, Level, MasterPhrase, Profile, SourceSentence, Theme,
    Translation, arabic_key, estimate_difficulty, estimate_unit_type,
    normalize_text, text_digest, translation_key,
)

DEFAULT_THEME = "Divers"

# (code, nom, écriture, sens) — à ajuster dans l'admin si besoin.
SEED_LANGUAGES = [
    ("mey", "Hassaniya", Language.Script.ARABIC, Language.Direction.RTL),
    ("fuc", "Pulaar", Language.Script.LATIN, Language.Direction.LTR),
    ("snk", "Soninke", Language.Script.LATIN, Language.Direction.LTR),
    ("wol", "Wolof", Language.Script.LATIN, Language.Direction.LTR),
    ("fra", "Français", Language.Script.LATIN, Language.Direction.LTR),
    ("eng", "English", Language.Script.LATIN, Language.Direction.LTR),
]


class Command(BaseCommand):
    help = "Copie content_master_phrase vers Language/Theme/SourceSentence/Translation/DataSource."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Simule puis annule tout.")
        parser.add_argument("--batch-size", type=int, default=2000)

    def handle(self, *args, **opts):
        batch = opts["batch_size"]
        with transaction.atomic():
            stats = self.run(batch)
            if opts["dry_run"]:
                transaction.set_rollback(True)

        self.stdout.write(self.style.SUCCESS("\n=== Résumé ==="))
        for key, value in stats.items():
            self.stdout.write(f"{key:<38} {value}")
        if opts["dry_run"]:
            self.stdout.write(self.style.WARNING("\nSIMULATION : aucune donnée n'a été écrite."))

    # ------------------------------------------------------------------
    def run(self, batch):
        stats = Counter()
        stats["lignes dans content_master_phrase"] = MasterPhrase.objects.count()

        # 0. profils pour les comptes déjà existants
        for user in get_user_model().objects.filter(profile__isnull=True):
            Profile.objects.create(user=user)

        # 1. langues
        langs = {}
        for code, name, script, direction in SEED_LANGUAGES:
            obj, _ = Language.objects.get_or_create(
                code=code, defaults={"name": name, "script": script, "direction": direction}
            )
            langs[code] = obj

        themes = {t.name.casefold(): t for t in Theme.objects.all()}
        data_sources = {(d.name, d.url): d.id for d in DataSource.objects.all()}
        rows = MasterPhrase.objects.exclude(text_arabic="").exclude(text_native="").order_by("id")

        # 2. phrases sources (une par arabe distinct)
        sources_before = SourceSentence.objects.count()
        known = set(SourceSentence.objects.values_list("text_hash", flat=True))
        new_sources = {}
        for row in rows.iterator(chunk_size=batch):
            arabic = normalize_text(row.text_arabic)
            if not arabic:
                continue
            digest = text_digest(arabic_key(arabic))
            if digest in known or digest in new_sources:
                continue
            words = len(arabic.split())
            new_sources[digest] = SourceSentence(
                arabic_text=arabic,
                text_hash=digest,
                theme=self.get_theme(row.category, themes),
                unit_type=row.level if row.level in Level.values else estimate_unit_type(words),
                word_count=words,
                difficulty=estimate_difficulty(words),
            )
        SourceSentence.objects.bulk_create(new_sources.values(), batch_size=batch, ignore_conflicts=True)
        source_ids = dict(SourceSentence.objects.values_list("text_hash", "id"))
        stats["phrases sources créées"] = SourceSentence.objects.count() - sources_before

        # 3. traductions : langue native + français + anglais
        trans_before = Translation.objects.count()
        existing = set(Translation.objects.values_list("source_id", "language_id", "text_hash"))
        pending = {}

        def flush():
            Translation.objects.bulk_create(pending.values(), batch_size=batch, ignore_conflicts=True)
            existing.update(pending.keys())
            pending.clear()

        for row in rows.iterator(chunk_size=batch):
            arabic = normalize_text(row.text_arabic)
            source_id = source_ids.get(text_digest(arabic_key(arabic))) if arabic else None
            if source_id is None:
                continue
            native = langs.get(row.language_code)
            if native is None:
                stats["lignes ignorées (langue inconnue)"] += 1
                continue

            status = Translation.Status.VALIDATED if row.is_lesson_ready else Translation.Status.RAW
            ds_id = self.get_data_source(row, data_sources)

            for lang, raw in ((native, row.text_native), (langs["fra"], row.text_french), (langs["eng"], row.text_english)):
                text = normalize_text(raw)
                if not text:
                    continue
                key = (source_id, lang.id, text_digest(translation_key(text)))
                if key in existing:
                    continue
                current = pending.get(key)
                if current is None:
                    pending[key] = Translation(
                        source_id=source_id, language=lang, text=text, text_hash=key[2],
                        status=status, data_source_id=ds_id,
                    )
                elif status == Translation.Status.VALIDATED:
                    current.status = status
            if len(pending) >= batch:
                flush()
        flush()

        stats["traductions créées"] = Translation.objects.count() - trans_before
        for code in ("mey", "fuc", "snk", "wol", "fra", "eng"):
            stats[f"  traductions {code} (total)"] = Translation.objects.filter(language=langs[code]).count()
        stats["lignes sans arabe (restent en brut)"] = MasterPhrase.objects.filter(text_arabic="").count()
        return stats

    # ------------------------------------------------------------------
    @staticmethod
    def get_theme(category, themes):
        name = normalize_text(category) or DEFAULT_THEME
        key = name.casefold()
        if key not in themes:
            themes[key] = Theme.objects.create(name=name[:100], position=len(themes))
        return themes[key]

    @staticmethod
    def get_data_source(row, cache):
        name = normalize_text(row.source_name)
        url = normalize_text(row.source_url)
        if not name and not url:
            return None
        name = (name or url)[:255]
        url = url[:1000]
        key = (name, url)
        if key not in cache:
            obj, _ = DataSource.objects.get_or_create(name=name, url=url)
            cache[key] = obj.id
        return cache[key]
