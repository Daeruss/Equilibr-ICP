import io

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.offline import plot
from scipy.stats import linregress

from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.db.models import Min
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views import View

from equilibrium.models import SavedCalculation
from ivtanthermo.charge_utils import build_substance_charge_map, parse_charge_from_label
from ivtanthermo.models import MoleculeProp, Substance

from .models import ParsedPoint


DEFAULT_TEMPERATURE = "default"
EQUILIBR_DISPLAY_AMOUNT_THRESHOLD = 1e-12


class ParseError(Exception):
    pass


def read_uploaded_text_file(uploaded_file: UploadedFile, encoding: str = "utf-8") -> str:
    if not uploaded_file:
        raise ParseError("Файл не был передан.")
    if not uploaded_file.name.lower().endswith(".txt"):
        raise ParseError("Поддерживаются только .txt файлы.")
    try:
        raw_bytes = uploaded_file.read()
        return raw_bytes.decode(encoding)
    except UnicodeDecodeError as exc:
        raise ParseError("Не удалось декодировать файл как UTF-8.") from exc


def parse_text_points(raw_text: str) -> pd.DataFrame:
    if not raw_text or not raw_text.strip():
        raise ParseError("Пустой текстовый ввод.")

    rows = []
    for line_number, line in enumerate(raw_text.splitlines(), start=1):
        clean_line = line.split("#", 1)[0].strip()
        if not clean_line:
            continue

        parts = clean_line.replace(",", " ").replace(";", " ").split()
        try:
            if len(parts) == 2:
                mass_to_charge, intensity = parts
            elif len(parts) == 3:
                _old_point_index, mass_to_charge, intensity = parts
            else:
                raise ValueError

            rows.append(
                {
                    "point_index": len(rows) + 1,
                    "x_value": float(mass_to_charge),
                    "y_value": float(intensity),
                }
            )
        except ValueError as exc:
            raise ParseError(
                f"Ошибка в строке {line_number}. Для файла 1 используйте формат: m/z intensity."
            ) from exc

    if not rows:
        raise ParseError("Нет валидных строк для парсинга.")
    return pd.DataFrame(rows).sort_values("x_value").reset_index(drop=True)


def parse_temperature_points(raw_text: str) -> pd.DataFrame:
    if not raw_text or not raw_text.strip():
        raise ParseError("Пустой текстовый ввод.")

    rows = []
    for line_number, line in enumerate(raw_text.splitlines(), start=1):
        clean_line = line.split("#", 1)[0].strip()
        if not clean_line:
            continue

        parts = clean_line.replace(",", " ").replace(";", " ").split()
        try:
            if len(parts) == 2:
                x_value, y_value = parts
                temperature = DEFAULT_TEMPERATURE
            elif len(parts) == 3:
                temperature, x_value, y_value = parts
            elif len(parts) == 4:
                _old_point_index, temperature, x_value, y_value = parts
            else:
                raise ValueError

            rows.append(
                {
                    "point_index": 0,
                    "temperature": str(temperature),
                    "x_value": float(x_value),
                    "y_value": float(y_value),
                }
            )
        except ValueError as exc:
            raise ParseError(
                f"Ошибка в строке {line_number}. Для файла 2 используйте формат: temperature m/z concentration."
            ) from exc

    if not rows:
        raise ParseError("Нет валидных строк для парсинга.")

    df = pd.DataFrame(rows).sort_values(["temperature", "x_value"]).reset_index(drop=True)
    df["point_index"] = df.groupby("temperature").cumcount() + 1
    return df


@transaction.atomic
def save_dataframe_to_db(
    df: pd.DataFrame,
    source: str,
    batch_id: str,
    temperature: str = "",
) -> None:
    delete_filter = {"source": source, "batch_id": batch_id}
    if temperature:
        delete_filter["temperature"] = temperature
    ParsedPoint.objects.filter(**delete_filter).delete()

    objs = []
    for r in df.itertuples(index=False):
        row_temperature = getattr(r, "temperature", temperature)
        if row_temperature == DEFAULT_TEMPERATURE:
            row_temperature = ""
        objs.append(
            ParsedPoint(
                source=source,
                batch_id=batch_id,
                temperature=str(row_temperature or ""),
                point_index=int(r.point_index),
                mass_to_charge=getattr(r, "mass_to_charge", None),
                x_value=float(r.x_value),
                y_value=float(r.y_value),
            )
        )
    ParsedPoint.objects.bulk_create(objs, batch_size=1000)


def load_source_dataframe(source: str, batch_id: str, temperature: str = "") -> pd.DataFrame:
    qs = ParsedPoint.objects.filter(source=source, batch_id=batch_id)
    if temperature:
        qs = qs.filter(temperature=temperature)
    elif source in {"file2", "file4"}:
        qs = qs.filter(temperature="")

    data = list(
        qs.values("point_index", "mass_to_charge", "x_value", "y_value", "temperature").order_by("point_index")
    )
    if not data:
        return pd.DataFrame(columns=["point_index", "mass_to_charge", "x_value", "y_value", "temperature"])
    return pd.DataFrame(data)


def get_available_temperatures(batch_id: str) -> list[str]:
    temperatures = (
        ParsedPoint.objects.filter(source="file2", batch_id=batch_id)
        .order_by("temperature")
        .values_list("temperature", flat=True)
        .distinct()
    )
    return list(temperatures)


def format_number(value: float) -> str:
    return f"{float(value):g}"


def build_file1_text(batch_id: str) -> str:
    df = load_source_dataframe("file1", batch_id=batch_id)
    if df.empty:
        return ""
    return "\n".join(
        f"{format_number(row.x_value)} {format_number(row.y_value)}"
        for row in df.itertuples(index=False)
    )


def build_file2_text(batch_id: str) -> str:
    qs = (
        ParsedPoint.objects.filter(source="file2", batch_id=batch_id)
        .values("temperature", "x_value", "y_value")
        .order_by("temperature", "x_value")
    )
    return "\n".join(
        f"{row['temperature']} {format_number(row['x_value'])} {format_number(row['y_value'])}".strip()
        for row in qs
    )


def display_temperature(temperature: str) -> str:
    return temperature if temperature else "без температуры"


def calculate_regression(df: pd.DataFrame) -> dict | None:
    if df.empty:
        return None
    if len(df) < 2:
        return None

    x = df["x_value"].to_numpy()
    y = df["y_value"].to_numpy()
    slope, intercept, r_value, p_value, std_err = linregress(x, y)
    return {
        "slope": slope,
        "intercept": intercept,
        "r_value": r_value,
        "r_squared": r_value**2,
    }


def temperature_to_float(temperature: str) -> float | None:
    if not temperature:
        return None
    try:
        return float(str(temperature).replace(",", "."))
    except ValueError:
        return None


def get_temperature_range_bounds(temperatures: list[str]) -> tuple[str, str]:
    numeric_values = [temperature_to_float(temperature) for temperature in temperatures]
    numeric_values = [value for value in numeric_values if value is not None]
    if not numeric_values:
        return "", ""
    return f"{min(numeric_values):g}", f"{max(numeric_values):g}"


def analyze_r_squared_by_temperature(
    batch_id: str,
    temperatures: list[str],
    min_temperature: str = "",
    max_temperature: str = "",
) -> tuple[list[dict], dict | None]:
    min_value = temperature_to_float(min_temperature)
    max_value = temperature_to_float(max_temperature)
    results = []

    for temperature in temperatures:
        numeric_temperature = temperature_to_float(temperature)
        if numeric_temperature is None:
            continue
        if min_value is not None and numeric_temperature < min_value:
            continue
        if max_value is not None and numeric_temperature > max_value:
            continue

        df4 = load_source_dataframe("file4", batch_id=batch_id, temperature=temperature)
        if df4.empty:
            df4 = build_file4_from_file1_file2(batch_id=batch_id, temperature=temperature)["dataframe"]

        regression = calculate_regression(df4)
        if not regression:
            continue

        results.append(
            {
                "temperature": temperature,
                "temperature_value": numeric_temperature,
                "r_value": regression["r_value"],
                "r_squared": regression["r_squared"],
            }
        )

    results.sort(key=lambda item: item["temperature_value"])
    if not results:
        return [], None

    max_result = max(results, key=lambda item: item["r_squared"])
    return results, max_result


def get_plot_history() -> list:
    qs = (
        ParsedPoint.objects
        .values("batch_id")
        .annotate(created_at=Min("created_at"))
        .order_by("-created_at")
    )
    return list(qs)


def get_equilibrium_saved_calculations(limit: int = 24) -> list[SavedCalculation]:
    return list(
        SavedCalculation.objects.exclude(result_payload__isnull=True)
        .order_by("-created_at", "-id")[:limit]
    )


def format_temperature_token(value) -> str:
    if value in (None, "", DEFAULT_TEMPERATURE):
        return DEFAULT_TEMPERATURE
    return f"{float(value):g}"


def _species_mass_to_charge_map(species_labels: list[str]) -> dict[str, float]:
    mapping: dict[str, float] = {}
    substances = Substance.objects.filter(label__in=species_labels).select_related("molecule")
    charge_map = build_substance_charge_map(substances)
    for substance in substances:
        molecule = substance.molecule
        molecule_prop = (
            MoleculeProp.objects.filter(molecule=molecule)
            .order_by("-recommended", "id")
            .first()
        )
        mass = molecule_prop.mass if molecule_prop and molecule_prop.mass else None
        if mass is None:
            continue
        charge = abs(charge_map.get(substance.id, parse_charge_from_label(substance.label)))
        if charge <= 0:
            continue
        mapping[substance.label] = float(mass) / float(charge)
    return mapping


def build_dataframe_from_equilibrium_saved(saved_calculation: SavedCalculation) -> pd.DataFrame:
    payload = saved_calculation.result_payload or {}
    temperature_series_rows = payload.get("temperature_series_rows") or []
    concentration_rows = payload.get("concentration_rows") or []
    primary_temperature = payload.get("primary_temperature")

    source_rows = []
    if concentration_rows:
        temperature = format_temperature_token(primary_temperature)
        for row in concentration_rows:
            source_rows.append(
                {
                    "temperature": temperature,
                    "species": row.get("species", ""),
                    "y_value": float(row.get("mole_fraction", 0.0)),
                }
            )
    elif temperature_series_rows:
        for row in temperature_series_rows:
            if float(row.get("amount", 0.0)) < EQUILIBR_DISPLAY_AMOUNT_THRESHOLD:
                continue
            source_rows.append(
                {
                    "temperature": format_temperature_token(row.get("temperature")),
                    "species": row.get("species", ""),
                    "y_value": float(row.get("mole_fraction", 0.0)),
                }
            )

    if not source_rows:
        raise ValueError("В сохранённом расчёте Equilibr нет концентраций для импорта.")

    species_labels = sorted({row["species"] for row in source_rows if row["species"]})
    mass_to_charge_map = _species_mass_to_charge_map(species_labels)
    if not mass_to_charge_map:
        raise ValueError("В сохранённом расчёте Equilibr не найдено ионов с определимым m/z.")

    filtered_rows = []
    for row in source_rows:
        species = row["species"]
        mass_to_charge = mass_to_charge_map.get(species)
        if mass_to_charge is None:
            continue
        y_value = float(row["y_value"])
        if y_value <= 0:
            continue
        filtered_rows.append(
            {
                "temperature": row["temperature"],
                "mass_to_charge": mass_to_charge,
                "x_value": mass_to_charge,
                "y_value": y_value,
            }
        )

    if not filtered_rows:
        raise ValueError("После фильтрации не осталось ионных точек для ICP Stat.")

    df = pd.DataFrame(filtered_rows).sort_values(["temperature", "x_value"]).reset_index(drop=True)
    df["point_index"] = df.groupby("temperature").cumcount() + 1
    return df[["point_index", "temperature", "mass_to_charge", "x_value", "y_value"]]


@transaction.atomic
def build_file4_from_file1_file2(batch_id: str, temperature: str = "") -> dict:
    df1 = load_source_dataframe("file1", batch_id=batch_id)
    df2 = load_source_dataframe("file2", batch_id=batch_id, temperature=temperature)

    if df1.empty or df2.empty:
        raise ValueError("Нужно загрузить file1 и file2 для выбранной температуры.")

    merged = pd.merge(df1, df2, on="x_value", how="inner", suffixes=("_f1", "_f2"))
    if merged.empty:
        raise ValueError("Нет общих значений m/z между file1 и file2 для выбранной температуры.")

    valid_mask = (merged["y_value_f1"] > 0) & (merged["y_value_f2"] > 0)
    merged = merged[valid_mask]

    if merged.empty:
        raise ValueError("После удаления нулевых и отрицательных значений не осталось точек для графика.")

    df4 = pd.DataFrame(
        {
            "mass_to_charge": merged["x_value"],
            "x_value": np.log10(merged["y_value_f1"]),
            "y_value": np.log10(merged["y_value_f2"]),
        }
    )
    df4 = df4.sort_values("mass_to_charge").reset_index(drop=True)
    df4.insert(0, "point_index", range(1, len(df4) + 1))
    save_dataframe_to_db(df4, source="file4", batch_id=batch_id, temperature=temperature)

    return {
        "dataframe": df4,
        "regression": calculate_regression(df4),
    }


def dataframe_to_csv_bytes(df: pd.DataFrame) -> bytes:
    buffer = io.StringIO()
    df.to_csv(buffer, index=False)
    return buffer.getvalue().encode("utf-8")


class GraphPageView(View):
    template_name = "icp_stat/graph_page.html"

    def get(self, request):
        batch_id = request.GET.get("batch_id")
        error_message = request.GET.get("error")
        selected_temperature = request.GET.get("temperature", "")
        range_min = request.GET.get("range_min", "")
        range_max = request.GET.get("range_max", "")

        df4 = pd.DataFrame()
        regression = None
        temperatures = []
        r_squared_by_temperature = []
        max_r_squared_result = None
        r_squared_plot_div = ""
        file1_text = ""
        file2_text = ""
        equilibrium_saved_calculations = get_equilibrium_saved_calculations()

        if batch_id:
            file1_text = build_file1_text(batch_id)
            file2_text = build_file2_text(batch_id)
            temperatures = get_available_temperatures(batch_id)
            has_file1 = bool(file1_text.strip())
            if temperatures and selected_temperature not in temperatures:
                selected_temperature = temperatures[0]

            if has_file1 and (selected_temperature or "" in temperatures):
                df4 = load_source_dataframe("file4", batch_id=batch_id, temperature=selected_temperature)
                try:
                    if df4.empty or df4["mass_to_charge"].isna().all():
                        result = build_file4_from_file1_file2(batch_id=batch_id, temperature=selected_temperature)
                        df4 = result["dataframe"]
                        regression = result["regression"]
                    else:
                        regression = calculate_regression(df4)
                except ValueError as exc:
                    error_message = error_message or str(exc)

            if has_file1:
                default_min, default_max = get_temperature_range_bounds(temperatures)
                if not range_min:
                    range_min = default_min
                if not range_max:
                    range_max = default_max
                r_squared_by_temperature, max_r_squared_result = analyze_r_squared_by_temperature(
                    batch_id=batch_id,
                    temperatures=temperatures,
                    min_temperature=range_min,
                    max_temperature=range_max,
                )
                r_squared_plot_div = self._build_r_squared_temperature_plot(
                    r_squared_by_temperature,
                    max_r_squared_result,
                )

        graph_div = self._build_plot(df4, regression, selected_temperature)
        history = get_plot_history()

        context = {
            "batch_id": batch_id,
            "graph_div": graph_div,
            "regression": regression,
            "history": history,
            "error_message": error_message,
            "temperatures": temperatures,
            "selected_temperature": selected_temperature,
            "selected_temperature_label": display_temperature(selected_temperature),
            "range_min": range_min,
            "range_max": range_max,
            "max_r_squared_result": max_r_squared_result,
            "r_squared_plot_div": r_squared_plot_div,
            "file1_text": file1_text,
            "file2_text": file2_text,
            "equilibrium_saved_calculations": equilibrium_saved_calculations,
        }
        return render(request, self.template_name, context)

    def post(self, request):
        import uuid
        from urllib.parse import urlencode

        batch_id = request.POST.get("batch_id") or str(uuid.uuid4())[:8]
        requested_temperature = request.POST.get("selected_temperature", "")
        action = request.POST.get("action", "upload")

        file1 = request.FILES.get("file1")
        text1_val = request.POST.get("file1_text")

        file2 = request.FILES.get("file2")
        text2_val = request.POST.get("file2_text")

        try:
            if action == "import_equilibrium":
                equilibrium_id = request.POST.get("equilibrium_calculation_id")
                if not equilibrium_id:
                    raise ValueError("Выберите сохранённый расчёт Equilibr для импорта.")

                saved_calculation = SavedCalculation.objects.filter(pk=equilibrium_id).first()
                if not saved_calculation:
                    raise ValueError("Сохранённый расчёт Equilibr не найден.")

                imported_df = build_dataframe_from_equilibrium_saved(saved_calculation)
                save_dataframe_to_db(imported_df, "file2", batch_id)
                ParsedPoint.objects.filter(source="file4", batch_id=batch_id).delete()

                temperatures = get_available_temperatures(batch_id)
                selected_temperature = requested_temperature if requested_temperature in temperatures else ""
                if not selected_temperature and temperatures:
                    selected_temperature = temperatures[0]

                if not load_source_dataframe("file1", batch_id=batch_id).empty and (selected_temperature or "" in temperatures):
                    build_file4_from_file1_file2(batch_id=batch_id, temperature=selected_temperature)

                query_string = urlencode({"batch_id": batch_id, "temperature": selected_temperature})
                return redirect(f"{request.path}?{query_string}")

            if file1:
                text1 = read_uploaded_text_file(file1)
                df1 = parse_text_points(text1)
                save_dataframe_to_db(df1, "file1", batch_id)
            elif text1_val and text1_val.strip():
                df1 = parse_text_points(text1_val)
                save_dataframe_to_db(df1, "file1", batch_id)
            else:
                raise ValueError("Загрузите файл 1 или вставьте его текст.")

            if file2:
                text2 = read_uploaded_text_file(file2)
                df2 = parse_temperature_points(text2)
                save_dataframe_to_db(df2, "file2", batch_id)
            elif text2_val and text2_val.strip():
                df2 = parse_temperature_points(text2_val)
                save_dataframe_to_db(df2, "file2", batch_id)
            else:
                raise ValueError("Загрузите файл 2 или вставьте его текст.")

            ParsedPoint.objects.filter(source="file4", batch_id=batch_id).delete()
            temperatures = get_available_temperatures(batch_id)
            selected_temperature = requested_temperature if requested_temperature in temperatures else ""
            if not selected_temperature and temperatures:
                selected_temperature = temperatures[0]
            build_file4_from_file1_file2(batch_id=batch_id, temperature=selected_temperature)

            query_string = urlencode({"batch_id": batch_id, "temperature": selected_temperature})
            return redirect(f"{request.path}?{query_string}")

        except (ParseError, ValueError) as exc:
            error_msg = str(exc)
        except Exception as exc:
            error_msg = f"Системная ошибка при расчетах: {str(exc)}"

        query_string = urlencode({"error": error_msg})
        return redirect(f"{request.path}?{query_string}")

    def _build_plot(
        self,
        df4: pd.DataFrame,
        regression: dict | None = None,
        temperature: str = "",
    ) -> str:
        fig = go.Figure()

        if not df4.empty:
            fig.add_trace(
                go.Scatter(
                    x=df4["x_value"],
                    y=df4["y_value"],
                    customdata=df4["mass_to_charge"] if "mass_to_charge" in df4 else None,
                    mode="markers",
                    name="Расчетные точки (lg)",
                    hovertemplate="m/z: %{customdata:g}<br>lg(I): %{x:.6f}<br>lg(n): %{y:.6f}<extra></extra>",
                    marker=dict(size=9, color="#2563eb", line=dict(width=1, color="#ffffff")),
                )
            )

        temp_label = display_temperature(temperature)
        if regression and not df4.empty:
            slope = regression["slope"]
            intercept = regression["intercept"]
            r_squared = regression["r_squared"]

            x_line = np.linspace(df4["x_value"].min(), df4["x_value"].max(), 200)
            y_line = slope * x_line + intercept

            fig.add_trace(
                go.Scatter(
                    x=x_line,
                    y=y_line,
                    mode="lines",
                    name=f"Аппроксимация: y = {slope:.4f}x + {intercept:.4f}",
                    hovertemplate="x: %{x:.6f}<br>y_approx: %{y:.6f}<extra></extra>",
                    line=dict(color="#dc2626", width=3),
                )
            )
            title = f"График lg(n) от lg(I), температура: {temp_label} | R² = {r_squared:.6f}"
        else:
            title = "Ожидание данных для построения графика"

        fig.update_layout(
            title=title,
            xaxis_title="lg(I)",
            yaxis_title="lg(n)",
            template="plotly_white",
            height=560,
            margin=dict(l=48, r=24, t=72, b=48),
            font=dict(family="Segoe UI, Arial, sans-serif", size=13, color="#111827"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        fig.update_xaxes(showgrid=True, gridcolor="#e5e7eb", zeroline=False)
        fig.update_yaxes(showgrid=True, gridcolor="#e5e7eb", zeroline=False)
        return plot(fig, output_type="div", include_plotlyjs="cdn", config={"responsive": True})

    def _build_r_squared_temperature_plot(self, results: list[dict], max_result: dict | None) -> str:
        fig = go.Figure()

        if results:
            fig.add_trace(
                go.Scatter(
                    x=[item["temperature_value"] for item in results],
                    y=[item["r_squared"] for item in results],
                    mode="lines+markers",
                    name="R²",
                    marker=dict(size=8, color="#2563eb"),
                    line=dict(color="#2563eb", width=3),
                    hovertemplate="T: %{x:g}<br>R²: %{y:.6f}<extra></extra>",
                )
            )

        if max_result:
            fig.add_trace(
                go.Scatter(
                    x=[max_result["temperature_value"]],
                    y=[max_result["r_squared"]],
                    mode="markers",
                    name="Максимум R²",
                    marker=dict(size=13, color="#dc2626", symbol="diamond"),
                    hovertemplate="T: %{x:g}<br>R² max: %{y:.6f}<extra></extra>",
                )
            )

        fig.update_layout(
            title="Зависимость коэффициента R² от температуры",
            xaxis_title="Температура",
            yaxis_title="R²",
            template="plotly_white",
            height=420,
            margin=dict(l=48, r=24, t=72, b=48),
            font=dict(family="Segoe UI, Arial, sans-serif", size=13, color="#111827"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        fig.update_xaxes(showgrid=True, gridcolor="#e5e7eb", zeroline=False)
        fig.update_yaxes(showgrid=True, gridcolor="#e5e7eb", zeroline=False)
        return plot(fig, output_type="div", include_plotlyjs="cdn", config={"responsive": True})


class ExportCsvView(View):
    def get(self, request):
        batch_id = request.GET.get("batch_id")
        temperature = request.GET.get("temperature", "")
        if not batch_id:
            return HttpResponse("Нет данных для экспорта", status=400)

        df4 = load_source_dataframe("file4", batch_id=batch_id, temperature=temperature)
        csv_data = dataframe_to_csv_bytes(df4)

        suffix = f"_{temperature}" if temperature else ""
        response = HttpResponse(csv_data, content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="processed_file4_{batch_id}{suffix}.csv"'
        return response
