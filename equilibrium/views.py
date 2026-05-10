from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from ivtanthermo.models import Substance

from .forms import DatabaseEquilibriumForm, EquilibriumInputForm
from .models import SavedCalculation
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


def database_substance_labels() -> list[str]:
    return list(Substance.objects.order_by("label").values_list("label", flat=True))


def recent_saved_calculations(limit: int = 12) -> list[SavedCalculation]:
    return list(SavedCalculation.objects.all()[:limit])


def default_database_initial() -> dict:
    return {
        "mode": "gibbs",
        "temperature_start": 2000.0,
        "temperature_end": 2000.0,
        "temperature_step": 100.0,
        "pressure_mpa": 0.1,
        "include_condensed": True,
        "include_ions": False,
        "feed_input": "C2O(g) 1.0",
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
        "pressure_mpa": saved_calculation.pressure_mpa or 0.1,
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


def run_database_series(cleaned_data: dict) -> list[dict]:
    feed_entries = parse_feed_input(cleaned_data["feed_input"])
    temperatures = temperature_points(
        cleaned_data["temperature_start"],
        cleaned_data["temperature_end"],
        cleaned_data["temperature_step"],
    )

    snapshots = []
    for temperature in temperatures:
        parsed = build_input_from_database(
            temperature=temperature,
            feed_entries=feed_entries,
            pressure_mpa=cleaned_data["pressure_mpa"],
            include_condensed=cleaned_data["include_condensed"],
            include_ions=cleaned_data["include_ions"],
        )
        result = solve_equilibrium(parsed, mode=cleaned_data["mode"])
        snapshots.append(
            {
                "temperature": temperature,
                "parsed": parsed,
                "result": result,
                "rows": result_rows(result),
                "phases": phase_rows(result),
                "multipliers": multiplier_rows(result),
            }
        )
    return snapshots


def chart_rows(items: list[dict], value_key: str = "value") -> list[dict]:
    if not items:
        return []

    max_value = max(float(item[value_key]) for item in items)
    if max_value <= 0:
        max_value = 1.0

    prepared = []
    for item in items:
        value = float(item[value_key])
        prepared.append({**item, "relative": value / max_value * 100.0})
    return prepared


def result_context(snapshot: dict):
    rows = snapshot["rows"]
    phases = snapshot["phases"]
    multipliers = snapshot["multipliers"]

    species_chart = chart_rows(
        [
            {
                "label": row["species"],
                "value": row["amount"],
                "meta": f"g / RT = {row['g_rt']:.6f}",
            }
            for row in rows[:20]
        ]
    )
    phase_chart = chart_rows(
        [
            {
                "label": f"Phase {row['phase_index']}",
                "value": row["amount"],
                "meta": ", ".join(row["species"]),
            }
            for row in phases
        ]
    )
    return rows, phases, multipliers, species_chart, phase_chart


def build_temperature_chart(snapshots: list[dict], species_limit: int = 8) -> dict | None:
    if len(snapshots) < 2:
        return None

    temperatures = [snapshot["temperature"] for snapshot in snapshots]
    fraction_maps = []
    species_maxima: dict[str, float] = {}

    for snapshot in snapshots:
        total_amount = max(float(snapshot["result"].species_amounts.sum()), NUMERICAL_EPS)
        values = {}
        for species_name, amount in zip(snapshot["parsed"].species, snapshot["result"].species_amounts):
            fraction = float(amount) / total_amount
            values[species_name] = fraction
            species_maxima[species_name] = max(species_maxima.get(species_name, 0.0), fraction)
        fraction_maps.append(values)

    selected_species = [
        species_name
        for species_name, _ in sorted(species_maxima.items(), key=lambda item: item[1], reverse=True)
        if species_maxima[species_name] > 1e-10
    ][:species_limit]
    if not selected_species:
        return None

    width = 920
    height = 380
    margin_left = 64
    margin_right = 20
    margin_top = 20
    margin_bottom = 48
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom

    x_min = min(temperatures)
    x_max = max(temperatures)
    y_max = max(species_maxima[name] for name in selected_species)
    y_max = min(1.0, max(y_max * 1.05, 0.05))

    def x_coord(value: float) -> float:
        if x_max == x_min:
            return margin_left + plot_width / 2
        return margin_left + (value - x_min) / (x_max - x_min) * plot_width

    def y_coord(value: float) -> float:
        return margin_top + plot_height - (value / y_max) * plot_height

    x_ticks = [{"value": temp, "x": x_coord(temp)} for temp in temperatures]
    y_ticks = []
    for index in range(5):
        tick_value = y_max * index / 4
        y_ticks.append({"value": tick_value, "y": y_coord(tick_value)})

    series = []
    for index, species_name in enumerate(selected_species):
        points = []
        for temp, values in zip(temperatures, fraction_maps):
            value = values.get(species_name, 0.0)
            points.append(
                {
                    "temperature": temp,
                    "value": value,
                    "x": x_coord(temp),
                    "y": y_coord(value),
                }
            )

        path = " ".join(
            [
                f"{'M' if point_index == 0 else 'L'} {point['x']:.2f} {point['y']:.2f}"
                for point_index, point in enumerate(points)
            ]
        )
        series.append(
            {
                "name": species_name,
                "color": TEMPERATURE_COLORS[index % len(TEMPERATURE_COLORS)],
                "path": path,
                "points": points,
                "latest_value": points[-1]["value"],
            }
        )

    return {
        "width": width,
        "height": height,
        "margin_left": margin_left,
        "margin_top": margin_top,
        "plot_width": plot_width,
        "plot_height": plot_height,
        "x_ticks": x_ticks,
        "y_ticks": y_ticks,
        "series": series,
    }


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


def save_database_calculation(cleaned_data: dict, save_name: str) -> SavedCalculation:
    return SavedCalculation.objects.create(
        name=save_name,
        source=SavedCalculation.SOURCE_DATABASE,
        mode=cleaned_data["mode"],
        temperature=cleaned_data["temperature_start"],
        temperature_start=cleaned_data["temperature_start"],
        temperature_end=cleaned_data["temperature_end"],
        temperature_step=cleaned_data["temperature_step"],
        pressure_mpa=cleaned_data["pressure_mpa"],
        include_condensed=cleaned_data["include_condensed"],
        include_ions=cleaned_data["include_ions"],
        feed_input=cleaned_data["feed_input"],
    )


def save_manual_calculation(cleaned_data: dict, save_name: str) -> SavedCalculation:
    return SavedCalculation.objects.create(
        name=save_name,
        source=SavedCalculation.SOURCE_MANUAL,
        mode=cleaned_data["mode"],
        example_name=cleaned_data.get("example") or "",
        raw_input=cleaned_data.get("raw_input") or "",
    )


def equilibrium_calculator(request):
    selected_example = request.GET.get("example", "").strip()
    selected_saved = None
    save_message = None

    initial_manual = manual_initial_from_example(selected_example)
    form = EquilibriumInputForm(initial=initial_manual)
    db_form = DatabaseEquilibriumForm(initial=default_database_initial())

    snapshots = []
    result = None
    parsed = None
    rows = []
    phases = []
    multipliers = []
    species_chart = []
    phase_chart = []
    temperature_chart = None
    temperature_table = []
    source = None

    if request.method == "POST":
        action = request.POST.get("action", "calculate").strip()
        source = request.POST.get("source")

        if source == SavedCalculation.SOURCE_DATABASE:
            db_form = DatabaseEquilibriumForm(request.POST)
            form = EquilibriumInputForm(initial=initial_manual)

            if db_form.is_valid():
                try:
                    snapshots = run_database_series(db_form.cleaned_data)
                    primary_snapshot = snapshots[-1]
                    parsed = primary_snapshot["parsed"]
                    result = primary_snapshot["result"]
                    rows, phases, multipliers, species_chart, phase_chart = result_context(primary_snapshot)
                    temperature_chart = build_temperature_chart(snapshots)
                    temperature_table = build_temperature_rows(snapshots)
                    if action == "save":
                        save_name = (
                            request.POST.get("save_name_database", "").strip()
                            or default_save_name(source, db_form.cleaned_data["mode"])
                        )
                        selected_saved = save_database_calculation(db_form.cleaned_data, save_name)
                        save_message = f"Calculation saved as #{selected_saved.id}: {selected_saved.name}"
                except Exception as exc:
                    db_form.add_error(None, str(exc))
        else:
            form = EquilibriumInputForm(request.POST)
            db_form = DatabaseEquilibriumForm(initial=default_database_initial())

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
                    rows, phases, multipliers, species_chart, phase_chart = result_context(primary_snapshot)
                    if action == "save":
                        example_name = form.cleaned_data.get("example") or ""
                        save_name = (
                            request.POST.get("save_name_manual", "").strip()
                            or default_save_name(source or SavedCalculation.SOURCE_MANUAL, form.cleaned_data["mode"], example_name)
                        )
                        selected_saved = save_manual_calculation(form.cleaned_data, save_name)
                        save_message = f"Calculation saved as #{selected_saved.id}: {selected_saved.name}"
                except Exception as exc:
                    form.add_error(None, str(exc))
    else:
        saved_id = request.GET.get("saved", "").strip()
        if saved_id:
            selected_saved = get_object_or_404(SavedCalculation, pk=saved_id)
            source = selected_saved.source

            if selected_saved.source == SavedCalculation.SOURCE_DATABASE:
                db_initial = database_initial_from_saved(selected_saved)
                db_form = DatabaseEquilibriumForm(initial=db_initial)
                try:
                    snapshots = run_database_series(db_initial)
                    primary_snapshot = snapshots[-1]
                    parsed = primary_snapshot["parsed"]
                    result = primary_snapshot["result"]
                    rows, phases, multipliers, species_chart, phase_chart = result_context(primary_snapshot)
                    temperature_chart = build_temperature_chart(snapshots)
                    temperature_table = build_temperature_rows(snapshots)
                except Exception as exc:
                    db_form.add_error(None, str(exc))
            else:
                manual_initial = manual_initial_from_saved(selected_saved)
                form = EquilibriumInputForm(initial=manual_initial)
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
                    rows, phases, multipliers, species_chart, phase_chart = result_context(primary_snapshot)
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
        else db_form.initial.get("temperature_start", 2000.0)
    ) or 2000.0
    database_temperature_end = (
        db_form["temperature_end"].value()
        if hasattr(db_form["temperature_end"], "value")
        else db_form.initial.get("temperature_end", 2000.0)
    ) or 2000.0
    database_pressure_value = (
        db_form["pressure_mpa"].value()
        if hasattr(db_form["pressure_mpa"], "value")
        else db_form.initial.get("pressure_mpa", 0.1)
    ) or 0.1

    context = {
        "form": form,
        "db_form": db_form,
        "result": result,
        "parsed": parsed,
        "rows": rows,
        "phases": phases,
        "multipliers": multipliers,
        "species_chart": species_chart,
        "phase_chart": phase_chart,
        "temperature_chart": temperature_chart,
        "temperature_table": temperature_table,
        "temperature_point_count": len(snapshots),
        "primary_temperature": snapshots[-1]["temperature"] if snapshots else None,
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
        "current_pressure_mpa": database_pressure_value,
        "default_save_name_manual": default_save_name(
            SavedCalculation.SOURCE_MANUAL,
            manual_mode_value,
            manual_example_value,
        ),
        "default_save_name_database": default_save_name(
            SavedCalculation.SOURCE_DATABASE,
            f"{database_temperature_start}-{database_temperature_end}K {database_mode_value}",
        ),
    }
    return render(request, "equilibrium/equilibrium_calculator.html", context)
