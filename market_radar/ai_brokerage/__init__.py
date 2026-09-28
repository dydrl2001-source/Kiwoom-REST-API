"""AI Brokerage decision layer for Market Radar.

The package is PAPER-first. It produces explainable decision packets but does not
send broker orders.
"""
from .models import DeskVerdict, DecisionPacket, StrategySpec
from .strategy_registry import StrategyRegistry

__all__ = ["DeskVerdict", "DecisionPacket", "StrategySpec", "StrategyRegistry"]
