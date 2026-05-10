from django.contrib import admin
from django.db import models
from django.test import RequestFactory, SimpleTestCase, TestCase

from . import admin as admin_module
from . import models as app_models
from .charge_utils import parse_charge_from_label
from . import views


class AdminRegistrationTests(TestCase):
    def test_registers_all_models_without_composite_primary_key(self):
        eligible_models = {
            model
            for model in app_models.__dict__.values()
            if isinstance(model, type)
            and issubclass(model, models.Model)
            and model is not models.Model
            and not isinstance(model._meta.pk, models.CompositePrimaryKey)
        }

        self.assertTrue(eligible_models)
        self.assertTrue(eligible_models.issubset(admin.site._registry.keys()))

    def test_skips_models_with_composite_primary_key(self):
        composite_models = {
            model
            for model in app_models.__dict__.values()
            if isinstance(model, type)
            and issubclass(model, models.Model)
            and model is not models.Model
            and isinstance(model._meta.pk, models.CompositePrimaryKey)
        }

        self.assertTrue(composite_models)
        self.assertTrue(composite_models.isdisjoint(admin.site._registry.keys()))

    def test_admin_is_read_only(self):
        registry = admin.site._registry
        model_admin = registry[app_models.Substance]
        request = RequestFactory().get("/admin/")
        request.user = type("User", (), {"is_active": True, "is_staff": True})()

        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_change_permission(request))
        self.assertFalse(model_admin.has_delete_permission(request))
        self.assertTrue(model_admin.has_view_permission(request))
        self.assertEqual(model_admin.get_model_perms(request), {"view": True})

    def test_helper_detects_composite_pk(self):
        self.assertTrue(admin_module._is_composite_pk(app_models.AclUserGroup))
        self.assertFalse(admin_module._is_composite_pk(app_models.Substance))


class ThermoViewHelperTests(SimpleTestCase):
    def test_parse_charge_from_label(self):
        self.assertEqual(parse_charge_from_label("H(+g)"), 1)
        self.assertEqual(parse_charge_from_label("H2(+g)"), 1)
        self.assertEqual(parse_charge_from_label("O(+2g)"), 2)
        self.assertEqual(parse_charge_from_label("U(+g;+3)"), 3)
        self.assertEqual(parse_charge_from_label("e(-g)"), -1)
        self.assertEqual(parse_charge_from_label("H2O(g)"), 0)

    def test_build_temperature_grid_keeps_bounds(self):
        grid = views._build_temperature_grid(298.15, 1500, points=5)

        self.assertEqual(grid[0], 298.15)
        self.assertEqual(grid[-1], 1500.0)
        self.assertEqual(len(grid), 5)

    def test_build_chart_series_from_coefficients(self):
        coefficients = [
            {
                "tmin": 298.15,
                "tmax": 500.0,
                "coefficients": [278.592, 24.877, -0.000122122, -0.0314325, 122.121, -289.562, 361.802],
            }
        ]

        datasets = views._build_chart_series(coefficients, 234.118)

        self.assertIn("cp", datasets)
        self.assertIn("phi", datasets)
        self.assertTrue(datasets["cp"])
        self.assertEqual(datasets["cp"][0]["x"], 298.15)
        self.assertIn("interval", datasets["cp"][0])

    def test_build_property_rows_skips_missing_values(self):
        thermo = type(
            "ThermoStub",
            (),
            {
                "dfh0": 1000.0,
                "dfh298": None,
                "cp298": 20.0,
                "s298": None,
                "dh298": 3000.0,
                "drh298": None,
            },
        )()
        molecule_prop = type("MoleculePropStub", (), {"mass": 18.0, "nucl_entropy": None})()

        rows = views._build_property_rows(thermo, molecule_prop)

        self.assertEqual([row["label"] for row in rows], [
            "Молекулярная масса",
            "Энтальпия образования, Delta_fH(0)",
            "Изобарная теплоемкость, Cp(298.15 K)",
            "Приращение энтальпии, H(298.15) - H(0)",
        ])
