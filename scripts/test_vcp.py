#!/usr/bin/env python3
"""Validate technical signal computation. Run: python scripts/test_vcp.py [TICKER]"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ticker = sys.argv[1] if len(sys.argv) > 1 else "NVDA"
from signals.technicals import compute_technicals

print(f"\n{ticker} 技术信号:")
sig = compute_technicals(ticker)
print(f"  RS Score    : {sig.rs_score:.2f}  {'✅ 强势 (≥1.2)' if sig.rs_score >= 1.2 else '—'}")
print(f"  VCP         : {'✅ 收缩形态' if sig.vcp else '—'}")
print(f"  MA Reclaim  : {'✅ 穿越' if sig.ma_reclaim else '—'}")
print(f"  Has Signal  : {'✅ 是' if sig.has_signal else '否'}")
