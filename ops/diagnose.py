#!/usr/bin/env python3
"""
EDGAR 诊断脚本 — 打印 RKLB 8-K 实际可访问的 URL
运行：python3 diagnose_edgar.py
"""
import requests, json

UA = "EarningsMonitor janine.jian.chen@gmail.com"
sess = requests.Session()
sess.headers["User-Agent"] = UA

# 1. 从 submissions API 取 RKLB 最近 8-K
print("=== Step 1: submissions API ===")
sub = sess.get("https://data.sec.gov/submissions/CIK0001819994.json", timeout=30).json()
recent = sub["filings"]["recent"]
for i, form in enumerate(recent["form"]):
    if form in ("8-K", "8-K/A"):
        acc  = recent["accessionNumber"][i]
        date = recent["filingDate"][i]
        prim = recent["primaryDocument"][i]
        print(f"  {date}  {form}  {acc}  primary={prim}")
        if date >= "2026-04-01":
            # 找到目标 accession，尝试各种 URL
            acc_nd = acc.replace("-", "")
            cik = 1819994
            agent_cik = int(acc.split("-")[0])

            urls_to_try = [
                f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nd}/{acc}-index.htm",
                f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nd}/{acc}-index.json",
                f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nd}/{prim}",
                f"https://www.sec.gov/Archives/edgar/data/{agent_cik}/{acc_nd}/{prim}",
                f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nd}/",
            ]
            print(f"\n  --- Trying URLs for {acc} ---")
            for url in urls_to_try:
                r = sess.get(url, timeout=15)
                print(f"  {r.status_code}  {url}")
                if r.status_code == 200 and "index" in url and ".htm" in url:
                    # 打印 index.htm 中所有 href 行
                    print("  [index.htm links]")
                    for line in r.text.splitlines():
                        if "Archives" in line and "href" in line:
                            print("   ", line.strip()[:120])
            print()
        if i > 20:
            break
