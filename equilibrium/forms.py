from django import forms

from .solver import EXAMPLES


MODE_CHOICES = [
    ("gibbs", "Gibbs minimization"),
    ("helmholtz", "Helmholtz minimization"),
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
    pressure_mpa = forms.FloatField(min_value=1e-9, initial=0.1)
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
