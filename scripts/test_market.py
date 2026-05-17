#!/usr/bin/env python3
"""Validate market condition detection. Run: python scripts/test_market.py"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from signals.market import get_market_condition

cond = get_market_condition()
print(f"\n大盘环境:")
print(f"  Status      : {cond.status.upper()}")
print(f"  VIX         : {cond.vix:.1f}")
print(f"  SPY > 200MA : {cond.spy_above_200ma}")
