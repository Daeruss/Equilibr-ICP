from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from .models import SavedCalculation
from .solver import (
    EquilibriumResult,
    ParsedEquilibriumInput,
    _substance_charge,
    load_example_input,
    multiplier_rows,
    parse_equilibrium_input,
    parse_feed_input,
    phase_rows,
    result_rows,
    solve_equilibrium,
    temperature_points,
)


class EquilibriumSolverTests(SimpleTestCase):
    def test_parser_reads_example_dimensions(self):
        parsed = load_example_input("test11.dat")

        self.assertEqual(parsed.m, 3)
        self.assertEqual(parsed.k, 22)
        self.assertEqual(parsed.np, 2)
        self.assertEqual(parsed.nc, 7)
        self.assertEqual(parsed.phase_ranges, [(7, 18), (19, 21)])
        self.assertTrue(parsed.trailing_lines)

    def test_parse_manual_input(self):
        parsed = parse_equilibrium_input(
            "2 3 1 1 0\n"
            "A 0.0 1 0\n"
            "B 0.0 0 1\n"
            "AB -1.0 1 1\n"
            "2 3\n"
            "1.0\n"
            "1.0\n"
        )

        self.assertEqual(parsed.species, ["A", "B", "AB"])
        self.assertEqual(parsed.phase_ranges, [(1, 2)])
        self.assertEqual(parsed.element_amounts.tolist(), [1.0, 1.0])

    def test_gibbs_example_solves_and_preserves_balance(self):
        parsed = load_example_input("test1.dat")
        result = solve_equilibrium(parsed, mode="gibbs")
        rows = result_rows(result)

        self.assertTrue(result.success)
        self.assertLess(result.mass_balance_residual, 1e-8)
        self.assertEqual(rows[0]["species"], "C(c;graphite)")
        self.assertGreater(rows[0]["amount"], 0.9)
        self.assertEqual(rows[1]["species"], "CO(g)")
        self.assertGreater(rows[1]["amount"], 0.9)

    def test_helmholtz_example_solves(self):
        parsed = load_example_input("test1vi.dat")
        result = solve_equilibrium(parsed, mode="helmholtz")

        self.assertTrue(result.success)
        self.assertLess(result.mass_balance_residual, 1e-8)
        self.assertEqual(len(result.phase_amounts), parsed.np)

    def test_parse_feed_input(self):
        entries = parse_feed_input("C2O(g) 1.0\nO2(g) 0.25\n")

        self.assertEqual(entries, [("C2O(g)", 1.0), ("O2(g)", 0.25)])

    def test_substance_charge_parser(self):
        self.assertEqual(_substance_charge(SimpleNamespace(label="e(-g)")), -1)
        self.assertEqual(_substance_charge(SimpleNamespace(label="H(+g)")), 1)
        self.assertEqual(_substance_charge(SimpleNamespace(label="O(+2g)")), 2)
        self.assertEqual(_substance_charge(SimpleNamespace(label="U(+g;+3)")), 3)
        self.assertEqual(_substance_charge(SimpleNamespace(label="CO(g)")), 0)

    def test_temperature_points_builder(self):
        self.assertEqual(temperature_points(1000.0, 1200.0, 100.0), [1000.0, 1100.0, 1200.0])


class EquilibriumViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.substance_labels_patcher = patch("equilibrium.views.database_substance_labels")
        self.database_substance_labels_mock = self.substance_labels_patcher.start()
        self.database_substance_labels_mock.return_value = ["C2O(g)", "CO(g)", "O2(g)"]
        self.addCleanup(self.substance_labels_patcher.stop)

    @staticmethod
    def make_snapshot(temperature=2000.0, co_amount=1.0, graphite_amount=1.0):
        parsed = ParsedEquilibriumInput(
            raw_text="",
            m=2,
            k=2,
            np=1,
            nc=1,
            ion=0,
            species=["C(c;graphite)", "CO(g)"],
            g=np.array([0.0, -1.0]),
            formula_matrix=np.array([[1.0, 0.0], [1.0, 1.0]]),
            phase_ranges=[(1, 1)],
            element_amounts=np.array([1.0, 1.0]),
            trailing_lines=[f"temperature {temperature}"],
        )
        result = EquilibriumResult(
            parsed=parsed,
            mode="gibbs",
            objective_value=-1.0,
            species_amounts=np.array([graphite_amount, co_amount]),
            phase_amounts=np.array([co_amount]),
            lagrange_multipliers=np.array([0.1, 0.2]),
            success=True,
            status=1,
            message="ok",
            iterations=5,
            optimality=0.0,
            mass_balance_residual=0.0,
        )
        return {
            "temperature": temperature,
            "parsed": parsed,
            "result": result,
            "rows": result_rows(result),
            "phases": phase_rows(result),
            "multipliers": multiplier_rows(result),
        }

    def test_get_calculator_page(self):
        response = self.client.get(reverse("equilibrium-calculator"))
        content = response.content.decode("utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Калькулятор гетерогенного равновесия")
        self.assertContains(response, "Давление, MPa")
        self.assertContains(response, "Ручной ввод `.dat`")
        self.assertContains(response, 'list="db-substance-options"', html=False)
        self.assertContains(response, "Добавить вещество")
        self.assertContains(response, "Сохранённые расчёты")
        self.assertContains(response, '<option value="C2O(g)"></option>', html=False)
        self.assertLess(content.index("Example:\nC2O(g) 1.0"), content.index('id="id_feed_input"'))
        self.assertLess(content.index("line 1: m k np nc ion"), content.index('id="id_raw_input"'))

    @patch("equilibrium.views.run_database_series")
    def test_post_database_runs_temperature_series(self, run_database_series_mock):
        run_database_series_mock.return_value = [
            self.make_snapshot(temperature=1800.0, graphite_amount=1.2, co_amount=0.8),
            self.make_snapshot(temperature=2000.0, graphite_amount=0.9, co_amount=1.1),
        ]

        response = self.client.post(
            reverse("equilibrium-calculator"),
            {
                "source": "database",
                "action": "calculate",
                "mode": "gibbs",
                "temperature_start": "1800",
                "temperature_end": "2000",
                "temperature_step": "200",
                "pressure_mpa": "0.2",
                "include_condensed": "on",
                "feed_input": "C2O(g) 1.0",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Зависимость мольных долей веществ от температуры")
        self.assertContains(response, "Состав при опорной температуре")
        self.assertContains(response, "Опорная температура")
        run_database_series_mock.assert_called_once()

    def test_post_example_runs_solver(self):
        response = self.client.post(
            reverse("equilibrium-calculator"),
            {"source": "manual", "action": "calculate", "example": "test1.dat", "mode": "gibbs", "raw_input": ""},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Равновесный состав")
        self.assertContains(response, "C(c;graphite)")

    def test_save_manual_calculation(self):
        response = self.client.post(
            reverse("equilibrium-calculator"),
            {
                "source": "manual",
                "action": "save",
                "example": "test1.dat",
                "mode": "gibbs",
                "raw_input": "",
                "save_name_manual": "Manual smoke save",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(SavedCalculation.objects.count(), 1)
        saved = SavedCalculation.objects.get()
        self.assertEqual(saved.name, "Manual smoke save")
        self.assertEqual(saved.source, SavedCalculation.SOURCE_MANUAL)
        self.assertEqual(saved.example_name, "test1.dat")
        self.assertContains(response, "Calculation saved as")

    @patch("equilibrium.views.run_database_series")
    def test_save_database_calculation_with_pressure_and_range(self, run_database_series_mock):
        run_database_series_mock.return_value = [self.make_snapshot(temperature=2000.0)]

        response = self.client.post(
            reverse("equilibrium-calculator"),
            {
                "source": "database",
                "action": "save",
                "mode": "gibbs",
                "temperature_start": "1800",
                "temperature_end": "2200",
                "temperature_step": "200",
                "pressure_mpa": "0.3",
                "include_condensed": "on",
                "feed_input": "C2O(g) 1.0",
                "save_name_database": "DB smoke save",
            },
        )

        self.assertEqual(response.status_code, 200)
        saved = SavedCalculation.objects.get(name="DB smoke save")
        self.assertEqual(saved.source, SavedCalculation.SOURCE_DATABASE)
        self.assertEqual(saved.feed_input, "C2O(g) 1.0")
        self.assertEqual(saved.temperature_start, 1800.0)
        self.assertEqual(saved.temperature_end, 2200.0)
        self.assertEqual(saved.temperature_step, 200.0)
        self.assertEqual(saved.pressure_mpa, 0.3)
        self.assertContains(response, "Calculation saved as")

    def test_load_saved_manual_calculation(self):
        parsed = load_example_input("test1.dat")
        saved = SavedCalculation.objects.create(
            name="Saved example",
            source=SavedCalculation.SOURCE_MANUAL,
            mode="gibbs",
            raw_input=parsed.raw_text,
        )

        response = self.client.get(reverse("equilibrium-calculator"), {"saved": saved.id})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Saved example")
        self.assertContains(response, "Равновесный состав")
        self.assertContains(response, "C(c;graphite)")
