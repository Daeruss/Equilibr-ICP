import json
import os
import sqlite3
import subprocess
import sys
from datetime import date, datetime, time
from pathlib import Path

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, models
from django.db.models import CompositePrimaryKey

from equilibrium.models import SavedCalculation
from icp_stat.models import ParsedPoint
from ivtanthermo.models import (
    BibAuthorRef,
    Bibliography,
    Bibtype,
    DataBibRef,
    Datainfo,
    GibbsCoef,
    Molecule,
    MoleculeAtomRef,
    MoleculeProp,
    Substance,
    SubstanceCharge,
    SubstanceName,
    Thermo,
)


TEST_SUBSET_LABELS = [
    "e(-g)",
    "C(c;graphite)",
    "C(g)",
    "CO(g)",
    "CO2(g)",
    "C2O(g)",
    "O(g)",
    "O(-g)",
    "O(+g)",
    "O2(g)",
    "O2(+g)",
    "H(g)",
    "H(-g)",
    "H(+g)",
    "H2(g)",
    "H2(+g)",
    "H3(+g)",
    "OH(g)",
    "OH(+g)",
    "H2O(g)",
    "H2O(+g)",
]


def _is_simple_model(model):
    return (
        isinstance(model, type)
        and issubclass(model, models.Model)
        and model is not models.Model
        and not isinstance(model._meta.pk, CompositePrimaryKey)
    )


def _sqlite_type(field):
    if isinstance(field, (models.ForeignKey, models.OneToOneField)):
        return _sqlite_type(field.target_field)
    if isinstance(
        field,
        (
            models.AutoField,
            models.BigAutoField,
            models.IntegerField,
            models.SmallIntegerField,
            models.BigIntegerField,
            models.PositiveIntegerField,
            models.PositiveSmallIntegerField,
            models.BooleanField,
        ),
    ):
        return "INTEGER"
    if isinstance(field, (models.FloatField, models.DecimalField)):
        return "REAL"
    return "TEXT"


def _serialize_value(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value


class Command(BaseCommand):
    help = "Build SQLite catalog databases from the current source database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            default="db.sqlite3",
            help="Target SQLite file path relative to the project root.",
        )
        parser.add_argument(
            "--subset",
            choices=("full", "test"),
            default="full",
            help="Copy the full catalog or a short test subset.",
        )
        parser.add_argument(
            "--labels",
            nargs="*",
            default=None,
            help="Explicit substance labels for subset mode. Overrides the built-in test preset.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite the target SQLite file if it already exists.",
        )

    def handle(self, *args, **options):
        self.copy_warnings = []
        output_path = (Path.cwd() / options["output"]).resolve()
        subset = options["subset"]
        labels = options["labels"] or (TEST_SUBSET_LABELS if subset == "test" else None)

        self._validate_source_backend(output_path)
        self._bootstrap_sqlite_database(output_path, force=options["force"])

        subset_context = self._build_subset_context(labels) if labels else None
        with sqlite3.connect(output_path) as sqlite_connection:
            sqlite_connection.row_factory = sqlite3.Row
            self._create_unmanaged_ivtanthermo_tables(sqlite_connection)
            copied_rows = self._copy_all_data(sqlite_connection, subset_context=subset_context)

        summary = ", ".join(f"{table}={count}" for table, count in copied_rows.items() if count)
        if not summary:
            summary = "no rows copied"
        self.stdout.write(
            self.style.SUCCESS(
                f"SQLite database prepared: {output_path}\n"
                f"mode={subset}, source_vendor={connection.vendor}\n"
                f"{summary}"
            )
        )
        if subset_context and subset_context["missing_labels"]:
            self.stdout.write(
                self.style.WARNING(
                    "Missing subset labels: " + ", ".join(sorted(subset_context["missing_labels"]))
                )
            )
        for warning in self.copy_warnings:
            self.stdout.write(self.style.WARNING(warning))

    def _validate_source_backend(self, output_path: Path):
        source_name = connection.settings_dict.get("NAME")
        if connection.vendor == "sqlite":
            source_path = Path(str(source_name)).resolve()
            if source_path == output_path:
                raise CommandError(
                    "Source and target SQLite database paths match. Use USE_POSTGRES=1 or another --output path."
                )

    def _bootstrap_sqlite_database(self, output_path: Path, *, force: bool):
        if output_path.exists():
            if not force:
                raise CommandError(f"Target SQLite file already exists: {output_path}. Use --force to overwrite it.")
            output_path.unlink()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env.pop("USE_POSTGRES", None)
        env["USE_SQLITE"] = "1"
        env["SQLITE_NAME"] = str(output_path)
        command = [sys.executable, "manage.py", "migrate", "--noinput"]
        completed = subprocess.run(
            command,
            cwd=Path.cwd(),
            env=env,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise CommandError(
                "Failed to bootstrap target SQLite database with migrations:\n"
                f"{completed.stdout}\n{completed.stderr}"
            )

    def _build_subset_context(self, labels):
        label_set = {label.strip() for label in labels if label and label.strip()}
        substances = list(
            Substance.objects.filter(label__in=label_set).select_related("molecule", "phase")
        )
        found_labels = {substance.label for substance in substances}
        substance_ids = {substance.id for substance in substances}
        molecule_ids = {substance.molecule_id for substance in substances}
        phase_ids = {substance.phase_id for substance in substances}

        thermo_rows = list(Thermo.objects.filter(substance_id__in=substance_ids))
        thermo_ids = {row.id for row in thermo_rows}
        datainfo_ids = {row.datainfo_id for row in thermo_rows}

        gibbs_rows = list(GibbsCoef.objects.filter(thermo_id__in=thermo_ids))
        approx_ids = {row.approx_id for row in gibbs_rows}
        cond_phase_ids = {row.cond_phase_id for row in gibbs_rows if row.cond_phase_id}

        molecule_prop_rows = list(MoleculeProp.objects.filter(molecule_id__in=molecule_ids))
        datainfo_ids.update(row.datainfo_id for row in molecule_prop_rows)

        atom_refs = list(MoleculeAtomRef.objects.filter(molecule_id__in=molecule_ids))
        atom_ids = {row.atom_id for row in atom_refs}

        bib_refs = list(DataBibRef.objects.filter(datainfo_id__in=datainfo_ids))
        bib_ids = {row.bib_id for row in bib_refs}

        bibliography_rows = list(Bibliography.objects.filter(id__in=bib_ids))
        bibtype_ids = {row.bibtype_id for row in bibliography_rows}

        author_refs = list(BibAuthorRef.objects.filter(bib_id__in=bib_ids))
        author_ids = {row.author_id for row in author_refs}

        return {
            "substance_ids": substance_ids,
            "molecule_ids": molecule_ids,
            "phase_ids": phase_ids,
            "thermo_ids": thermo_ids,
            "datainfo_ids": datainfo_ids,
            "approx_ids": approx_ids,
            "cond_phase_ids": cond_phase_ids,
            "atom_ids": atom_ids,
            "bib_ids": bib_ids,
            "bibtype_ids": bibtype_ids,
            "author_ids": author_ids,
            "missing_labels": label_set - found_labels,
        }

    def _create_unmanaged_ivtanthermo_tables(self, sqlite_connection):
        models_to_create = [
            model
            for model in apps.get_app_config("ivtanthermo").get_models()
            if _is_simple_model(model) and not model._meta.managed
        ]
        for model in models_to_create:
            columns = []
            for field in model._meta.concrete_fields:
                parts = [f'"{field.column}"', _sqlite_type(field)]
                if field.primary_key:
                    parts.append("PRIMARY KEY")
                columns.append(" ".join(parts))
            ddl = f'CREATE TABLE IF NOT EXISTS "{model._meta.db_table}" ({", ".join(columns)})'
            sqlite_connection.execute(ddl)
        sqlite_connection.commit()

    def _copy_all_data(self, sqlite_connection, *, subset_context):
        copied_rows = {}

        ivtanthermo_models = [
            model
            for model in apps.get_app_config("ivtanthermo").get_models()
            if _is_simple_model(model)
        ]
        for model in ivtanthermo_models:
            queryset = self._subset_queryset(model, subset_context)
            try:
                copied_rows[model._meta.db_table] = self._copy_queryset(sqlite_connection, model, queryset)
            except Exception as exc:
                copied_rows[model._meta.db_table] = 0
                self.copy_warnings.append(f"Skipped {model._meta.db_table}: {exc}")

        for model in (SavedCalculation, ParsedPoint):
            try:
                copied_rows[model._meta.db_table] = self._copy_queryset(
                    sqlite_connection,
                    model,
                    model.objects.all(),
                )
            except Exception as exc:
                copied_rows[model._meta.db_table] = 0
                self.copy_warnings.append(f"Skipped {model._meta.db_table}: {exc}")
        return copied_rows

    def _subset_queryset(self, model, subset_context):
        queryset = model.objects.all().order_by(model._meta.pk.attname)
        if not subset_context:
            return queryset

        filters = {
            "Substance": ("id__in", subset_context["substance_ids"]),
            "SubstanceCharge": ("substance_id__in", subset_context["substance_ids"]),
            "SubstanceName": ("substance_id__in", subset_context["substance_ids"]),
            "Thermo": ("substance_id__in", subset_context["substance_ids"]),
            "GibbsCoef": ("thermo_id__in", subset_context["thermo_ids"]),
            "Molecule": ("id__in", subset_context["molecule_ids"]),
            "MoleculeProp": ("molecule_id__in", subset_context["molecule_ids"]),
            "MoleculeAtomRef": ("molecule_id__in", subset_context["molecule_ids"]),
            "Phase": ("id__in", subset_context["phase_ids"]),
            "Datainfo": ("id__in", subset_context["datainfo_ids"]),
            "DataBibRef": ("datainfo_id__in", subset_context["datainfo_ids"]),
            "Bibliography": ("id__in", subset_context["bib_ids"]),
            "BibAuthorRef": ("bib_id__in", subset_context["bib_ids"]),
            "Author": ("id__in", subset_context["author_ids"]),
            "Bibtype": ("id__in", subset_context["bibtype_ids"]),
            "Approx": ("id__in", subset_context["approx_ids"]),
            "CondPhase": ("id__in", subset_context["cond_phase_ids"]),
            "Atom": ("id__in", subset_context["atom_ids"]),
        }
        filter_spec = filters.get(model.__name__)
        if filter_spec is None:
            return queryset.none() if model._meta.app_label == "ivtanthermo" and not model._meta.managed else queryset
        lookup, ids = filter_spec
        if not ids:
            return queryset.none()
        return queryset.filter(**{lookup: ids})

    def _copy_queryset(self, sqlite_connection, model, queryset):
        table_name = model._meta.db_table
        fields = list(model._meta.concrete_fields)
        columns = [field.column for field in fields]
        attnames = [field.attname for field in fields]
        placeholders = ", ".join("?" for _ in columns)
        sql = (
            f'DELETE FROM "{table_name}";'
        )
        sqlite_connection.execute(sql)
        quoted_columns = ", ".join(f'"{column}"' for column in columns)
        insert_sql = f'INSERT INTO "{table_name}" ({quoted_columns}) VALUES ({placeholders})'

        total = 0
        batch = []
        for row in queryset.values_list(*attnames).iterator(chunk_size=1000):
            batch.append(tuple(_serialize_value(value) for value in row))
            if len(batch) >= 1000:
                sqlite_connection.executemany(insert_sql, batch)
                total += len(batch)
                batch.clear()
        if batch:
            sqlite_connection.executemany(insert_sql, batch)
            total += len(batch)
        sqlite_connection.commit()
        return total
