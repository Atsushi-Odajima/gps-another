import unittest

from route_interpolator import (
    build_transmission_plan,
    haversine_meters,
    interpolate_route,
)


class RouteInterpolatorTests(unittest.TestCase):
    def test_haversine_returns_expected_order_of_magnitude(self):
        distance = haversine_meters((35.0, 139.0), (35.001, 139.0))
        self.assertGreater(distance, 100)
        self.assertLess(distance, 120)

    def test_interpolate_uses_speed_per_second_spacing(self):
        route = [(35.0, 139.0), (35.001, 139.0)]
        points = interpolate_route(route, speed_kmh=3.6, interval_seconds=1.0)

        self.assertGreater(len(points), 100)
        first_step = haversine_meters(
            (points[0].latitude, points[0].longitude),
            (points[1].latitude, points[1].longitude),
        )
        self.assertAlmostEqual(first_step, 1.0, delta=0.05)

    def test_build_transmission_plan_keeps_interval(self):
        route = [(35.0, 139.0), (35.0001, 139.0)]
        plan = build_transmission_plan(route, speed_kmh=5, interval_seconds=1.0)

        self.assertEqual(plan.interval_seconds, 1.0)
        self.assertEqual(plan.speed_kmh, 5)
        self.assertGreater(plan.total_distance_meters, 0)


if __name__ == "__main__":
    unittest.main()

