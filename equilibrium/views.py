import csv
import json
from io import StringIO
from types import SimpleNamespace

from django.db import OperationalError, ProgrammingError
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
import plotly.graph_objects as go
from plotly.offline import get_plotlyjs, plot

from ivtanthermo.models import Substance

from .forms import CustomSubstanceForm, DatabaseEquilibriumForm, EquilibriumInputForm
from .models import CustomSubstance, SavedCalculation
from .solver import (
    EXAMPLES,
    NUMERICAL_EPS,
    build_input_from_database,
    load_example_input,
    multiplier_rows,
    parse_feed_input,
    parse_equilibrium_input,
    phase_rows,
    result_rows,
    solve_equilibrium,
    temperature_points,
)


TEMPERATURE_COLORS = [
    "#38bdf8",
    "#22c55e",
    "#f59e0b",
    "#f97316",
    "#ef4444",
    "#a855f7",
    "#14b8a6",
    "#eab308",
    "#fb7185",
    "#60a5fa",
]

DISPLAY_AMOUNT_THRESHOLD = 1e-12


def database_substance_labels() -> list[str]:
    try:
        built_in_labels = list(Substance.objects.order_by("label").values_list("label", flat=True))
    except (OperationalError, ProgrammingError):
        built_in_labels = []
    custom_labels = list(
        CustomSubstance.objects.filter(is_active=True).order_by("label").values_list("label", flat=True)
    )
    return sorted(set(built_in_labels).union(custom_labels))


def recent_custom_substances(limit: int = 20) -> list[CustomSubstance]:
    return list(CustomSubstance.objects.filter(is_active=True).order_by("label")[:limit])


def recent_saved_calculations(limit: int = 12) -> list[SavedCalculation]:
    return list(SavedCalculation.objects.all()[:limit])


def default_database_initial() -> dict:
    return {
        "mode": "gibbs",
        "temperature_start": 2000.0,
        "temperature_end": 2000.0,
        "temperature_step": 100.0,
        "temperature_report": None,
        "pressure_mpa": 0.1,
        "feed_basis": "mole",
        "include_condensed": True,
        "include_ions": False,
        "feed_input": "C2O(g) 1.0",
    }


def default_custom_substance_initial() -> dict:
    return {
        "phase": "g",
        "molar_mass": 1.0,
        "dfh0": 0.0,
        "tmin": 200.0,
        "tmax": 10000.0,
        "element_counts_input": "X 1",
        "gibbs_coefficients_input": "0 0 0 0 0 0 0",
    }


def default_save_name(source: str, mode: str, example_name: str = "") -> str:
    timestamp = timezone.localtime().strftime("%Y-%m-%d %H:%M")
    source_label = "DB" if source == SavedCalculation.SOURCE_DATABASE else "Manual"
    detail = example_name or mode
    return f"{source_label} {detail} {timestamp}"


def manual_initial_from_example(selected_example: str) -> dict:
    if selected_example not in EXAMPLES:
        return {}

    parsed_example = load_example_input(selected_example)
    return {
        "example": selected_example,
        "mode": EXAMPLES[selected_example]["mode"],
        "raw_input": parsed_example.raw_text,
    }


def manual_initial_from_saved(saved_calculation: SavedCalculation) -> dict:
    return {
        "example": saved_calculation.example_name,
        "mode": saved_calculation.mode,
        "raw_input": saved_calculation.raw_input,
    }


def database_initial_from_saved(saved_calculation: SavedCalculation) -> dict:
    start = saved_calculation.temperature_start or saved_calculation.temperature or 2000.0
    end = saved_calculation.temperature_end or start
    step = saved_calculation.temperature_step or 100.0
    return {
        "mode": saved_calculation.mode,
        "temperature_start": start,
        "temperature_end": end,
        "temperature_step": step,
        "temperature_report": saved_calculation.temperature_report,
        "pressure_mpa": saved_calculation.pressure_mpa or 0.1,
        "feed_basis": getattr(saved_calculation, "feed_basis", "mole") or "mole",
        "include_condensed": saved_calculation.include_condensed,
        "include_ions": saved_calculation.include_ions,
        "feed_input": saved_calculation.feed_input,
    }


def run_manual_calculation(cleaned_data: dict):
    raw_input = (cleaned_data.get("raw_input") or "").strip()
    if raw_input:
        parsed = parse_equilibrium_input(raw_input)
    else:
        parsed = load_example_input(cleaned_data["example"])
    result = solve_equilibrium(parsed, mode=cleaned_data["mode"])
    return parsed, result


def run_database_point(cleaned_data: dict, temperature: float, feed_entries: list[tuple[str, float]] | None = None) -> dict:
    if feed_entries is None:
        feed_entries = parse_feed_input(cleaned_data["feed_input"])

    parsed = build_input_from_database(
        temperature=temperature,
        feed_entries=feed_entries,
        pressure_mpa=cleaned_data["pressure_mpa"],
        feed_basis=cleaned_data.get("feed_basis", "mole"),
        include_condensed=cleaned_data["include_condensed"],
        include_ions=cleaned_data["include_ions"],
    )
    result = solve_equilibrium(parsed, mode=cleaned_data["mode"])
    return {
        "temperature": temperature,
        "parsed": parsed,
        "result": result,
        "rows": result_rows(result),
        "phases": phase_rows(result),
        "multipliers": multiplier_rows(result),
    }


def run_database_series(cleaned_data: dict) -> list[dict]:
    feed_entries = parse_feed_input(cleaned_data["feed_input"])
    temperatures = temperature_points(
        cleaned_data["temperature_start"],
        cleaned_data["temperature_end"],
        cleaned_data["temperature_step"],
    )
    return [run_database_point(cleaned_data, temperature, feed_entries=feed_entries) for temperature in temperatures]


def result_context(snapshot: dict):
    return snapshot["rows"], snapshot["phases"], snapshot["multipliers"]


def build_concentration_rows(snapshot: dict) -> list[dict]:
    total_amount = max(float(snapshot["result"].species_amounts.sum()), NUMERICAL_EPS)
    rows = []
    for row in snapshot["rows"]:
        rows.append({**row, "mole_fraction": float(row["amount"]) / total_amount})
    return rows


def build_plot_html(figure: go.Figure) -> str:
    figure.update_layout(
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=56, r=20, t=28, b=48),
        font=dict(family="Arial, Helvetica, sans-serif"),
    )
    return plot(
        figure,
        output_type="div",
        include_plotlyjs=False,
        config={
            "responsive": True,
            "displaylogo": False,
            "modeBarButtonsToRemove": ["lasso2d", "select2d"],
        },
    )


def build_temperature_series_rows_data(snapshots: list[dict]) -> list[dict]:
    rows = []
    for snapshot in snapshots:
        total_amount = max(float(snapshot["result"].species_amounts.sum()), NUMERICAL_EPS)
        for species_name, amount in zip(snapshot["parsed"].species, snapshot["result"].species_amounts):
            if float(amount) < DISPLAY_AMOUNT_THRESHOLD:
                continue
            rows.append(
                {
                    "temperature": float(snapshot["temperature"]),
                    "species": species_name,
                    "amount": float(amount),
                    "mole_fraction": float(amount) / total_amount,
                }
            )
    return rows


def build_temperature_plot_from_series_rows(
    temperature_series_rows: list[dict],
    species_limit: int = 8,
) -> str | None:
    if not temperature_series_rows:
        return None

    temperatures = sorted({float(row["temperature"]) for row in temperature_series_rows})
    if len(temperatures) < 2:
        return None

    species_points: dict[str, list[dict]] = {}
    species_maxima: dict[str, float] = {}
    for row in temperature_series_rows:
        species_name = row["species"]
        species_points.setdefault(species_name, []).append(row)
        species_maxima[species_name] = max(species_maxima.get(species_name, 0.0), float(row["mole_fraction"]))

    selected_species = [
        species_name
        for species_name, _ in sorted(species_maxima.items(), key=lambda item: item[1], reverse=True)
        if species_maxima[species_name] > 1e-10
    ][:species_limit]
    if not selected_species:
        return None

    figure = go.Figure()
    for index, species_name in enumerate(selected_species):
        points = sorted(species_points[species_name], key=lambda item: float(item["temperature"]))
        figure.add_trace(
            go.Scatter(
                x=[float(point["temperature"]) for point in points],
                y=[float(point["mole_fraction"]) for point in points],
                mode="lines+markers",
                name=species_name,
                line=dict(color=TEMPERATURE_COLORS[index % len(TEMPERATURE_COLORS)], width=2.5),
                marker=dict(size=6),
                hovertemplate="T=%{x:.2f} K<br>x=%{y:.6f}<extra>%{fullData.name}</extra>",
            )
        )

    figure.update_layout(
        height=420,
        xaxis_title="Temperature, K",
        yaxis_title="Mole fraction",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    return build_plot_html(figure)


def build_temperature_plot(snapshots: list[dict], species_limit: int = 8) -> str | None:
    return build_temperature_plot_from_series_rows(
        build_temperature_series_rows_data(snapshots),
        species_limit=species_limit,
    )


def build_csv_text(header: list[str], rows: list[list]) -> str:
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


def build_csv_exports(
    temperature_series_rows: list[dict],
    concentration_rows: list[dict],
    phases: list[dict],
) -> list[dict]:
    exports = []

    if concentration_rows:
        exports.append(
            {
                "slug": "equilibrium-composition-csv",
                "filename": "equilibrium_composition.csv",
                "label": "РЎРєР°С‡Р°С‚СЊ СЃРѕСЃС‚Р°РІ",
                "content": build_csv_text(
                    ["index", "species", "amount_mol", "mole_fraction", "g_over_rt"],
                    [
                        [row["index"], row["species"], row["amount"], row["mole_fraction"], row["g_rt"]]
                        for row in concentration_rows
                    ],
                ),
            }
        )

    if phases:
        exports.append(
            {
                "slug": "equilibrium-phases-csv",
                "filename": "equilibrium_phases.csv",
                "label": "РЎРєР°С‡Р°С‚СЊ С„Р°Р·С‹",
                "content": build_csv_text(
                    ["phase_index", "start_index", "end_index", "amount_mol", "species"],
                    [
                        [row["phase_index"], row["start"], row["end"], row["amount"], ", ".join(row["species"])]
                        for row in phases
                    ],
                ),
            }
        )

    if temperature_series_rows:
        exports.append(
            {
                "slug": "equilibrium-temperature-series-csv",
                "filename": "equilibrium_temperature_series.csv",
                "label": "РЎРєР°С‡Р°С‚СЊ С‚РµРјРїРµСЂР°С‚СѓСЂРЅСѓСЋ СЃРµСЂРёСЋ",
                "content": build_csv_text(
                    ["temperature_k", "species", "amount_mol", "mole_fraction"],
                    [
                        [row["temperature"], row["species"], row["amount"], row["mole_fraction"]]
                        for row in temperature_series_rows
                    ],
                ),
            }
        )

    return exports


def build_temperature_rows(snapshots: list[dict]) -> list[dict]:
    rows = []
    for snapshot in snapshots:
        dominant_species = snapshot["rows"][0]["species"] if snapshot["rows"] else "-"
        rows.append(
            {
                "temperature": snapshot["temperature"],
                "objective": snapshot["result"].objective_value,
                "success": snapshot["result"].success,
                "dominant_species": dominant_species,
                "species_count": len(snapshot["rows"]),
                "mass_balance_residual": snapshot["result"].mass_balance_residual,
            }
        )
    return rows


def build_result_payload(
    *,
    source: str,
    parsed,
    result,
    rows: list[dict],
    phases: list[dict],
    multipliers: list[dict],
    concentration_rows: list[dict],
    temperature_table: list[dict],
    temperature_series_rows: list[dict],
    primary_temperature,
    current_temperature_start,
    current_temperature_end,
    current_temperature_report,
    current_pressure_mpa,
    current_feed_basis,
) -> dict:
    return {
        "version": 1,
        "source": source,
        "parsed": {
            "m": parsed.m,
            "k": parsed.k,
            "np": parsed.np,
            "trailing_lines": list(parsed.trailing_lines),
        } if parsed else None,
        "result": {
            "mode": result.mode,
            "objective_value": result.objective_value,
            "success": result.success,
            "status": result.status,
            "message": result.message,
            "iterations": result.iterations,
            "optimality": result.optimality,
            "mass_balance_residual": result.mass_balance_residual,
        } if result else None,
        "rows": rows,
        "phases": phases,
        "multipliers": multipliers,
        "concentration_rows": concentration_rows,
        "temperature_table": temperature_table,
        "temperature_series_rows": temperature_series_rows,
        "primary_temperature": primary_temperature,
        "current_temperature_start": current_temperature_start,
        "current_temperature_end": current_temperature_end,
        "current_temperature_report": current_temperature_report,
        "current_pressure_mpa": current_pressure_mpa,
        "current_feed_basis": current_feed_basis,
    }


def restore_saved_result_payload(payload: dict) -> dict:
    parsed_payload = payload.get("parsed") or {}
    result_payload = payload.get("result") or {}
    concentration_rows = payload.get("concentration_rows") or []
    phases = payload.get("phases") or []
    temperature_series_rows = payload.get("temperature_series_rows") or []
    return {
        "parsed": SimpleNamespace(
            m=parsed_payload.get("m"),
            k=parsed_payload.get("k"),
            np=parsed_payload.get("np"),
            trailing_lines=parsed_payload.get("trailing_lines", []),
        ) if parsed_payload else None,
        "result": SimpleNamespace(**result_payload) if result_payload else None,
        "rows": payload.get("rows") or [],
        "phases": phases,
        "multipliers": payload.get("multipliers") or [],
        "concentration_rows": concentration_rows,
        "temperature_table": payload.get("temperature_table") or [],
        "temperature_series_rows": temperature_series_rows,
        "temperature_plot_html": build_temperature_plot_from_series_rows(temperature_series_rows),
        "csv_exports": build_csv_exports(temperature_series_rows, concentration_rows, phases),
        "primary_temperature": payload.get("primary_temperature"),
        "current_temperature_start": payload.get("current_temperature_start"),
        "current_temperature_end": payload.get("current_temperature_end"),
        "current_temperature_report": payload.get("current_temperature_report"),
        "current_pressure_mpa": payload.get("current_pressure_mpa"),
        "current_feed_basis": payload.get("current_feed_basis", "mole"),
    }


def save_database_calculation(cleaned_data: dict, save_name: str, result_payload: dict | None = None) -> SavedCalculation:
    return SavedCalculation.objects.create(
        name=save_name,
        source=SavedCalculation.SOURCE_DATABASE,
        mode=cleaned_data["mode"],
        temperature=cleaned_data["temperature_start"],
        temperature_start=cleaned_data["temperature_start"],
        temperature_end=cleaned_data["temperature_end"],
        temperature_step=cleaned_data["temperature_step"],
        temperature_report=cleaned_data["temperature_report"],
        pressure_mpa=cleaned_data["pressure_mpa"],
        feed_basis=cleaned_data.get("feed_basis", "mole"),
        include_condensed=cleaned_data["include_condensed"],
        include_ions=cleaned_data["include_ions"],
        feed_input=cleaned_data["feed_input"],
        result_payload=result_payload,
    )


def save_manual_calculation(cleaned_data: dict, save_name: str, result_payload: dict | None = None) -> SavedCalculation:
    return SavedCalculation.objects.create(
        name=save_name,
        source=SavedCalculation.SOURCE_MANUAL,
        mode=cleaned_data["mode"],
        example_name=cleaned_data.get("example") or "",
        raw_input=cleaned_data.get("raw_input") or "",
        result_payload=result_payload,
    )


def apply_result_bundle(bundle: dict):
    parsed = bundle.get("parsed")
    result = bundle.get("result")
    rows = bundle.get("rows", [])
    phases = bundle.get("phases", [])
    multipliers = bundle.get("multipliers", [])
    concentration_rows = bundle.get("concentration_rows", [])
    temperature_series_rows = bundle.get("temperature_series_rows", [])
    temperature_table = bundle.get("temperature_table", [])
    temperature_plot_html = bundle.get("temperature_plot_html")
    if temperature_plot_html is None and temperature_series_rows:
        temperature_plot_html = build_temperature_plot_from_series_rows(temperature_series_rows)
    csv_exports = bundle.get("csv_exports")
    if csv_exports is None:
        csv_exports = build_csv_exports(temperature_series_rows, concentration_rows, phases)
    return {
        "parsed": parsed,
        "result": result,
        "rows": rows,
        "phases": phases,
        "multipliers": multipliers,
        "concentration_rows": concentration_rows,
        "temperature_series_rows": temperature_series_rows,
        "temperature_table": temperature_table,
        "temperature_plot_html": temperature_plot_html,
        "csv_exports": csv_exports,
        "primary_temperature": bundle.get("primary_temperature"),
        "current_temperature_start": bundle.get("current_temperature_start"),
        "current_temperature_end": bundle.get("current_temperature_end"),
        "current_temperature_report": bundle.get("current_temperature_report"),
        "current_pressure_mpa": bundle.get("current_pressure_mpa"),
        "current_feed_basis": bundle.get("current_feed_basis", "mole"),
    }


def equilibrium_calculator(request):
    selected_example = request.GET.get("example", "").strip()
    selected_saved = None
    save_message = None
    custom_substance_message = None

    initial_manual = manual_initial_from_example(selected_example)
    form = EquilibriumInputForm(initial=initial_manual)
    db_form = DatabaseEquilibriumForm(initial=default_database_initial())
    custom_substance_form = CustomSubstanceForm(initial=default_custom_substance_initial())

    parsed = None
    result = None
    rows = []
    phases = []
    multipliers = []
    concentration_rows = []
    temperature_series_rows = []
    temperature_plot_html = None
    plotly_js = ""
    temperature_table = []
    csv_exports = []
    report_temperature = None
    source = None
    result_payload = None

    current_temperature_start = default_database_initial()["temperature_start"]
    current_temperature_end = default_database_initial()["temperature_end"]
    current_temperature_report = None
    current_pressure_mpa = default_database_initial()["pressure_mpa"]
    current_feed_basis = default_database_initial()["feed_basis"]

    if request.method == "POST":
        action = request.POST.get("action", "calculate").strip()
        source = request.POST.get("source")

        if action == "create_custom_substance":
            custom_substance_form = CustomSubstanceForm(request.POST)
            if custom_substance_form.is_valid():
                custom_substance = custom_substance_form.save()
                custom_substance_message = f"Пользовательское вещество сохранено: {custom_substance.label}"
                custom_substance_form = CustomSubstanceForm(initial=default_custom_substance_initial())

        elif action == "delete_custom_substance":
            custom_substance_id = request.POST.get("custom_substance_id", "").strip()
            custom_substance = get_object_or_404(CustomSubstance, pk=custom_substance_id)
            custom_substance.is_active = False
            custom_substance.save(update_fields=["is_active", "updated_at"])
            custom_substance_message = f"Пользовательское вещество отключено: {custom_substance.label}"
            custom_substance_form = CustomSubstanceForm(initial=default_custom_substance_initial())

        elif action == "save_result":
            payload_raw = request.POST.get("result_payload", "").strip()
            if not payload_raw:
                save_message = "Result payload is empty."
            else:
                try:
                    result_payload = json.loads(payload_raw)
                except json.JSONDecodeError:
                    save_message = "Result payload is invalid."
                    result_payload = None
                if result_payload is None:
                    pass
                else:
                    restored = apply_result_bundle(restore_saved_result_payload(result_payload))
                    parsed = restored["parsed"]
                    result = restored["result"]
                    rows = restored["rows"]
                    phases = restored["phases"]
                    multipliers = restored["multipliers"]
                    concentration_rows = restored["concentration_rows"]
                    temperature_series_rows = restored["temperature_series_rows"]
                    temperature_table = restored["temperature_table"]
                    temperature_plot_html = restored["temperature_plot_html"]
                    csv_exports = restored["csv_exports"]
                    report_temperature = restored["primary_temperature"]
                    current_temperature_start = restored["current_temperature_start"]
                    current_temperature_end = restored["current_temperature_end"]
                    current_temperature_report = restored["current_temperature_report"]
                    current_pressure_mpa = restored["current_pressure_mpa"]
                    current_feed_basis = restored["current_feed_basis"]
                    source = result_payload.get("source") or source

                    if source == SavedCalculation.SOURCE_DATABASE:
                        cleaned_data = {
                            "mode": request.POST.get("mode", "gibbs"),
                            "temperature_start": float(request.POST.get("temperature_start") or current_temperature_start or 2000.0),
                            "temperature_end": float(request.POST.get("temperature_end") or current_temperature_end or 2000.0),
                            "temperature_step": float(request.POST.get("temperature_step") or 100.0),
                            "temperature_report": float(request.POST.get("temperature_report")) if request.POST.get("temperature_report") else None,
                            "pressure_mpa": float(request.POST.get("pressure_mpa") or current_pressure_mpa or 0.1),
                            "feed_basis": request.POST.get("feed_basis", current_feed_basis or "mole"),
                            "include_condensed": request.POST.get("include_condensed") == "on",
                            "include_ions": request.POST.get("include_ions") == "on",
                            "feed_input": request.POST.get("feed_input", ""),
                        }
                        db_form = DatabaseEquilibriumForm(initial=cleaned_data)
                        save_name = request.POST.get("save_name_result", "").strip() or default_save_name(source, cleaned_data["mode"])
                        selected_saved = save_database_calculation(cleaned_data, save_name, result_payload=result_payload)
                    else:
                        cleaned_data = {
                            "mode": request.POST.get("mode", "gibbs"),
                            "example": request.POST.get("example", ""),
                            "raw_input": request.POST.get("raw_input", ""),
                        }
                        form = EquilibriumInputForm(initial=cleaned_data)
                        save_name = request.POST.get("save_name_result", "").strip() or default_save_name(
                            SavedCalculation.SOURCE_MANUAL,
                            cleaned_data["mode"],
                            cleaned_data.get("example", ""),
                        )
                        selected_saved = save_manual_calculation(cleaned_data, save_name, result_payload=result_payload)
                    save_message = f"Calculation saved as #{selected_saved.id}: {selected_saved.name}"

        elif source == SavedCalculation.SOURCE_DATABASE:
            db_form = DatabaseEquilibriumForm(request.POST)
            form = EquilibriumInputForm(initial=initial_manual)
            custom_substance_form = CustomSubstanceForm(initial=default_custom_substance_initial())
            if db_form.is_valid():
                try:
                    snapshots = run_database_series(db_form.cleaned_data)
                    report_temperature_value = db_form.cleaned_data.get("temperature_report")
                    primary_snapshot = snapshots[-1] if snapshots else None
                    report_snapshot = None
                    if report_temperature_value is not None:
                        report_temperature = float(report_temperature_value)
                        report_snapshot = run_database_point(db_form.cleaned_data, report_temperature)
                        primary_snapshot = report_snapshot
                    if primary_snapshot is None:
                        raise ValueError("No calculation points were produced.")

                    parsed = primary_snapshot["parsed"]
                    result = primary_snapshot["result"]
                    rows, phases, multipliers = result_context(primary_snapshot)
                    if report_snapshot is not None:
                        concentration_rows = build_concentration_rows(report_snapshot)
                    temperature_series_rows = build_temperature_series_rows_data(snapshots)
                    temperature_plot_html = build_temperature_plot_from_series_rows(temperature_series_rows)
                    temperature_table = build_temperature_rows(snapshots)
                    csv_exports = build_csv_exports(
                        temperature_series_rows,
                        concentration_rows,
                        phases if report_snapshot is not None else [],
                    )
                    current_temperature_start = db_form.cleaned_data["temperature_start"]
                    current_temperature_end = db_form.cleaned_data["temperature_end"]
                    current_temperature_report = db_form.cleaned_data.get("temperature_report")
                    current_pressure_mpa = db_form.cleaned_data["pressure_mpa"]
                    current_feed_basis = db_form.cleaned_data.get("feed_basis", "mole")
                    result_payload = build_result_payload(
                        source=source,
                        parsed=parsed,
                        result=result,
                        rows=rows,
                        phases=phases if report_snapshot is not None else [],
                        multipliers=multipliers,
                        concentration_rows=concentration_rows,
                        temperature_table=temperature_table,
                        temperature_series_rows=temperature_series_rows,
                        primary_temperature=report_temperature,
                        current_temperature_start=current_temperature_start,
                        current_temperature_end=current_temperature_end,
                        current_temperature_report=current_temperature_report,
                        current_pressure_mpa=current_pressure_mpa,
                        current_feed_basis=current_feed_basis,
                    )
                except Exception as exc:
                    db_form.add_error(None, str(exc))
        else:
            form = EquilibriumInputForm(request.POST)
            db_form = DatabaseEquilibriumForm(initial=default_database_initial())
            custom_substance_form = CustomSubstanceForm(initial=default_custom_substance_initial())
            if form.is_valid():
                try:
                    parsed, result = run_manual_calculation(form.cleaned_data)
                    primary_snapshot = {
                        "temperature": None,
                        "parsed": parsed,
                        "result": result,
                        "rows": result_rows(result),
                        "phases": phase_rows(result),
                        "multipliers": multiplier_rows(result),
                    }
                    rows, phases, multipliers = result_context(primary_snapshot)
                    concentration_rows = build_concentration_rows(primary_snapshot)
                    csv_exports = build_csv_exports([], concentration_rows, phases)
                    current_feed_basis = "mole"
                    result_payload = build_result_payload(
                        source=SavedCalculation.SOURCE_MANUAL,
                        parsed=parsed,
                        result=result,
                        rows=rows,
                        phases=phases,
                        multipliers=multipliers,
                        concentration_rows=concentration_rows,
                        temperature_table=[],
                        temperature_series_rows=[],
                        primary_temperature=None,
                        current_temperature_start=None,
                        current_temperature_end=None,
                        current_temperature_report=None,
                        current_pressure_mpa=None,
                        current_feed_basis=current_feed_basis,
                    )
                    source = SavedCalculation.SOURCE_MANUAL
                except Exception as exc:
                    form.add_error(None, str(exc))
    else:
        saved_id = request.GET.get("saved", "").strip()
        if saved_id:
            selected_saved = get_object_or_404(SavedCalculation, pk=saved_id)
            source = selected_saved.source
            if selected_saved.result_payload:
                restored = apply_result_bundle(restore_saved_result_payload(selected_saved.result_payload))
                parsed = restored["parsed"]
                result = restored["result"]
                rows = restored["rows"]
                phases = restored["phases"]
                multipliers = restored["multipliers"]
                concentration_rows = restored["concentration_rows"]
                temperature_series_rows = restored["temperature_series_rows"]
                temperature_table = restored["temperature_table"]
                temperature_plot_html = restored["temperature_plot_html"]
                csv_exports = restored["csv_exports"]
                report_temperature = restored["primary_temperature"]
                current_temperature_start = restored["current_temperature_start"]
                current_temperature_end = restored["current_temperature_end"]
                current_temperature_report = restored["current_temperature_report"]
                current_pressure_mpa = restored["current_pressure_mpa"]
                current_feed_basis = restored["current_feed_basis"]
                result_payload = selected_saved.result_payload
                if source == SavedCalculation.SOURCE_DATABASE:
                    db_form = DatabaseEquilibriumForm(initial=database_initial_from_saved(selected_saved))
                    custom_substance_form = CustomSubstanceForm(initial=default_custom_substance_initial())
                else:
                    form = EquilibriumInputForm(initial=manual_initial_from_saved(selected_saved))
                    custom_substance_form = CustomSubstanceForm(initial=default_custom_substance_initial())
            elif selected_saved.source == SavedCalculation.SOURCE_DATABASE:
                db_initial = database_initial_from_saved(selected_saved)
                db_form = DatabaseEquilibriumForm(initial=db_initial)
                custom_substance_form = CustomSubstanceForm(initial=default_custom_substance_initial())
                try:
                    snapshots = run_database_series(db_initial)
                    report_temperature_value = db_initial.get("temperature_report")
                    primary_snapshot = snapshots[-1] if snapshots else None
                    report_snapshot = None
                    if report_temperature_value is not None:
                        report_temperature = float(report_temperature_value)
                        report_snapshot = run_database_point(db_initial, report_temperature)
                        primary_snapshot = report_snapshot
                    if primary_snapshot is None:
                        raise ValueError("No calculation points were produced.")
                    parsed = primary_snapshot["parsed"]
                    result = primary_snapshot["result"]
                    rows, phases, multipliers = result_context(primary_snapshot)
                    if report_snapshot is not None:
                        concentration_rows = build_concentration_rows(report_snapshot)
                    temperature_series_rows = build_temperature_series_rows_data(snapshots)
                    temperature_plot_html = build_temperature_plot_from_series_rows(temperature_series_rows)
                    temperature_table = build_temperature_rows(snapshots)
                    csv_exports = build_csv_exports(
                        temperature_series_rows,
                        concentration_rows,
                        phases if report_snapshot is not None else [],
                    )
                    current_temperature_start = db_initial["temperature_start"]
                    current_temperature_end = db_initial["temperature_end"]
                    current_temperature_report = db_initial.get("temperature_report")
                    current_pressure_mpa = db_initial["pressure_mpa"]
                    current_feed_basis = db_initial.get("feed_basis", "mole")
                    result_payload = build_result_payload(
                        source=source,
                        parsed=parsed,
                        result=result,
                        rows=rows,
                        phases=phases if report_snapshot is not None else [],
                        multipliers=multipliers,
                        concentration_rows=concentration_rows,
                        temperature_table=temperature_table,
                        temperature_series_rows=temperature_series_rows,
                        primary_temperature=report_temperature,
                        current_temperature_start=current_temperature_start,
                        current_temperature_end=current_temperature_end,
                        current_temperature_report=current_temperature_report,
                        current_pressure_mpa=current_pressure_mpa,
                        current_feed_basis=current_feed_basis,
                    )
                except Exception as exc:
                    db_form.add_error(None, str(exc))
            else:
                manual_initial = manual_initial_from_saved(selected_saved)
                form = EquilibriumInputForm(initial=manual_initial)
                custom_substance_form = CustomSubstanceForm(initial=default_custom_substance_initial())
                try:
                    parsed, result = run_manual_calculation(manual_initial)
                    primary_snapshot = {
                        "temperature": None,
                        "parsed": parsed,
                        "result": result,
                        "rows": result_rows(result),
                        "phases": phase_rows(result),
                        "multipliers": multiplier_rows(result),
                    }
                    rows, phases, multipliers = result_context(primary_snapshot)
                    concentration_rows = build_concentration_rows(primary_snapshot)
                    csv_exports = build_csv_exports([], concentration_rows, phases)
                    result_payload = build_result_payload(
                        source=SavedCalculation.SOURCE_MANUAL,
                        parsed=parsed,
                        result=result,
                        rows=rows,
                        phases=phases,
                        multipliers=multipliers,
                        concentration_rows=concentration_rows,
                        temperature_table=[],
                        temperature_series_rows=[],
                        primary_temperature=None,
                        current_temperature_start=None,
                        current_temperature_end=None,
                        current_temperature_report=None,
                        current_pressure_mpa=None,
                        current_feed_basis="mole",
                    )
                    source = SavedCalculation.SOURCE_MANUAL
                except Exception as exc:
                    form.add_error(None, str(exc))

    manual_mode_value = (
        form["mode"].value()
        if hasattr(form["mode"], "value")
        else form.initial.get("mode", "gibbs")
    ) or "gibbs"
    manual_example_value = (
        form["example"].value()
        if hasattr(form["example"], "value")
        else form.initial.get("example", "")
    ) or ""
    database_mode_value = (
        db_form["mode"].value()
        if hasattr(db_form["mode"], "value")
        else db_form.initial.get("mode", "gibbs")
    ) or "gibbs"
    database_temperature_start = (
        db_form["temperature_start"].value()
        if hasattr(db_form["temperature_start"], "value")
        else db_form.initial.get("temperature_start", current_temperature_start or 2000.0)
    ) or current_temperature_start or 2000.0
    database_temperature_end = (
        db_form["temperature_end"].value()
        if hasattr(db_form["temperature_end"], "value")
        else db_form.initial.get("temperature_end", current_temperature_end or 2000.0)
    ) or current_temperature_end or 2000.0
    database_temperature_report = (
        db_form["temperature_report"].value()
        if hasattr(db_form["temperature_report"], "value")
        else db_form.initial.get("temperature_report", current_temperature_report)
    )
    if database_temperature_report in ("", None):
        database_temperature_report = current_temperature_report
    database_pressure_value = (
        db_form["pressure_mpa"].value()
        if hasattr(db_form["pressure_mpa"], "value")
        else db_form.initial.get("pressure_mpa", current_pressure_mpa or 0.1)
    ) or current_pressure_mpa or 0.1
    database_feed_basis = (
        db_form["feed_basis"].value()
        if hasattr(db_form["feed_basis"], "value")
        else db_form.initial.get("feed_basis", current_feed_basis or "mole")
    ) or current_feed_basis or "mole"

    if temperature_plot_html:
        plotly_js = get_plotlyjs()

    context = {
        "form": form,
        "db_form": db_form,
        "result": result,
        "parsed": parsed,
        "rows": rows,
        "phases": phases,
        "multipliers": multipliers,
        "concentration_rows": concentration_rows,
        "temperature_plot_html": temperature_plot_html,
        "plotly_js": plotly_js,
        "temperature_table": temperature_table,
        "csv_exports": csv_exports,
        "temperature_point_count": len({row["temperature"] for row in temperature_series_rows}) if temperature_series_rows else 0,
        "primary_temperature": report_temperature,
        "examples": EXAMPLES,
        "source": source,
        "substance_labels": database_substance_labels(),
        "saved_calculations": recent_saved_calculations(),
        "active_saved_id": selected_saved.id if selected_saved else None,
        "save_message": save_message,
        "manual_section_open": bool(form.errors or source == SavedCalculation.SOURCE_MANUAL),
        "details_section_open": False,
        "current_temperature_start": database_temperature_start,
        "current_temperature_end": database_temperature_end,
        "current_temperature_report": database_temperature_report,
        "current_pressure_mpa": database_pressure_value,
        "current_feed_basis": database_feed_basis,
        "current_feed_input": db_form["feed_input"].value() if hasattr(db_form["feed_input"], "value") else db_form.initial.get("feed_input", ""),
        "current_include_condensed": bool(db_form["include_condensed"].value()) if hasattr(db_form["include_condensed"], "value") else bool(db_form.initial.get("include_condensed", True)),
        "current_include_ions": bool(db_form["include_ions"].value()) if hasattr(db_form["include_ions"], "value") else bool(db_form.initial.get("include_ions", False)),
        "current_manual_mode": form["mode"].value() if hasattr(form["mode"], "value") else form.initial.get("mode", "gibbs"),
        "current_manual_example": form["example"].value() if hasattr(form["example"], "value") else form.initial.get("example", ""),
        "current_manual_raw_input": form["raw_input"].value() if hasattr(form["raw_input"], "value") else form.initial.get("raw_input", ""),
        "default_save_name_manual": default_save_name(
            SavedCalculation.SOURCE_MANUAL,
            manual_mode_value,
            manual_example_value,
        ),
        "default_save_name_database": default_save_name(
            SavedCalculation.SOURCE_DATABASE,
            f"{database_temperature_start}-{database_temperature_end}K {database_mode_value}",
        ),
        "result_payload_json": json.dumps(result_payload, ensure_ascii=False) if result_payload else "",
        "custom_substance_form": custom_substance_form,
        "custom_substances": recent_custom_substances(),
        "custom_substance_message": custom_substance_message,
    }
    return render(request, "equilibrium/equilibrium_calculator.html", context)
