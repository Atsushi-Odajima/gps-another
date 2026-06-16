import unittest

from route_service import RouteMode, mode_for_speed


class RouteServiceTests(unittest.TestCase):
    def test_speed_mode_selection(self):
        self.assertEqual(mode_for_speed(1), RouteMode.WALK)
        self.assertEqual(mode_for_speed(6), RouteMode.WALK)
        self.assertEqual(mode_for_speed(7), RouteMode.BICYCLE)
        self.assertEqual(mode_for_speed(29), RouteMode.BICYCLE)
        self.assertEqual(mode_for_speed(30), RouteMode.CAR)
        self.assertEqual(mode_for_speed(40), RouteMode.CAR)

    def test_speed_mode_rejects_out_of_range(self):
        with self.assertRaises(ValueError):
            mode_for_speed(0)
        with self.assertRaises(ValueError):
            mode_for_speed(41)


if __name__ == "__main__":
    unittest.main()

