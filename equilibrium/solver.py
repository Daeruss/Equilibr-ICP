import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, minimize
from django.db import OperationalError, ProgrammingError

from ivtanthermo.charge_utils import (
    build_substance_charge_map,
    coerce_float_array,
    parse_charge_from_label,
)
from ivtanthermo.models import GibbsCoef, MoleculeAtomRef, MoleculeProp, Substance, Thermo

from .models import CustomSubstance


NUMERICAL_EPS = 1e-30
GAS_CONSTANT = 8.31446261815324
STANDARD_PRESSURE_MPA = 0.1


@dataclass(frozen=True)
class ParsedEquilibriumInput:
    raw_text: str
    m: int
    k: int
    np: int
    nc: int
    ion: int
    species: list[str]
    g: np.ndarray
    formula_matrix: np.ndarray
    phase_ranges: list[tuple[int, int]]
    element_amounts: np.ndarray
    trailing_lines: list[str]


@dataclass(frozen=True)
class EquilibriumResult:
    parsed: ParsedEquilibriumInput
    mode: str
    objective_value: float
    species_amounts: np.ndarray
    phase_amounts: np.ndarray
    lagrange_multipliers: np.ndarray
    success: bool
    status: int
    message: str
    iterations: int
    optimality: float | None
    mass_balance_residual: float


def parse_equilibrium_input(raw_text: str) -> ParsedEquilibriumInput:
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("Input is empty.")

    try:
        m, k, np_count, nc, ion = map(int, lines[0].split()[:5])
    except Exception as exc:
        raise ValueError("First line must contain: m k np nc ion.") from exc

    expected_min_lines = 1 + k + np_count + m
    if len(lines) < expected_min_lines:
        raise ValueError("Input is incomplete for the declared dimensions.")

    species: list[str] = []
    gibbs_values: list[float] = []
    formula_rows: list[list[float]] = []
    index = 1

    for row_number in range(k):
        parts = lines[index].split()
        if len(parts) < m + 2:
            raise ValueError(f"Species row {row_number + 1} is incomplete.")
        species.append(parts[0])
        gibbs_values.append(float(parts[1]))
        formula_rows.append([float(value) for value in parts[2 : m + 2]])
        index += 1

    phase_ranges: list[tuple[int, int]] = []
    for phase_number in range(np_count):
        parts = lines[index].split()
        if len(parts) < 2:
            raise ValueError(f"Phase row {phase_number + 1} must contain two indices.")
        start, end = map(int, parts[:2])
        start_index = start - 1
        end_index = end - 1
        if start_index < 0 or end_index >= k or start_index > end_index:
            raise ValueError(f"Phase row {phase_number + 1} has invalid indices.")
        phase_ranges.append((start_index, end_index))
        index += 1

    element_amounts = []
    for element_number in range(m):
        element_amounts.append(float(lines[index + element_number]))
    index += m

    return ParsedEquilibriumInput(
        raw_text=raw_text,
        m=m,
        k=k,
        np=np_count,
        nc=nc,
        ion=ion,
        species=species,
        g=np.array(gibbs_values, dtype=float),
        formula_matrix=np.array(formula_rows, dtype=float),
        phase_ranges=phase_ranges,
        element_amounts=np.array(element_amounts, dtype=float),
        trailing_lines=lines[index:],
    )


def load_example_input(name: str) -> ParsedEquilibriumInput:
    example_path = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "Heterogeneous-Equilibrium-main"
        / name
    )
    return parse_equilibrium_input(example_path.read_text(encoding="utf-8", errors="replace"))


def parse_feed_input(raw_text: str) -> list[tuple[str, float]]:
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("Feed input is empty.")

    entries = []
    for index, line in enumerate(lines, start=1):
        try:
            label, amount = line.rsplit(maxsplit=1)
            entries.append((label.strip(), float(amount)))
        except Exception as exc:
            raise ValueError(f"Feed row {index} must be '<substance label> <amount>'.") from exc
    return entries


def _substance_molar_mass_g_per_mol(substance: Substance) -> float | None:
    molecule_prop = (
        MoleculeProp.objects.filter(molecule=substance.molecule)
        .order_by("-recommended", "id")
        .first()
    )
    if molecule_prop and molecule_prop.mass and molecule_prop.mass > 0:
        return float(molecule_prop.mass)

    refs = getattr(substance.molecule, "_prefetched_atom_refs", None)
    if refs is None:
        refs = MoleculeAtomRef.objects.filter(molecule=substance.molecule).select_related("atom")

    molar_mass = 0.0
    has_mass_data = False
    for ref in refs:
        if ref.atom.charge == -1:
            continue
        if ref.atom.mass_num is None:
            return None
        has_mass_data = True
        molar_mass += float(ref.num_elements) * float(ref.atom.mass_num)

    if has_mass_data and molar_mass > 0:
        return molar_mass
    return None


def _custom_substance_molar_mass_g_per_mol(custom_substance: CustomSubstance) -> float | None:
    if custom_substance.molar_mass and custom_substance.molar_mass > 0:
        return float(custom_substance.molar_mass)
    return None


def _safe_builtin_feed_substances(feed_labels: list[str]) -> list[Substance]:
    try:
        return list(
            Substance.objects.filter(label__in=feed_labels)
            .select_related("molecule", "phase")
            .prefetch_related("molecule__moleculeatomref_set__atom")
        )
    except (OperationalError, ProgrammingError):
        return []


def _safe_all_builtin_substances() -> list[Substance]:
    try:
        return list(
            Substance.objects.select_related("molecule", "phase")
            .prefetch_related("molecule__moleculeatomref_set__atom")
        )
    except (OperationalError, ProgrammingError):
        return []


def convert_feed_entries_to_moles(
    feed_entries: list[tuple[str, float]],
    *,
    feed_basis: str = "mole",
) -> list[tuple[str, float]]:
    if feed_basis == "mole":
        return feed_entries
    if feed_basis != "mass":
        raise ValueError(f"Unsupported feed basis: {feed_basis}")

    feed_labels = [label for label, _ in feed_entries]
    substances = _safe_builtin_feed_substances(feed_labels)
    custom_substances = list(CustomSubstance.objects.filter(label__in=feed_labels, is_active=True))
    substance_by_label = {substance.label: substance for substance in substances}
    custom_by_label = {substance.label: substance for substance in custom_substances}
    missing = [
        label for label in feed_labels
        if label not in substance_by_label and label not in custom_by_label
    ]
    if missing:
        raise ValueError(f"Unknown substance labels: {', '.join(missing)}")

    for substance in substances:
        substance.molecule._prefetched_atom_refs = list(substance.molecule.moleculeatomref_set.all())

    converted_entries = []
    for label, amount in feed_entries:
        if amount < 0:
            raise ValueError("Feed amounts must be non-negative.")
        if label in custom_by_label:
            molar_mass = _custom_substance_molar_mass_g_per_mol(custom_by_label[label])
        else:
            substance = substance_by_label[label]
            molar_mass = _substance_molar_mass_g_per_mol(substance)
        if molar_mass is None or molar_mass <= 0:
            raise ValueError(f"Molar mass is unavailable for substance '{label}'.")
        converted_entries.append((label, amount / molar_mass))
    return converted_entries


def temperature_points(start: float, end: float, step: float) -> list[float]:
    if start <= 0 or end <= 0:
        raise ValueError("Temperature must be positive.")
    if step <= 0:
        raise ValueError("Temperature step must be positive.")
    if end < start:
        raise ValueError("Temperature range end must be greater than or equal to start.")

    points = []
    current = float(start)
    limit = float(end)
    tolerance = max(abs(step) * 1e-9, 1e-9)
    while current <= limit + tolerance:
        points.append(round(current, 8))
        current += step
        if len(points) > 400:
            raise ValueError("Temperature grid is too large.")

    if not points:
        raise ValueError("Temperature grid is empty.")
    return points


def _substance_charge(substance: Substance, charge_map: dict[int, int] | None = None) -> int:
    if charge_map is not None and substance.id in charge_map:
        return int(charge_map[substance.id])
    return parse_charge_from_label(substance.label)


def _molecule_element_counts(substance: Substance) -> dict[str, float]:
    counts: dict[str, float] = {}
    refs = getattr(substance.molecule, "_prefetched_atom_refs", None)
    if refs is None:
        refs = MoleculeAtomRef.objects.filter(molecule=substance.molecule).select_related("atom")

    for ref in refs:
        if ref.atom.charge == -1:
            continue
        counts[ref.atom.symbol] = counts.get(ref.atom.symbol, 0.0) + float(ref.num_elements)
    return counts


def _custom_substance_element_counts(custom_substance: CustomSubstance) -> dict[str, float]:
    return {
        str(symbol): float(amount)
        for symbol, amount in (custom_substance.element_counts or {}).items()
        if float(amount) != 0.0
    }


def _gibbs_rt_from_coefficients(thermo: Thermo, coefficient: GibbsCoef, temperature: float) -> float:
    f1, f2, f3, f4, f5, f6, f7 = (coerce_float_array(coefficient.data) + [0.0] * 7)[:7]
    x = temperature / 10000.0
    entropy = f1 + f2 * (math.log(x) + 1) - f3 / (x ** 2) + 2 * f5 * x + 3 * f6 * (x ** 2) + 4 * f7 * (x ** 3)
    dh = 10 * (f2 * x - 2 * f3 / x - f4 + f5 * (x ** 2) + 2 * f6 * (x ** 3) + 3 * f7 * (x ** 4))
    enthalpy = (thermo.dfh0 or 0.0) / 1000.0 + dh
    gibbs = enthalpy - entropy * temperature / 1000.0
    return gibbs * 1000.0 / (GAS_CONSTANT * temperature)


def _custom_gibbs_rt(custom_substance: CustomSubstance, temperature: float) -> float | None:
    if custom_substance.tmin is not None and temperature < float(custom_substance.tmin):
        return None
    if custom_substance.tmax is not None and temperature > float(custom_substance.tmax):
        return None

    coefficients = coerce_float_array(custom_substance.gibbs_coefficients)
    if len(coefficients) != 7:
        raise ValueError(f"Custom substance '{custom_substance.label}' must have exactly 7 Gibbs coefficients.")

    coefficient_stub = type("CoefficientStub", (), {"data": coefficients})()
    thermo_stub = type("ThermoStub", (), {"dfh0": float(custom_substance.dfh0 or 0.0)})()
    return _gibbs_rt_from_coefficients(thermo_stub, coefficient_stub, temperature)


def build_input_from_database(
    temperature: float,
    feed_entries: list[tuple[str, float]],
    pressure_mpa: float = STANDARD_PRESSURE_MPA,
    include_condensed: bool = True,
    include_ions: bool = False,
    feed_basis: str = "mole",
) -> ParsedEquilibriumInput:
    if pressure_mpa <= 0:
        raise ValueError("Pressure must be positive.")

    feed_entries = convert_feed_entries_to_moles(feed_entries, feed_basis=feed_basis)

    feed_labels = [label for label, _ in feed_entries]
    feed_substances = _safe_builtin_feed_substances(feed_labels)
    feed_custom_substances = list(CustomSubstance.objects.filter(label__in=feed_labels, is_active=True))
    substance_by_label = {substance.label: substance for substance in feed_substances}
    custom_by_label = {substance.label: substance for substance in feed_custom_substances}
    missing = [
        label for label in feed_labels
        if label not in substance_by_label and label not in custom_by_label
    ]
    if missing:
        raise ValueError(f"Unknown substance labels: {', '.join(missing)}")

    for substance in feed_substances:
        substance.molecule._prefetched_atom_refs = list(substance.molecule.moleculeatomref_set.all())
    feed_charge_map = build_substance_charge_map(feed_substances)

    feed_element_symbols: set[str] = set()
    element_amounts_by_symbol: dict[str, float] = {}
    charge_balance = 0.0
    for label, amount in feed_entries:
        if label in custom_by_label:
            custom_substance = custom_by_label[label]
            counts = _custom_substance_element_counts(custom_substance)
            charge = parse_charge_from_label(custom_substance.label)
        else:
            substance = substance_by_label[label]
            counts = _molecule_element_counts(substance)
            charge = _substance_charge(substance, feed_charge_map)
        for symbol, count in counts.items():
            feed_element_symbols.add(symbol)
            element_amounts_by_symbol[symbol] = element_amounts_by_symbol.get(symbol, 0.0) + count * amount
        charge_balance += charge * amount

    all_substances = _safe_all_builtin_substances()
    candidates = []
    for substance in all_substances:
        substance.molecule._prefetched_atom_refs = list(substance.molecule.moleculeatomref_set.all())
    candidate_charge_map = build_substance_charge_map(all_substances)
    custom_candidates = list(CustomSubstance.objects.filter(is_active=True))

    for substance in all_substances:
        counts = _molecule_element_counts(substance)
        charge = _substance_charge(substance, candidate_charge_map)
        symbols = set(counts.keys())

        if symbols and not symbols.issubset(feed_element_symbols):
            continue
        if not symbols and charge == 0:
            continue
        if not include_ions and charge != 0:
            continue
        if not include_condensed and substance.phase.label != "g":
            continue
        if substance.phase.label != "g" and charge != 0 and not include_condensed:
            continue
        if substance.phase.label != "g" and charge != 0 and not include_ions:
            continue

        candidates.append(
            {
                "source": "builtin",
                "label": substance.label,
                "phase_label": substance.phase.label,
                "substance": substance,
                "counts": counts,
                "charge": charge,
            }
        )

    for custom_substance in custom_candidates:
        counts = _custom_substance_element_counts(custom_substance)
        charge = parse_charge_from_label(custom_substance.label)
        symbols = set(counts.keys())

        if symbols and not symbols.issubset(feed_element_symbols):
            continue
        if not symbols and charge == 0:
            continue
        if not include_ions and charge != 0:
            continue
        if not include_condensed and custom_substance.phase != "g":
            continue
        if custom_substance.phase != "g" and charge != 0 and not include_condensed:
            continue
        if custom_substance.phase != "g" and charge != 0 and not include_ions:
            continue

        candidates.append(
            {
                "source": "custom",
                "label": custom_substance.label,
                "phase_label": custom_substance.phase,
                "custom_substance": custom_substance,
                "counts": counts,
                "charge": charge,
            }
        )

    if not candidates:
        raise ValueError("No candidate substances were found in the database for the selected element system.")

    builtin_substance_ids = [
        row["substance"].id
        for row in candidates
        if row["source"] == "builtin"
    ]
    thermo_qs = (
        Thermo.objects.filter(substance_id__in=builtin_substance_ids)
        .select_related("substance")
        .order_by("-recommended", "id")
    )
    thermo_by_substance: dict[int, Thermo] = {}
    for thermo in thermo_qs:
        thermo_by_substance.setdefault(thermo.substance_id, thermo)

    coefficients = (
        GibbsCoef.objects.filter(
            thermo_id__in=[thermo.id for thermo in thermo_by_substance.values()],
            tmin__lte=temperature,
            tmax__gte=temperature,
        )
        .order_by("thermo_id", "-tmin", "id")
    )
    coefficient_by_thermo: dict[int, GibbsCoef] = {}
    for coefficient in coefficients:
        coefficient_by_thermo.setdefault(coefficient.thermo_id, coefficient)

    valid_candidates = []
    for row in candidates:
        if row["source"] == "custom":
            g_rt = _custom_gibbs_rt(row["custom_substance"], temperature)
            if g_rt is None:
                continue
        else:
            thermo = thermo_by_substance.get(row["substance"].id)
            coefficient = coefficient_by_thermo.get(thermo.id) if thermo else None
            if thermo is None or coefficient is None:
                continue
            g_rt = _gibbs_rt_from_coefficients(thermo, coefficient, temperature)
        if row["phase_label"] == "g":
            g_rt += math.log(pressure_mpa / STANDARD_PRESSURE_MPA)
        valid_candidates.append({**row, "g_rt": g_rt})

    if not valid_candidates:
        raise ValueError("No thermodynamic data covering the selected temperature were found in the database.")

    ordered_candidates = sorted(
        valid_candidates,
        key=lambda row: (1 if row["phase_label"] == "g" else 0, row["label"]),
    )

    include_charge_dimension = any(row["charge"] != 0 for row in ordered_candidates) or abs(charge_balance) > 0
    element_order = sorted(feed_element_symbols)
    if include_charge_dimension:
        element_order.append("charge")

    species = []
    gibbs_values = []
    formula_rows = []
    for row in ordered_candidates:
        species.append(row["label"])
        gibbs_values.append(row["g_rt"])
        formula_row = [row["counts"].get(symbol, 0.0) for symbol in element_order if symbol != "charge"]
        if include_charge_dimension:
            formula_row.append(float(row["charge"]))
        formula_rows.append(formula_row)

    element_amounts = [element_amounts_by_symbol.get(symbol, 0.0) for symbol in element_order if symbol != "charge"]
    if include_charge_dimension:
        element_amounts.append(charge_balance)

    nc = sum(1 for row in ordered_candidates if row["phase_label"] != "g")
    gas_count = len(ordered_candidates) - nc
    phase_ranges = [(nc, len(ordered_candidates) - 1)] if gas_count > 0 else []

    metadata = [
        "source database",
        f"temperature {temperature}",
        f"pressure_mpa {pressure_mpa}",
        f"include_condensed {1 if include_condensed else 0}",
        f"include_ions {1 if include_ions else 0}",
        "feed",
    ]
    metadata.extend(f"{label} {amount}" for label, amount in feed_entries)

    raw_lines = [
        f"{len(element_order)} {len(species)} {len(phase_ranges)} {nc} {1 if include_charge_dimension else 0}",
    ]
    for species_name, g_rt, row in zip(species, gibbs_values, formula_rows):
        raw_lines.append(" ".join([species_name, str(g_rt)] + [str(value) for value in row]))
    for start, end in phase_ranges:
        raw_lines.append(f"{start + 1} {end + 1}")
    raw_lines.extend(str(value) for value in element_amounts)
    raw_lines.extend(metadata)

    return ParsedEquilibriumInput(
        raw_text="\n".join(raw_lines),
        m=len(element_order),
        k=len(species),
        np=len(phase_ranges),
        nc=nc,
        ion=1 if include_charge_dimension else 0,
        species=species,
        g=np.array(gibbs_values, dtype=float),
        formula_matrix=np.array(formula_rows, dtype=float),
        phase_ranges=phase_ranges,
        element_amounts=np.array(element_amounts, dtype=float),
        trailing_lines=metadata,
    )


def _phase_amounts_from_species(parsed: ParsedEquilibriumInput, species_amounts: np.ndarray) -> np.ndarray:
    amounts = []
    for start, end in parsed.phase_ranges:
        amounts.append(float(np.sum(species_amounts[start : end + 1])))
    return np.array(amounts, dtype=float)


def _gibbs_objective(parsed: ParsedEquilibriumInput, species_amounts: np.ndarray) -> float:
    species_amounts = np.clip(species_amounts, NUMERICAL_EPS, None)
    total = float(np.dot(species_amounts[: parsed.nc], parsed.g[: parsed.nc]))
    for start, end in parsed.phase_ranges:
        phase_species = species_amounts[start : end + 1]
        phase_total = float(np.sum(phase_species))
        total += float(np.sum(phase_species * (np.log(phase_species) + parsed.g[start : end + 1])))
        total -= phase_total * math.log(max(phase_total, NUMERICAL_EPS))
    return total


def _helmholtz_objective(parsed: ParsedEquilibriumInput, species_amounts: np.ndarray) -> float:
    species_amounts = np.clip(species_amounts, NUMERICAL_EPS, None)
    total = float(np.dot(species_amounts[: parsed.nc], parsed.g[: parsed.nc]))
    for phase_index, (start, end) in enumerate(parsed.phase_ranges):
        phase_species = species_amounts[start : end + 1]
        phase_total = float(np.sum(phase_species))
        total += float(np.sum(phase_species * (np.log(phase_species) + parsed.g[start : end + 1])))
        if phase_index > 0:
            total -= phase_total * math.log(max(phase_total, NUMERICAL_EPS))
    return total


def solve_equilibrium(parsed: ParsedEquilibriumInput, mode: str = "gibbs") -> EquilibriumResult:
    mode = mode.lower().strip()
    if mode not in {"gibbs", "helmholtz"}:
        raise ValueError("Mode must be either 'gibbs' or 'helmholtz'.")

    objective = _gibbs_objective if mode == "gibbs" else _helmholtz_objective
    formula_transposed = parsed.formula_matrix.T
    linear_constraint = LinearConstraint(
        formula_transposed,
        parsed.element_amounts,
        parsed.element_amounts,
    )
    initial_guess = np.full(parsed.k, 1e-4, dtype=float)
    bounds = Bounds(np.full(parsed.k, NUMERICAL_EPS), np.full(parsed.k, np.inf))

    result = minimize(
        lambda values: objective(parsed, values),
        initial_guess,
        method="trust-constr",
        constraints=[linear_constraint],
        bounds=bounds,
        options={"maxiter": 2000, "verbose": 0},
    )

    species_amounts = np.clip(result.x, 0.0, None)
    phase_amounts = _phase_amounts_from_species(parsed, species_amounts)
    residual = formula_transposed @ species_amounts - parsed.element_amounts

    lagrange = np.array([], dtype=float)
    if getattr(result, "v", None):
        raw_lagrange = np.array(result.v[0], dtype=float)
        lagrange = raw_lagrange.copy()
        if parsed.ion != 0 and len(lagrange) == parsed.m:
            lagrange[-1] = -lagrange[-1]

    return EquilibriumResult(
        parsed=parsed,
        mode=mode,
        objective_value=float(result.fun),
        species_amounts=species_amounts,
        phase_amounts=phase_amounts,
        lagrange_multipliers=lagrange,
        success=bool(result.success),
        status=int(result.status),
        message=str(result.message),
        iterations=int(getattr(result, "nit", 0)),
        optimality=float(getattr(result, "optimality", np.nan))
        if getattr(result, "optimality", None) is not None
        else None,
        mass_balance_residual=float(np.max(np.abs(residual))),
    )


def result_rows(result: EquilibriumResult, threshold: float = 1e-12) -> list[dict]:
    rows = []
    for index, (name, amount, gibbs_rt) in enumerate(
        zip(result.parsed.species, result.species_amounts, result.parsed.g),
        start=1,
    ):
        if amount < threshold:
            continue
        rows.append(
            {
                "index": index,
                "species": name,
                "amount": float(amount),
                "g_rt": float(gibbs_rt),
            }
        )
    return sorted(rows, key=lambda row: row["amount"], reverse=True)


def phase_rows(result: EquilibriumResult) -> list[dict]:
    rows = []
    for phase_index, ((start, end), amount) in enumerate(
        zip(result.parsed.phase_ranges, result.phase_amounts),
        start=1,
    ):
        rows.append(
            {
                "phase_index": phase_index,
                "start": start + 1,
                "end": end + 1,
                "amount": float(amount),
                "species": result.parsed.species[start : end + 1],
            }
        )
    return rows


def multiplier_rows(result: EquilibriumResult) -> list[dict]:
    rows = []
    for index, value in enumerate(result.lagrange_multipliers, start=1):
        rows.append({"element_index": index, "value": float(value)})
    return rows


EXAMPLES = {
    "test1.dat": {"label": "Gibbs: C2O at 2000 K, 0.1 MPa", "mode": "gibbs"},
    "test11.dat": {"label": "Gibbs: FeOC with condensed oxide mixture", "mode": "gibbs"},
    "test1i.dat": {"label": "Gibbs: ionized H2O at 10000 K, 0.1 MPa", "mode": "gibbs"},
    "test1vi.dat": {"label": "Helmholtz: ionized H2O at 10000 K, fixed volume", "mode": "helmholtz"},
}
