"""The execution safety rails must hold — these are the guards that protect real money."""
import app.executor as ex


class _FakeMT5:
    def __init__(self, **kw):
        self._acct = kw.get("account")
        self._limits = kw.get("limits", {"min_lot": 0.01, "max_lot": 30.0, "lot_step": 0.01})
        self._avail = kw.get("available", True)

    def is_available(self): return self._avail
    def account(self): return self._acct
    def symbol_limits(self, a): return self._limits
    def resolve_symbol(self, a): return "XAUUSD"


def _acct(kind="DEMO", trade_allowed=True, balance=10000.0):
    return {"kind": kind, "is_real": kind == "REAL", "trade_allowed": trade_allowed,
            "balance": balance, "equity": balance, "server": "test", "currency": "USD"}


def _patch(monkeypatch, fake):
    import app.connectors.mt5 as mt5mod
    for name in ("is_available", "account", "symbol_limits", "resolve_symbol"):
        monkeypatch.setattr(mt5mod, name, getattr(fake, name))


SIG = {"asset": "gold", "direction": "BUY", "entry": 4000.0, "stop_loss": 3990.0,
       "take_profit": 4020.0, "source": "monster"}


def test_real_account_blocked_unless_explicitly_allowed(monkeypatch):
    monkeypatch.delenv("MARKETMIND_ALLOW_REAL", raising=False)
    _patch(monkeypatch, _FakeMT5(account=_acct("REAL")))
    r = ex.route(SIG)
    assert r["routed"] is False
    assert "REAL account blocked" in r["status"]


def test_autotrading_disabled_blocks_order(monkeypatch):
    _patch(monkeypatch, _FakeMT5(account=_acct("DEMO", trade_allowed=False)))
    r = ex.route(SIG)
    assert r["routed"] is False and "AutoTrading is disabled" in r["status"]


def test_zero_balance_blocks_order(monkeypatch):
    _patch(monkeypatch, _FakeMT5(account=_acct("DEMO", balance=0.0)))
    r = ex.route(SIG)
    assert r["routed"] is False and "no funds" in r["status"]


def test_no_terminal_queues_instead_of_raising(monkeypatch):
    _patch(monkeypatch, _FakeMT5(available=False, account=None))
    r = ex.route(SIG)
    assert r["routed"] is False and "not running" in r["status"]
    assert r["order"]["side"] == "BUY"          # order still described for the UI


def test_non_directional_signal_is_never_routed(monkeypatch):
    _patch(monkeypatch, _FakeMT5(account=_acct()))
    r = ex.route({"asset": "gold", "direction": "NONE"})
    assert r["routed"] is False and r["order"] is None


def test_lots_clamped_to_broker_limits():
    limits = {"min_lot": 0.01, "max_lot": 5.0, "lot_step": 0.01}
    assert ex._clamp_lots(0.001, limits) == 0.01      # below min -> min
    assert ex._clamp_lots(99.0, limits) == 5.0        # above max -> max
    assert ex._clamp_lots(0.117, limits) == 0.12      # snapped to step


def test_allow_real_flag_reads_env(monkeypatch):
    monkeypatch.setenv("MARKETMIND_ALLOW_REAL", "1")
    assert ex.allow_real() is True
    monkeypatch.setenv("MARKETMIND_ALLOW_REAL", "0")
    assert ex.allow_real() is False
