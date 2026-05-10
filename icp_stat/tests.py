import pandas as pd
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from equilibrium.models import SavedCalculation
from .models import ParsedPoint
from .views import (
    build_dataframe_from_equilibrium_saved,
    parse_temperature_points,
    parse_text_points,
)
from ivtanthermo.charge_utils import parse_charge_from_label


class IcpStatParsingTests(TestCase):
    def test_parse_text_points(self):
        dataframe = parse_text_points("20 200\n10 100\n")

        self.assertEqual(list(dataframe["point_index"]), [2, 1])
        self.assertEqual(list(dataframe["x_value"]), [10.0, 20.0])
        self.assertEqual(list(dataframe["y_value"]), [100.0, 200.0])

    def test_parse_temperature_points(self):
        dataframe = parse_temperature_points("600 20 170\n300 10 50\n300 20 120\n")

        self.assertEqual(list(dataframe["temperature"]), ["300", "300", "600"])
        self.assertEqual(list(dataframe["point_index"]), [1, 2, 1])

    def test_substance_label_charge_parser(self):
        self.assertEqual(parse_charge_from_label("H(+g)"), 1)
        self.assertEqual(parse_charge_from_label("H2(+g)"), 1)
        self.assertEqual(parse_charge_from_label("O(+2g)"), 2)
        self.assertEqual(parse_charge_from_label("U(+g;+3)"), 3)
        self.assertEqual(parse_charge_from_label("e(-g)"), -1)
        self.assertEqual(parse_charge_from_label("H2O(g)"), 0)

    @patch("icp_stat.views._species_mass_to_charge_map")
    def test_build_dataframe_from_equilibrium_saved_uses_only_ions(self, mass_to_charge_map_mock):
        saved = SavedCalculation.objects.create(
            name="Ion-only import",
            source=SavedCalculation.SOURCE_DATABASE,
            mode="gibbs",
            result_payload={
                "temperature_series_rows": [
                    {"temperature": 300.0, "species": "Ar(+g)", "amount": 0.4, "mole_fraction": 0.4},
                    {"temperature": 300.0, "species": "Ar(g)", "amount": 0.6, "mole_fraction": 0.6},
                ]
            },
        )
        mass_to_charge_map_mock.return_value = {"Ar(+g)": 39.948}

        dataframe = build_dataframe_from_equilibrium_saved(saved)

        self.assertEqual(list(dataframe["temperature"]), ["300"])
        self.assertEqual(list(dataframe["x_value"]), [39.948])
        self.assertEqual(list(dataframe["y_value"]), [0.4])
        mass_to_charge_map_mock.assert_called_once()

    @patch("icp_stat.views._species_mass_to_charge_map")
    def test_build_dataframe_from_equilibrium_saved_skips_hidden_trace_species(self, mass_to_charge_map_mock):
        saved = SavedCalculation.objects.create(
            name="Trace species import",
            source=SavedCalculation.SOURCE_DATABASE,
            mode="gibbs",
            result_payload={
                "temperature_series_rows": [
                    {"temperature": 300.0, "species": "H(+g)", "amount": 0.2, "mole_fraction": 0.2},
                    {"temperature": 300.0, "species": "H3(+g)", "amount": 1e-20, "mole_fraction": 1e-20},
                ]
            },
        )
        mass_to_charge_map_mock.return_value = {"H(+g)": 1.0079, "H3(+g)": 3.0237}

        dataframe = build_dataframe_from_equilibrium_saved(saved)

        self.assertEqual(list(dataframe["x_value"]), [1.0079])
        self.assertEqual(list(dataframe["y_value"]), [0.2])


class IcpStatViewTests(TestCase):
    def test_get_page(self):
        saved = SavedCalculation.objects.create(
            name="Saved Equilibr result",
            source=SavedCalculation.SOURCE_DATABASE,
            mode="gibbs",
            result_payload={"temperature_series_rows": [{"temperature": 300.0, "species": "CO(g)", "mole_fraction": 0.5}]},
        )
        response = self.client.get(reverse("icp_stat:graph-page"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ICP Stat")
        self.assertContains(response, "Импорт из Equilibr")
        self.assertContains(response, saved.name)

    def test_post_text_inputs_creates_processed_points(self):
        response = self.client.post(
            reverse("icp_stat:graph-page"),
            {
                "file1_text": "10 100\n20 200\n",
                "file2_text": "300 10 50\n300 20 120\n",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(ParsedPoint.objects.filter(source="file1").exists())
        self.assertTrue(ParsedPoint.objects.filter(source="file2").exists())
        self.assertTrue(ParsedPoint.objects.filter(source="file4").exists())

    @patch("icp_stat.views.build_dataframe_from_equilibrium_saved")
    def test_import_from_equilibr_creates_file2_points(self, build_dataframe_mock):
        saved = SavedCalculation.objects.create(
            name="Saved Equilibr result",
            source=SavedCalculation.SOURCE_DATABASE,
            mode="gibbs",
            result_payload={"temperature_series_rows": [{"temperature": 300.0, "species": "CO(g)", "mole_fraction": 0.5}]},
        )
        build_dataframe_mock.return_value = pd.DataFrame(
            [
                {
                    "point_index": 1,
                    "temperature": "300",
                    "mass_to_charge": 28.0,
                    "x_value": 28.0,
                    "y_value": 0.5,
                }
            ]
        )

        response = self.client.post(
            reverse("icp_stat:graph-page"),
            {
                "action": "import_equilibrium",
                "batch_id": "eqbatch",
                "equilibrium_calculation_id": str(saved.id),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(ParsedPoint.objects.filter(source="file2", batch_id="eqbatch").exists())
        build_dataframe_mock.assert_called_once()
