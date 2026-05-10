from django import forms
from django.db import OperationalError, ProgrammingError

from ivtanthermo.charge_utils import parse_charge_from_label
from ivtanthermo.models import Substance

from .models import CustomSubstance
from .solver import EXAMPLES


MODE_CHOICES = [
    ("gibbs", "Gibbs minimization"),
    ("helmholtz", "Helmholtz minimization"),
]

FEED_BASIS_CHOICES = [
    ("mole", "Мольный состав"),
    ("mass", "Массовый состав, г"),
]


EXAMPLE_CHOICES = [("", "Manual input")] + [
    (filename, payload["label"]) for filename, payload in EXAMPLES.items()
]


class EquilibriumInputForm(forms.Form):
    example = forms.ChoiceField(choices=EXAMPLE_CHOICES, required=False)
    mode = forms.ChoiceField(choices=MODE_CHOICES, initial="gibbs")
    raw_input = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 18, "spellcheck": "false"}),
        required=False,
    )

    def clean(self):
        cleaned = super().clean()
        example = cleaned.get("example")
        raw_input = (cleaned.get("raw_input") or "").strip()
        if not example and not raw_input:
            raise forms.ValidationError("Provide input data or choose one of the bundled examples.")
        return cleaned


class DatabaseEquilibriumForm(forms.Form):
    mode = forms.ChoiceField(choices=MODE_CHOICES, initial="gibbs")
    temperature_start = forms.FloatField(min_value=1.0, initial=2000.0)
    temperature_end = forms.FloatField(min_value=1.0, initial=2000.0)
    temperature_step = forms.FloatField(min_value=0.1, initial=100.0)
    temperature_report = forms.FloatField(min_value=1.0, required=False)
    pressure_mpa = forms.FloatField(min_value=1e-9, initial=0.1)
    feed_basis = forms.ChoiceField(choices=FEED_BASIS_CHOICES, initial="mole", required=False)
    include_condensed = forms.BooleanField(required=False, initial=True)
    include_ions = forms.BooleanField(required=False, initial=False)
    feed_input = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 10, "spellcheck": "false"}),
        help_text="One substance per line: <label> <amount>",
    )

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("temperature_start")
        end = cleaned.get("temperature_end")
        step = cleaned.get("temperature_step")

        if start is None or end is None or step is None:
            return cleaned
        if end < start:
            raise forms.ValidationError("Temperature range end must be greater than or equal to start.")
        count = int(round((end - start) / step)) + 1
        if count > 400:
            raise forms.ValidationError("Temperature grid is too large.")
        return cleaned


def parse_element_counts_text(raw_text: str) -> dict[str, float]:
    counts: dict[str, float] = {}
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if not lines:
        raise forms.ValidationError("Укажите элементный состав вещества.")

    for index, line in enumerate(lines, start=1):
        normalized = line.replace("=", " ").replace(":", " ").replace(";", " ")
        parts = [part for part in normalized.split() if part]
        if len(parts) != 2:
            raise forms.ValidationError(
                f"Строка состава {index} должна иметь вид '<элемент> <количество>'."
            )
        symbol, value_text = parts
        try:
            value = float(value_text)
        except ValueError as exc:
            raise forms.ValidationError(f"Некорректное количество элемента в строке {index}.") from exc
        if value <= 0:
            raise forms.ValidationError(f"Количество элемента в строке {index} должно быть положительным.")
        counts[symbol] = counts.get(symbol, 0.0) + value

    return counts


def parse_gibbs_coefficients_text(raw_text: str) -> list[float]:
    tokens = [
        token
        for token in raw_text.replace(",", " ").replace(";", " ").split()
        if token
    ]
    if len(tokens) != 7:
        raise forms.ValidationError("Нужно указать ровно 7 коэффициентов Гиббса.")
    try:
        return [float(token) for token in tokens]
    except ValueError as exc:
        raise forms.ValidationError("Коэффициенты Гиббса должны быть числами.") from exc


class CustomSubstanceForm(forms.ModelForm):
    element_counts_input = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 5, "spellcheck": "false"}),
        help_text="По одной строке: <элемент> <количество>",
    )
    gibbs_coefficients_input = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 4, "spellcheck": "false"}),
        help_text="Ровно 7 коэффициентов через пробел или с новой строки",
    )

    class Meta:
        model = CustomSubstance
        fields = [
            "label",
            "display_name",
            "phase",
            "molar_mass",
            "dfh0",
            "tmin",
            "tmax",
            "note",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = kwargs.get("instance")
        if instance:
            self.fields["element_counts_input"].initial = "\n".join(
                f"{symbol} {amount:g}" for symbol, amount in (instance.element_counts or {}).items()
            )
            self.fields["gibbs_coefficients_input"].initial = "\n".join(
                f"{float(value):g}" for value in (instance.gibbs_coefficients or [])
            )

    def clean_label(self):
        label = (self.cleaned_data["label"] or "").strip()
        try:
            if Substance.objects.filter(label=label).exists():
                raise forms.ValidationError("В основном каталоге уже есть вещество с таким label.")
        except (OperationalError, ProgrammingError):
            pass
        queryset = CustomSubstance.objects.filter(label=label)
        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise forms.ValidationError("Пользовательское вещество с таким label уже существует.")
        return label

    def clean(self):
        cleaned = super().clean()
        tmin = cleaned.get("tmin")
        tmax = cleaned.get("tmax")
        if tmin is not None and tmax is not None and tmax < tmin:
            self.add_error("tmax", "Верхняя граница температуры должна быть не меньше нижней.")

        label = cleaned.get("label")
        phase = cleaned.get("phase")
        if label and phase and parse_charge_from_label(label) != 0 and phase != "g":
            self.add_error("phase", "Ионы и электроны в пользовательском наборе должны быть в газовой фазе.")

        if "element_counts_input" in cleaned:
            cleaned["element_counts"] = parse_element_counts_text(cleaned["element_counts_input"])
        if "gibbs_coefficients_input" in cleaned:
            cleaned["gibbs_coefficients"] = parse_gibbs_coefficients_text(cleaned["gibbs_coefficients_input"])
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.element_counts = self.cleaned_data["element_counts"]
        instance.gibbs_coefficients = self.cleaned_data["gibbs_coefficients"]
        if commit:
            instance.save()
        return instance
