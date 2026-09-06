import unittest
from utils import parse_time_to_seconds, format_time_str

class TestAutoDeleteHelpers(unittest.TestCase):
    def test_parse_time_to_seconds(self):
        self.assertEqual(parse_time_to_seconds("300"), 300)
        self.assertEqual(parse_time_to_seconds("30s"), 30)
        self.assertEqual(parse_time_to_seconds("5m"), 300)
        self.assertEqual(parse_time_to_seconds("15m"), 900)
        self.assertEqual(parse_time_to_seconds("1h"), 3600)
        with self.assertRaises(ValueError):
            parse_time_to_seconds("invalid")

    def test_format_time_str(self):
        self.assertEqual(format_time_str(30), "30 seconds")
        self.assertEqual(format_time_str(60), "1 minute")
        self.assertEqual(format_time_str(300), "5 minutes")
        self.assertEqual(format_time_str(900), "15 minutes")
        self.assertEqual(format_time_str(3660), "1 hour 1 minute")

if __name__ == "__main__":
    unittest.main()
