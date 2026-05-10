import math

from django.db.models import OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, render

from .models import BibAuthorRef, DataBibRef, GibbsCoef, MoleculeProp, SubstanceName, Thermo


def _format_scientific(value):
    if value is None:
        return None
    return f"{value:.6g}"


def _default_name_subquery():
    return Coalesce(_default_name_ru_subquery(), _default_name_en_subquery())


def _default_name_ru_subquery():
    return SubstanceName.objects.filter(
        substance=OuterRef("substance_id"),
        default_name=True,
    ).values("name_ru")[:1]


def _default_name_en_subquery():
    return SubstanceName.objects.filter(
        substance=OuterRef("substance_id"),
        default_name=True,
    ).values("name_en")[:1]


def _build_temperature_grid(tmin, tmax, points=36):
    if tmin is None or tmax is None:
        return []
    if tmax <= tmin:
        return [round(float(tmin), 2)]

    steps = max(2, min(points, int((tmax - tmin) / 25) + 2))
    step = (tmax - tmin) / (steps - 1)
    return [round(tmin + step * index, 2) for index in range(steps)]


def _build_chart_series(coefficients, dfh0_kj):
    datasets = {
        "cp": [],
        "phi": [],
        "s": [],
        "dh": [],
        "h": [],
        "g": [],
    }

    for row in coefficients:
        f1, f2, f3, f4, f5, f6, f7 = row["coefficients"]
        interval_label = f'{row["tmin"]:.2f} - {row["tmax"]:.2f} K'
        for temperature in _build_temperature_grid(row["tmin"], row["tmax"]):
            x = temperature / 10000
            if x <= 0:
                continue

            cp = f2 + 2 * f3 / (x ** 2) + 2 * f5 * x + 6 * f6 * (x ** 2) + 12 * f7 * (x ** 3)
            phi = f1 + f2 * math.log(x) + f3 / (x ** 2) + f4 / x + f5 * x + f6 * (x ** 2) + f7 * (x ** 3)
            entropy = f1 + f2 * (math.log(x) + 1) - f3 / (x ** 2) + 2 * f5 * x + 3 * f6 * (x ** 2) + 4 * f7 * (x ** 3)
            dh = 10 * (f2 * x - 2 * f3 / x - f4 + f5 * (x ** 2) + 2 * f6 * (x ** 3) + 3 * f7 * (x ** 4))
            enthalpy = dfh0_kj + dh
            gibbs = enthalpy - entropy * temperature / 1000

            for key, value in (
                ("cp", cp),
                ("phi", phi),
                ("s", entropy),
                ("dh", dh),
                ("h", enthalpy),
                ("g", gibbs),
            ):
                datasets[key].append(
                    {
                        "x": temperature,
                        "y": round(value, 3),
                        "interval": interval_label,
                    }
                )

    return datasets


def _build_property_rows(thermo, molecule_prop):
    rows = [
        ("Молекулярная масса", getattr(molecule_prop, "mass", None), "г/моль"),
        ("Энтальпия образования, Delta_fH(0)", None if thermo.dfh0 is None else thermo.dfh0 / 1000, "кДж/моль"),
        ("Энтальпия образования, Delta_fH(298.15 K)", None if thermo.dfh298 is None else thermo.dfh298 / 1000, "кДж/моль"),
        ("Изобарная теплоемкость, Cp(298.15 K)", thermo.cp298, "Дж/моль/К"),
        ("Энтропия, S(298.15 K)", thermo.s298, "Дж/моль/К"),
        ("Приращение энтальпии, H(298.15) - H(0)", None if thermo.dh298 is None else thermo.dh298 / 1000, "кДж/моль"),
        ("Ядерно-спиновая энтропия, S_nucl", getattr(molecule_prop, "nucl_entropy", None), "Дж/моль/К"),
        ("Энтальпия диссоциации, Delta_rH(0)", None if thermo.drh298 is None else thermo.drh298 / 1000, "кДж/моль"),
    ]

    return [
        {"label": label, "value": value, "units": units}
        for label, value, units in rows
        if value is not None
    ]


def _build_reference_map(bibliography_ids):
    author_rows = (
        BibAuthorRef.objects.filter(bib_id__in=bibliography_ids)
        .select_related("author")
        .order_by("bib_id", "pos", "id")
    )
    author_map = {}
    for row in author_rows:
        author_map.setdefault(row.bib_id, []).append(
            " ".join(part for part in [row.author.lastname, row.author.initials] if part)
        )
    return author_map


def _build_references(datainfo):
    refs = list(
        DataBibRef.objects.filter(datainfo=datainfo)
        .select_related("bib__bibtype")
        .order_by("id")
    )
    if not refs:
        return []

    author_map = _build_reference_map([ref.bib_id for ref in refs])
    result = []
    for ref in refs:
        bib = ref.bib
        parts = []
        authors = ", ".join(author_map.get(bib.id, []))
        if authors:
            parts.append(authors)
        if bib.title:
            parts.append(bib.title)
        if bib.journal:
            parts.append(bib.journal)
        elif bib.booktitle:
            parts.append(bib.booktitle)
        if bib.year:
            parts.append(str(bib.year))

        tail = []
        if bib.volume:
            tail.append(f"т. {bib.volume}")
        if bib.issue:
            tail.append(f"№ {bib.issue}")
        if bib.pages:
            tail.append(f"с. {bib.pages}")
        if tail:
            parts.append(", ".join(tail))

        result.append(
            {
                "label": bib.label,
                "citation": ". ".join(parts),
                "doi": bib.doi,
                "link": bib.link,
                "type": getattr(bib.bibtype, "bibtex_type", None),
            }
        )
    return result


def substance_list(request):
    query = request.GET.get("q", "").strip()
    thermos = (
        Thermo.objects.select_related("substance__molecule", "substance__phase", "datainfo")
        .annotate(default_name=_default_name_subquery())
        .order_by("substance__label")
    )
    if query:
        thermos = thermos.filter(
            Q(substance__label__icontains=query)
            | Q(substance__molecule__formula__icontains=query)
            | Q(default_name__icontains=query)
            | Q(substance__substancename__name_en__icontains=query)
            | Q(substance__substancename__name_ru__icontains=query)
        ).distinct()

    thermos = thermos[:100]
    return render(
        request,
        "ivtanthermo/substance_list.html",
        {
            "thermos": thermos,
            "query": query,
        },
    )


def thermo_detail(request, thermo_id):
    thermo = get_object_or_404(
        Thermo.objects.select_related("substance__molecule", "substance__phase", "datainfo"),
        pk=thermo_id,
    )
    substance = thermo.substance
    names = list(SubstanceName.objects.filter(substance=substance).order_by("-default_name", "name_en"))
    display_name = next(
        (
            item.name_ru or item.name_en
            for item in names
            if item.default_name and (item.name_ru or item.name_en)
        ),
        None,
    )
    display_name = display_name or (names[0].name_ru or names[0].name_en if names else substance.label)

    versions = list(
        Thermo.objects.filter(substance=substance)
        .select_related("datainfo")
        .order_by("-recommended", "-datainfo__modified")
    )
    molecule_prop = (
        MoleculeProp.objects.filter(molecule=substance.molecule)
        .select_related("datainfo")
        .order_by("-recommended", "id")
        .first()
    )
    coefficients = []
    for coef in (
        GibbsCoef.objects.filter(thermo=thermo)
        .select_related("approx", "cond_phase")
        .order_by("tmin", "id")
    ):
        data = list(coef.data or [])
        coefficients.append(
            {
                "approx_label": getattr(coef.approx, "label", ""),
                "tmin": float(coef.tmin) if coef.tmin is not None else None,
                "tmax": float(coef.tmax) if coef.tmax is not None else None,
                "coefficients": (data + [0.0] * 7)[:7],
                "phase": getattr(coef.cond_phase, "label", "") if coef.cond_phase_id else "",
                "formatted": [_format_scientific(value) for value in (data + [0.0] * 7)[:7]],
            }
        )

    chart_data = _build_chart_series(coefficients, (thermo.dfh0 or 0.0) / 1000)

    context = {
        "thermo": thermo,
        "substance": substance,
        "display_name": display_name,
        "names": names,
        "versions": versions,
        "property_rows": _build_property_rows(thermo, molecule_prop),
        "references": _build_references(thermo.datainfo),
        "coefficients": coefficients,
        "chart_data": chart_data,
        "phase_name": substance.phase.name_ru or substance.phase.name_en or substance.phase.label,
        "modified_at": thermo.datainfo.modified,
        "release_no": thermo.datainfo.release_no,
        "note_en": thermo.datainfo.note_en,
        "note_ru": thermo.datainfo.note_ru,
    }
    return render(request, "ivtanthermo/thermo_detail.html", context)
