"""Opt-in workflow policy; preserve original implementations and historical results."""
import sys
import time
from unittest.mock import patch

BASE_DISABLED=("breakout","macd_cross","rsi2_pullback","bollinger_breakout","volume_breakout")
DEPENDENCIES={"blend":("breakout","momentum","reversion"),
    "adaptive":("breakout","momentum","reversion"),
    "trend_vote":("breakout","momentum","macd_cross"),
    "regime_mix":("trend_vote","reversion_vote")}
VERSION="observed-loss-filter-v1"
WARNING=(" User-requested post-hoc exclusions based on inspected development AND validation results; "
    "these dates are no longer untouched validation for the filtered set. Incomplete results remain unknown. "
    "Dependent mixtures are disabled as a precaution, not demonstrated causal attribution. No profitability or deployment approval.")


def excluded_names(names):
    excluded=set(BASE_DISABLED)
    while True:
        more={name for name,deps in DEPENDENCIES.items() if any(dep in excluded for dep in deps)}
        if more<=excluded:break
        excluded.update(more)
    return tuple(name for name in names if name in excluded)


def install(suite):
    if getattr(suite,"loss_filter_version",None)==VERSION:return
    original_names=tuple(suite.NAMES)
    if not set(BASE_DISABLED+tuple(DEPENDENCIES))<=set(original_names):
        raise ValueError("Strategy definitions changed; review the exclusion policy")
    excluded=excluded_names(original_names)
    active=tuple(name for name in original_names if name not in excluded)
    original_signals=suite.signals
    original_checkpoint=suite.checkpoint
    began=time.monotonic()
    metadata=dict(version=VERSION,base_disabled=list(BASE_DISABLED),
        dependent_mixtures_disabled=[name for name in excluded if name not in BASE_DISABLED],
        active_strategies=list(active),simulations_per_symbol=len(active)*4,
        criterion="Every complete aggregate result negative, with a complete negative result in each phase; incomplete cells unknown. Disable dependent mixtures transitively as a precaution.",
        basis_window=dict(start="2026-08-03",split="2026-10-01",end="2026-10-30"),
        warning=WARNING.strip(),scope="strategy-laboratory research workflow only; paper runner unchanged")
    def signals(raw):
        # Original generator needs its fixed first-five engine rules and dependencies.
        with patch.object(suite,"NAMES",original_names):
            frame=original_signals(raw)
        return frame.drop(columns=["sig_"+name for name in excluded])
    def checkpoint(path,payload):
        payload["research_policy"]=metadata
        original_checkpoint(path,payload)
        if "runs" in payload:
            runs=payload["runs"]
            last=runs[-1] if runs else {}
            print(f"{payload['config']['symbol']}: {len(runs)}/{payload['expected_runs']} simulations; "
                f"{last.get('phase','setup')} {last.get('strategy','')} {last.get('status','starting')}; "
                f"network snapshots={len(payload.get('provider_audit',[]))}; "
                f"elapsed={time.monotonic()-began:.0f}s",flush=True)
    suite.NAMES=active
    suite.signals=signals
    suite.checkpoint=checkpoint
    suite.NOTICE+=WARNING
    suite.loss_filter_version=VERSION
    return metadata


def main():
    import strategy_suite as suite
    import expanded_universe as universe
    import research_progress as progress
    metadata=install(suite)
    print("Research exclusions: "+", ".join(excluded_names(tuple(metadata['active_strategies'])+BASE_DISABLED+tuple(DEPENDENCIES)))+
        f"; {len(suite.NAMES)} active strategies, {len(suite.NAMES)*4} simulations/ticker",flush=True)
    if "--batch" in sys.argv or "--merge" in sys.argv:
        universe.main()
    else:
        progress.main()


if __name__=="__main__":main()
