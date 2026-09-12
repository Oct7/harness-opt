"""Thread-safe, conservative reservations shared by every evaluation call."""
import math
import threading
import time
import uuid


class BudgetExceeded(RuntimeError):
    pass


class Budget:
    def __init__(self, limit_usd, time_limit, on_change=None):
        if not all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in (limit_usd, time_limit)):
            raise ValueError('Budget and time limit must be finite and positive')
        self.limit_usd = limit_usd
        self.deadline = time.monotonic() + time_limit
        self.spent = 0.0
        self.reservations = {}
        self.lock = threading.RLock()
        self.uncertain = False
        self.on_change = on_change

    @property
    def remaining(self):
        with self.lock:
            return max(0.0, self.limit_usd - self.spent - sum(self.reservations.values())) if not self.uncertain else 0.0

    @property
    def time_left(self):
        return max(0.0, self.deadline - time.monotonic())

    def reserve(self, max_cost):
        with self.lock:
            if not isinstance(max_cost, (int, float)) or isinstance(max_cost, bool) or not math.isfinite(max_cost) or max_cost < 0:
                raise BudgetExceeded('Unknown maximum cost; automatic call excluded')
            if self.uncertain or not self.time_left or max_cost > self.remaining:
                raise BudgetExceeded('Budget or time limit reached')
            token = uuid.uuid4().hex
            self.reservations[token] = max_cost
            self._journal()
            return token

    def settle(self, token, actual_cost):
        with self.lock:
            reserved = self.reservations.pop(token)
            if not isinstance(actual_cost, (int, float)) or isinstance(actual_cost, bool) or not math.isfinite(actual_cost) or actual_cost < 0:
                self.spent += reserved
                self.uncertain = True
                self._journal()
                return
            self.spent += actual_cost
            if actual_cost > reserved + 1e-9:
                self.uncertain = True

            self._journal()

    def _journal(self):
        if self.on_change:
            self.on_change({'spent': self.spent, 'reservations': dict(self.reservations), 'uncertain': self.uncertain})
