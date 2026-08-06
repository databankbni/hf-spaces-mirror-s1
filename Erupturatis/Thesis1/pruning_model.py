"""
pruning_model.py

Pure-python evaluation of the calibrated unstructured pruning law (M2).
Vendored copy of pruning_recommender/model.py so the Hugging Face Space is
self-contained (stdlib only; no numpy/torch at query time).

    R(S)   = ln(1 - S) / ln(1 - rho)             (rounds to reach sparsity S)
    f      = E / R(S)                             (epochs per round given a budget E)
    d      = (1 - S) * 100                        (weight density in percent)
    d50(f) = 10 ** (c0 - c1 * (1 - exp(-f / tau)))
    A(d,f) = A_ch + (A_ceil - A_ch) / (1 + (d50(f)/d) ** k) ** m

A_ch = 100 / classes is the chance floor; A_ceil, c0, c1, k, m and the
saturation constant tau are calibrated per (network, criterion). The per-round
pruning rate rho is calibrated per network and held fixed for a task; reaching a
higher sparsity means running more rounds, which under a fixed epoch budget E
means fewer fine-tuning epochs per round and therefore less recovery.

The cliff-shift coefficient c1 may take either sign. c1 > 0 means more retraining
deepens the reachable sparsity (Taylor); c1 <= 0 means it does not, and can make
the collapse shallower (magnitude).
"""

import os
import json
import math

CARDS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cards.json')


def load_cards(path=CARDS_PATH):
    with open(path) as fh:
        return json.load(fh)


def rounds(S, rho):
    """Number of constant-rate rounds to reach sparsity S."""
    if not 0.0 < S < 1.0:
        raise ValueError('sparsity must lie in (0, 1)')
    return math.log(1.0 - S) / math.log(1.0 - rho)


class Recommender:
    """Query interface over one (network, criterion) calibrated M2 card."""

    def __init__(self, network, criterion, cards=None):
        cards = cards or load_cards()
        # Effective epochs-per-round are capped at the longest calibrated schedule:
        # the law is fit on f in {1, 5} and validated at f = 3, so beyond f = 5 it is
        # extrapolating. For c1 < 0 criteria (magnitude) that extrapolation drives the
        # cliff shallow enough to collapse accuracy to chance, which is an artifact, not
        # a measured effect. Holding f at the calibrated edge yields a saturating, honest
        # prediction (extra epochs simply stop changing the answer).
        self.f_cap = cards['model']['schedules_f']['long']
        # Effective epochs-per-round are also floored at the shortest calibrated schedule
        # (f = 1): a budget so small that it gives less than one fine-tuning epoch per
        # round is below anything that was measured, so the prediction is held at the
        # f = 1 edge rather than extrapolated into the untested sub-epoch regime.
        self.f_lo = cards['model']['schedules_f']['short']
        net = cards['networks'][network]
        self.rho = net['rho']
        self.network = network
        self.criterion = criterion
        self.classes = net['classes']
        self.A_ch = 100.0 / net['classes']
        self.meta = {k: net[k] for k in
                     ('title', 'dataset', 'classes', 'baseline_acc',
                      'dense_epochs', 'exp_rate')}
        c = net['criteria'][criterion]
        self.A_ceil = c['A_ceil']
        self.c0 = c['c0']
        self.c1 = c['c1']
        self.k = c['k']
        self.m = c['m']
        self.tau = c['tau']
        self.s_lo = c['s_lo']
        self.s_hi = c['s_hi']
        self.band_rmse = c['band_rmse']
        self.dense_flops = c['dense_flops']

    # primitives
    def log_d50(self, f):
        """log10 of the cliff-midpoint density (%) at f epochs per round."""
        return self.c0 - self.c1 * (1.0 - math.exp(-f / self.tau))

    def d50(self, f):
        return 10.0 ** self.log_d50(f)

    def accuracy(self, S, f):
        """M2 accuracy at sparsity S and f epochs per round."""
        d = (1.0 - S) * 100.0
        log10_d = math.log10(max(d, 1e-12))
        log10_ratio = self.k * (self.log_d50(f) - log10_d)   # log10 (d50/d)^k
        if log10_ratio > 150.0:                              # deep tail underflow
            return self.A_ch
        ratio = 10.0 ** log10_ratio
        denom_log = self.m * math.log10(1.0 + ratio)         # log10 (1+ratio)^m
        A = self.A_ch + (self.A_ceil - self.A_ch) * 10.0 ** (-denom_log)
        return max(self.A_ch, min(self.A_ceil, A))

    def rounds(self, S):
        return rounds(S, self.rho)

    def epochs_per_round(self, S, E):
        return E / self.rounds(S)

    # case: fix (S, E) -> predict accuracy
    def predict_accuracy(self, S, E):
        f = self.epochs_per_round(S, E)
        f_eval = min(max(f, self.f_lo), self.f_cap)
        return self.accuracy(S, f_eval)

    # case: fix (S, A) -> required epoch budget
    def required_budget(self, S, A_target):
        """Return (epochs, note). epochs is always >= f_lo * R(S) (the minimum
        calibrated effort) or None (target unreachable). The law was calibrated
        on f in {1, 5} epochs per round; f=0 (no retraining) is a qualitatively
        different regime and is never used."""
        if A_target >= self.A_ceil:
            return None, (f'unreachable: ceiling at this criterion is '
                          f'{self.A_ceil:.2f}%')
        if A_target <= self.A_ch:
            f = self.f_lo
            return f * self.rounds(S), 'ok'

        d = (1.0 - S) * 100.0
        y = (A_target - self.A_ch) / (self.A_ceil - self.A_ch)   # in (0, 1)
        ratio_needed = y ** (-1.0 / self.m) - 1.0                # > 0
        target_log_d50 = math.log10(d) + (1.0 / self.k) * math.log10(ratio_needed)

        if self.c1 > 0:
            g = (self.c0 - target_log_d50) / self.c1          # need exp(-f/tau)=1-g
            if g <= 0.0:
                f = self.f_lo
            elif g >= 1.0:
                return None, ('unreachable at any budget: target is deeper than '
                              'the saturated cliff this criterion can reach')
            else:
                f = -self.tau * math.log(1.0 - g)
        else:
            if target_log_d50 >= self.c0 - 1e-12:
                f = self.f_lo
            else:
                return None, ('unreachable: with c1 <= 0 extra retraining cannot '
                              'reach this depth; lower the sparsity instead')
        if f > self.f_cap + 1e-9:
            return None, (f'unreachable within the calibrated effort: needs more than '
                          f'{self.f_cap:g} epochs per round; lower the sparsity instead')
        # Floor to the minimum calibrated effort (1 epoch per round).
        f = max(f, self.f_lo)
        return f * self.rounds(S), 'ok'

    # case: fix (E, A) -> maximum achievable sparsity
    def max_sparsity(self, E, A_target, steps=2000):
        """Largest sparsity in the calibrated range whose predicted accuracy
        meets A_target under budget E, found by scanning the range."""
        best = None
        for i in range(steps + 1):
            S = self.s_lo + (self.s_hi - self.s_lo) * i / steps
            if self.predict_accuracy(S, E) >= A_target:
                best = S
        return best

    # frontiers (1 fixed target)
    def frontier_fix_sparsity(self, S, e_max=None, n=8):
        """Accuracy as a function of budget at fixed sparsity."""
        R = self.rounds(S)
        e_max = e_max if e_max is not None else 6.0 * R   # up to ~6 ep/round
        return [(E, self.predict_accuracy(S, E))
                for E in _linspace(0.0, e_max, n)]

    def frontier_fix_budget(self, E, n=8):
        """Best achievable accuracy across the sparsity range at fixed budget."""
        return [(S, self.predict_accuracy(S, E))
                for S in _linspace(self.s_lo, self.s_hi, n)]

    def frontier_fix_accuracy(self, A_target, n=8):
        """Required budget across the sparsity range to hit a target accuracy."""
        out = []
        for S in _linspace(self.s_lo, self.s_hi, n):
            E, note = self.required_budget(S, A_target)
            out.append((S, E, note))
        return out


def _linspace(a, b, n):
    if n == 1:
        return [a]
    return [a + (b - a) * i / (n - 1) for i in range(n)]
