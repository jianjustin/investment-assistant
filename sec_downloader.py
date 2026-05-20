"""
向后兼容入口 — SECDownloader 实现已统一至 data/sec.py
此文件保留以兼容根目录的 earnings_monitor.py import。
"""
from data.sec import SECDownloader  # noqa: F401

if __name__ == "__main__":
    from data.sec import main
    main()
