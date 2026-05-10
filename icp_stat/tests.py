from django.test import TestCase
from django.urls import reverse

from .models import ParsedPoint
from .views import parse_temperature_points, parse_text_points


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


class IcpStatViewTests(TestCase):
    def test_get_page(self):
        response = self.client.get(reverse("icp_stat:graph-page"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ICP Stat")

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
