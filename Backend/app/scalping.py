"""Scalping strategy backtest for MarketMind AI.

Ties the pieces together into a trading loop and answers the concrete question
behind the "$100 -> $1000" claim: run the strategy across thousands of
independent bankroll paths and look at the *distribution* of outcomes, not one
lucky stream.

Strategy
--------
* Signal   — the spoofing radar reads each order-book window. When a spoof wall
             is detected the price tends to get pushed the opposite way as the
             wall is pulled, so we scalp in that direction. The detector's
             short-horizon directional hit-rate is the ``edge`` (win probability
             p). Clean windows are skipped (no trade), which is what makes it a
             *selective* scalp rather than always-on.
* Sizing   — fractional Kelly on the edge, capped by ``max_risk`` per trade.
* Exit     — a symmetric quantile-volatility bracket: take-profit at +b*R,
             stop at -R, where R is one unit of per-trade risk.
* Costs    — round-trip fee + slippage as a fraction of the leveraged notional
             is deducted every trade, win or lose.

Everything is deterministic given a seed. The edge is a *modelled* input — the
honest lever in the whole thing — so the backtest also sweeps it to show how
sensitive "reaching $1000" is to whether the edge is real.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .quant import fractional_kelly


@dataclass
class ScalpConfig:
    start_equity: float = 100.0
    target_equity: float = 1000.0
    ruin_equity: float = 10.0          # below this the account is "blown up"
    trades: int = 600                  # e.g. ~30 scalps/day for ~20 days
    edge: float = 0.56                 # signal win probability p (the key input)
    payoff: float = 1.0                # reward:risk ratio b (target/stop)
    kelly_fraction: float = 0.5        # half-Kelly by default
    max_risk: float = 0.05             # cap risk per trade at 5% of equity
    fee_bps: float = 6.0               # round-trip cost in basis points of notional
    scalp_move_pct: float = 0.5        # stop distance as a % of price (tight = more leverage)
    max_leverage: float = 50.0         # exchange cap; scalps tighter than this are clamped
    trade_prob: float = 0.5            # fraction of windows that produce a signal


def _risk_fraction(cfg: ScalpConfig) -> float:
    """Per-trade risk as a fraction of equity from fractional Kelly, capped."""
    f = fractional_kelly(cfg.edge, cfg.payoff, c=cfg.kelly_fraction)
    return float(min(f, cfg.max_risk))


def _leverage_and_cost(cfg: ScalpConfig) -> tuple[float, float, float]:
    """Derive required leverage and per-trade cost from the scalp geometry.

    To risk fraction R of equity on an ``m`` = scalp_move_pct price move you must
    size the position at leverage L = R / m; the round-trip fee is paid on that
    leveraged notional, so cost (as a fraction of equity) = fee_rate * L. Tighter
    scalps => higher leverage => more fee drag. Leverage is clamped to the
    exchange cap, which in turn caps the achievable risk R.
    """
    R = _risk_fraction(cfg)
    m = cfg.scalp_move_pct / 100.0
    lev = R / m
    if lev > cfg.max_leverage:
        lev = cfg.max_leverage
        R = lev * m               # can't risk the full Kelly amount within the cap
    cost = (cfg.fee_bps / 1e4) * lev
    return float(R), float(lev), float(cost)


def simulate_paths(cfg: ScalpConfig, paths: int = 5000, seed: int = 0) -> dict:
    """Monte-Carlo the strategy across ``paths`` independent bankrolls.

    Vectorised over paths. Each trade multiplies equity by ``1 + b*R - cost`` on
    a win or ``1 - R - cost`` on a loss, where R is the risk fraction and cost is
    the leveraged round-trip fee. Skipped windows (no signal) cost nothing.
    """
    rng = np.random.default_rng(seed)
    R, lev, cost = _leverage_and_cost(cfg)

    equity = np.full(paths, cfg.start_equity, dtype=float)
    peak = equity.copy()
    max_dd = np.zeros(paths)
    ruined = np.zeros(paths, dtype=bool)
    reached = np.zeros(paths, dtype=bool)
    first_hit = np.full(paths, -1)

    win_mult = 1.0 + cfg.payoff * R - cost
    loss_mult = 1.0 - R - cost

    for t in range(cfg.trades):
        took_trade = rng.random(paths) < cfg.trade_prob
        wins = rng.random(paths) < cfg.edge
        step = np.where(wins, win_mult, loss_mult)
        step = np.where(took_trade & ~ruined, step, 1.0)
        equity = equity * step

        peak = np.maximum(peak, equity)
        dd = (peak - equity) / peak
        max_dd = np.maximum(max_dd, dd)

        newly_reached = (~reached) & (equity >= cfg.target_equity)
        first_hit[newly_reached] = t
        reached |= equity >= cfg.target_equity
        ruined |= equity <= cfg.ruin_equity

    median = float(np.median(equity))
    return {
        "config": cfg.__dict__.copy(),
        "risk_per_trade": round(R, 4),
        "implied_leverage": round(lev, 2),
        "cost_per_trade_pct": round(cost * 100, 4),
        "expectancy_per_trade_pct": round(((cfg.edge * win_mult + (1 - cfg.edge) * loss_mult) - 1) * 100, 4),
        "paths": paths,
        "median_final_equity": round(median, 2),
        "mean_final_equity": round(float(equity.mean()), 2),
        "p10_final_equity": round(float(np.percentile(equity, 10)), 2),
        "p90_final_equity": round(float(np.percentile(equity, 90)), 2),
        "prob_reach_1000": round(float(reached.mean()), 4),
        "prob_ruin": round(float(ruined.mean()), 4),
        "prob_below_start": round(float((equity < cfg.start_equity).mean()), 4),
        "median_max_drawdown": round(float(np.median(max_dd)), 4),
        "median_trades_to_1000": (int(np.median(first_hit[reached])) if reached.any() else None),
    }


def edge_sweep(cfg: ScalpConfig | None = None, paths: int = 4000, seed: int = 0) -> list[dict]:
    """How P(reach $1000) and P(ruin) depend on the win rate (is the edge real?)."""
    base = cfg or ScalpConfig()
    rows = []
    for edge in (0.50, 0.52, 0.54, 0.56, 0.58, 0.60):
        c = ScalpConfig(**{**base.__dict__, "edge": edge})
        r = simulate_paths(c, paths=paths, seed=seed)
        rows.append({
            "edge": edge,
            "expectancy_per_trade_pct": r["expectancy_per_trade_pct"],
            "median_final_equity": r["median_final_equity"],
            "prob_reach_1000": r["prob_reach_1000"],
            "prob_ruin": r["prob_ruin"],
        })
    return rows


def scalp_size_sweep(cfg: ScalpConfig | None = None, paths: int = 4000, seed: int = 0) -> list[dict]:
    """Tighter scalps need more leverage and bleed more to fees, edge fixed.

    Shows why fee drag, not the edge, is often what kills a scalper: the same
    signal is profitable on wider scalps and unprofitable on very tight ones.
    """
    base = cfg or ScalpConfig()
    rows = []
    for m in (0.2, 0.3, 0.5, 0.8, 1.2):
        c = ScalpConfig(**{**base.__dict__, "scalp_move_pct": m})
        r = simulate_paths(c, paths=paths, seed=seed)
        rows.append({
            "scalp_move_pct": m,
            "implied_leverage": r["implied_leverage"],
            "cost_per_trade_pct": r["cost_per_trade_pct"],
            "median_final_equity": r["median_final_equity"],
            "prob_reach_1000": r["prob_reach_1000"],
            "prob_ruin": r["prob_ruin"],
        })
    return rows


def one_path(cfg: ScalpConfig | None = None, seed: int = 0) -> dict:
    """A single equity curve (like the one shown 'live'), for illustration."""
    cfg = cfg or ScalpConfig()
    rng = np.random.default_rng(seed)
    R, lev, cost = _leverage_and_cost(cfg)
    win_mult = 1.0 + cfg.payoff * R - cost
    loss_mult = 1.0 - R - cost

    equity = cfg.start_equity
    curve = [equity]
    wins = losses = 0
    for _ in range(cfg.trades):
        if rng.random() >= cfg.trade_prob:
            curve.append(equity)
            continue
        if rng.random() < cfg.edge:
            equity *= win_mult
            wins += 1
        else:
            equity *= loss_mult
            losses += 1
        equity = max(equity, 0.0)
        curve.append(equity)
        if equity <= cfg.ruin_equity or equity >= cfg.target_equity:
            break
    return {
        "final_equity": round(equity, 2),
        "wins": wins, "losses": losses,
        "win_rate": round(wins / (wins + losses), 4) if wins + losses else 0.0,
        "reached_1000": equity >= cfg.target_equity,
        "ruined": equity <= cfg.ruin_equity,
        "equity_curve": [round(x, 2) for x in curve],
    }


def format_report(paths: int = 5000, seed: int = 0) -> str:
    cfg = ScalpConfig()
    r = simulate_paths(cfg, paths=paths, seed=seed)
    L = []
    L.append("=" * 68)
    L.append("  MarketMind AI — scalping strategy backtest  ($100 -> $1000?)")
    L.append("=" * 68)
    L.append(f"  edge(win%)={cfg.edge}  payoff={cfg.payoff}  half-Kelly risk/trade={r['risk_per_trade']}")
    L.append(f"  scalp move={cfg.scalp_move_pct}% -> implied leverage={r['implied_leverage']}x  "
             f"fee={cfg.fee_bps}bps -> cost/trade={r['cost_per_trade_pct']}%  trades={cfg.trades}")
    L.append(f"  expectancy per trade = {r['expectancy_per_trade_pct']}%")
    L.append("-" * 68)
    L.append(f"  median final equity ....... ${r['median_final_equity']}")
    L.append(f"  10th / 90th percentile .... ${r['p10_final_equity']} / ${r['p90_final_equity']}")
    L.append(f"  P(reach $1000) ............ {r['prob_reach_1000']*100:.1f}%")
    L.append(f"  P(ruin, < $10) ............ {r['prob_ruin']*100:.1f}%")
    L.append(f"  P(end below $100) ......... {r['prob_below_start']*100:.1f}%")
    L.append(f"  median max drawdown ....... {r['median_max_drawdown']*100:.1f}%")
    L.append("=" * 68)
    L.append("\n  EDGE SWEEP  (does the signal actually predict direction?)")
    L.append(f"  {'win%':>6} {'exp/trade':>10} {'median$':>10} {'P(1000)':>9} {'P(ruin)':>9}")
    for row in edge_sweep(cfg, paths=paths, seed=seed):
        L.append(f"  {row['edge']:>6} {row['expectancy_per_trade_pct']:>9}% "
                 f"{row['median_final_equity']:>10} {row['prob_reach_1000']*100:>8.1f}% {row['prob_ruin']*100:>8.1f}%")
    L.append("\n  SCALP-SIZE SWEEP  (edge fixed at %.2f; tighter scalp = more fee drag)" % cfg.edge)
    L.append(f"  {'move%':>6} {'lev':>6} {'cost%':>7} {'median$':>10} {'P(1000)':>9} {'P(ruin)':>9}")
    for row in scalp_size_sweep(cfg, paths=paths, seed=seed):
        L.append(f"  {row['scalp_move_pct']:>6} {row['implied_leverage']:>5}x {row['cost_per_trade_pct']:>6}% "
                 f"{row['median_final_equity']:>10} {row['prob_reach_1000']*100:>8.1f}% {row['prob_ruin']*100:>8.1f}%")
    L.append("=" * 68)
    return "\n".join(L)


if __name__ == "__main__":
    print(format_report())
