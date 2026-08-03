"""
FTMO Rule Enforcer
Hard limits baked into execution — never trust strategy layer alone.

FTMO rules:
  Max daily loss:  5%  of initial balance
  Max total DD:   10%  of initial balance
  Profit target:  10%  (Phase 1) / 5% (Phase 2)
"""


class FTMORules:
    def __init__(self, initial_balance: float, phase: int = 1):
        self.initial = initial_balance
        self.phase = phase
        self.daily_start_balance: float = initial_balance  # reset each day

        # Hard limits with 0.5% buffer so we stop BEFORE FTMO cuts us
        self.max_daily_loss_pct = 0.045   # FTMO is 5%, we stop at 4.5%
        self.max_total_dd_pct = 0.095     # FTMO is 10%, we stop at 9.5%
        self.profit_target_pct = 0.10 if phase == 1 else 0.05

    # Call at session start (once per trading day)
    def reset_daily(self, current_balance: float):
        self.daily_start_balance = current_balance

    def daily_loss_ok(self, current_balance: float) -> bool:
        loss_pct = (self.daily_start_balance - current_balance) / self.initial
        return loss_pct < self.max_daily_loss_pct

    def total_dd_ok(self, current_balance: float) -> bool:
        dd_pct = (self.initial - current_balance) / self.initial
        return dd_pct < self.max_total_dd_pct

    def target_hit(self, current_balance: float) -> bool:
        gain_pct = (current_balance - self.initial) / self.initial
        return gain_pct >= self.profit_target_pct

    def can_trade(self, current_balance: float) -> tuple[bool, str]:
        if not self.daily_loss_ok(current_balance):
            return False, "Daily loss limit hit — no more trades today"
        if not self.total_dd_ok(current_balance):
            return False, "Total drawdown limit hit — account locked"
        if self.target_hit(current_balance):
            return False, "Profit target reached — stop trading, submit account"
        return True, "ok"

    def position_size(self, balance: float, risk_pct: float,
                      sl_pips: float, pip_value: float) -> float:
        """Lot size so 1 loss = risk_pct of balance."""
        risk_amount = balance * risk_pct
        # ponytail: pip_value varies by pair/broker — caller must pass correct value
        lots = risk_amount / (sl_pips * pip_value)
        return round(max(0.01, lots), 2)
