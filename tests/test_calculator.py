import unittest
from app.calculator import add, subtract

class CalculatorTests(unittest.TestCase):
    def test_add_positive_numbers(self):
        self.assertEqual(add(1, 2), 3)

    def test_add_negative_numbers(self):
        self.assertEqual(add(-1, -2), -3)

    def test_add_zero(self):
        self.assertEqual(add(0, 0), 0)

    def test_subtract_positive_numbers(self):
        self.assertEqual(subtract(5, 3), 2)

    def test_subtract_negative_numbers(self):
        self.assertEqual(subtract(-5, -3), -2)

    def test_subtract_zero(self):
        self.assertEqual(subtract(0, 5), -5)

if __name__ == '__main__':
    unittest.main()