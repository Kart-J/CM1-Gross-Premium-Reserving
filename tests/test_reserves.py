import unittest
from main import factors, gross_premium, prospective_reserve, retrospective_reserves


class TestCM1Reserving(unittest.TestCase):
    def setUp(self):
        self.a = dict(pricing_interest=.04, initial_fixed_expense=350,
                      initial_premium_pct=.25, renewal_fixed_expense=120,
                      renewal_premium_pct=.04, stress_interest=.03,
                      stress_mortality_multiplier=1.15)
        self.q = {age: 0.0005 * 1.08**(age - 30) for age in range(20, 90)}
        self.age, self.term, self.s = 40, 10, 100000
        self.g, _, _ = gross_premium(self.s, self.age, self.term, self.a, self.q)

    def test_endowment_value_one_in_last_year(self):
        a, A = factors(49, 1, .04, self.q)
        self.assertAlmostEqual(a, 1)
        self.assertAlmostEqual(A, 1 / 1.04)

    def test_initial_prospective_reserve_zero_on_pricing_basis(self):
        self.assertAlmostEqual(prospective_reserve(0, self.age, self.term,
            self.s, self.g, self.a, self.q), 0, places=7)

    def test_retro_equals_prospective(self):
        retro = retrospective_reserves(self.age, self.term, self.s, self.g, self.a, self.q)
        for t in range(self.term):
            pro = prospective_reserve(t, self.age, self.term,
                                      self.s, self.g, self.a, self.q)
            self.assertAlmostEqual(pro, retro[t], places=6)

    def test_maturity_reserve_zero(self):
        self.assertEqual(prospective_reserve(self.term, self.age, self.term,
            self.s, self.g, self.a, self.q), 0)

    def test_stress_changes_reserve(self):
        base = prospective_reserve(4, self.age, self.term, self.s, self.g, self.a, self.q)
        stress = prospective_reserve(4, self.age, self.term, self.s, self.g,
                                     self.a, self.q, stressed=True)
        self.assertNotAlmostEqual(base, stress, places=2)


if __name__ == '__main__':
    unittest.main()
