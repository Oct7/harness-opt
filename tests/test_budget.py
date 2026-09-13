import unittest
from harness_opt.budget import Budget, BudgetExceeded

class BudgetTests(unittest.TestCase):
    def test_reserve_settle_unknown(self):
        budget = Budget(1, 10)
        token = budget.reserve(.8)
        with self.assertRaises(BudgetExceeded):
            budget.reserve(.3)
        budget.settle(token, .2)
        self.assertAlmostEqual(budget.remaining, .8)
        token = budget.reserve(.1)
        budget.settle(token, None)
        with self.assertRaises(BudgetExceeded):
            budget.reserve(0)

    def test_invalid(self):
        for value in (0, -1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                Budget(value, 10)

    def test_journal_before_dispatch_and_after_settle(self):
        states=[]
        budget=Budget(1,10,on_change=states.append)
        token=budget.reserve(.4)
        self.assertEqual(states[-1]['reservations'],{token:.4})
        budget.settle(token,.2)
        self.assertEqual(states[-1],{'spent':.2,'reservations':{},'uncertain':False})

    def test_time_only_budget_cannot_authorize_paid_dispatch(self):
        budget = Budget(None, 10)
        self.assertGreater(budget.time_left, 0)
        self.assertIsNone(budget.remaining)
        with self.assertRaises(BudgetExceeded):
            budget.reserve(.1)
