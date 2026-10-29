"""SEC monitor: original scope, durable delivery receipts and local scheduling."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from investment_assistant.filings.monitor_source import ACCESSION, EdgarSource, atomic_write, read_watchlist
from investment_assistant.filings.service import _persist_filing_index, _write_reports
from investment_assistant.notify.discord_bot import DeliveryError, DiscordBotClient


@contextmanager
def locked_state(directory: Path):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / "monitor.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = directory / "state.json"
        state = json.loads(path.read_text()) if path.exists() else {"version": 1, "files": {}, "events": {}}
        if (state.get("version") != 1 or not isinstance(state.get("files"), dict)
                or not isinstance(state.get("events"), dict)):
            raise ValueError("SEC 状态文件结构无效；未重置去重记录")

        def save():
            atomic_write(path, json.dumps(state, ensure_ascii=False, indent=2).encode())

        yield state, save


def legacy_records(log_path: Path, output: Path, tickers: list[str], owned: set[str]) -> dict[str, bool]:
    records: dict[str, bool] = {}
    # This file is required: an unreadable/corrupt log must not cause a mass replay.
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        accession = str(row.get("accession", ""))
        if accession == "n/a" or row.get("form") == "ZERO-HIT":
            continue
        if not ACCESSION.fullmatch(accession) or not row.get("ticker"):
            raise ValueError("SEC 历史日志包含无效申报记录")
        key = row["ticker"].upper() + ":" + accession
        records[key] = records.get(key, False) or row.get("discord_sent") is True
    for ticker in tickers:
        for path in (output / ticker).rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".htm", ".html", ".txt"}:
                continue
            match = ACCESSION.search(path.name)
            if match:
                key = ticker + ":" + match.group()
                if key not in owned:
                    records.setdefault(key, False)
    return records


def _event(state: dict, key: str, content: str) -> str:
    event_id = hashlib.sha256(key.encode()).hexdigest()[:24]
    state["events"].setdefault(event_id, {"key": key, "content": content, "status": "pending"})
    return event_id


def _deliver(state: dict, save, event_ids: list[str], client) -> list[dict]:
    receipts = []
    for event_id in dict.fromkeys(event_ids):
        event = state["events"][event_id]
        status = event["status"]
        if status == "sending":
            # A crash between the HTTP send and local commit is ambiguous.
            event["status"] = status = "unknown"
            save()
        if status not in {"sent", "unknown"}:
            event["status"] = "sending"
            save()
            try:
                event["receipt"] = client.send(event["content"], event_id)
                event["status"] = "sent"
                event.pop("error", None)
            except DeliveryError as exc:
                event["status"] = "unknown" if exc.uncertain else "failed"
                event["error"] = str(exc)
            except Exception:
                event["status"] = "unknown"
                event["error"] = "Discord 未预期错误；投递待核验"
            save()
        receipts.append({"event_id": event_id, "status": event["status"],
                         **event.get("receipt", {}), **({"error": event["error"]} if event.get("error") else {})})
    return receipts


def collect(config, start: date, end: date, state: dict, save, source, *, persist=None, reports=None) -> dict:
    if reports is None and not os.environ.get("FILINGS_REPORT_DIR"):
        raise ValueError("FILINGS_REPORT_DIR 未配置，无法完成正文报告")
    if persist is None and not os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL"):
        raise ValueError("数据库未配置，无法保存 SEC 索引")
    persist = persist or _persist_filing_index
    reports = reports or _write_reports
    cfg = config.sec_monitor
    tickers = read_watchlist(Path(cfg.watchlist_path))
    known = legacy_records(Path(cfg.legacy_log_path), config.filings.output_dir, tickers, set(state["files"]))
    result = {"start_date": start.isoformat(), "end_date": end.isoformat(), "tickers": tickers,
              "downloaded_count": 0, "filings": [], "other_8k": [], "errors": {},
              "legacy_pending_verification": sum(not sent for sent in known.values()), "event_ids": []}
    # Finish the entire submissions query before downloading anything.
    found = source.discover(tickers, start.isoformat(), end.isoformat())
    # EdgarSource.discover is per ticker and returns (metas, {ticker: error}); a plain list (older sources, test
    # doubles) has no per-ticker errors. One ticker failing must not stop the others (fetch-1 spec §6.2 row 4a).
    candidates, ticker_errors = found if isinstance(found, tuple) else (found, {})
    result["errors"].update(ticker_errors)
    for meta in candidates:
        key = meta["ticker"] + ":" + meta["accession_number"]
        if key in known:
            continue
        entry = state["files"].get(key)
        if entry is None:
            entry = {"meta": meta, "status": "pending"}
            state["files"][key] = entry
            save()  # Claim before any file write so interrupted downloads can resume.
        meta = entry["meta"]
        if entry["status"] == "pending":
            selected, documents = source.documents(meta)
            if selected:
                paths = []
                for name, content in documents:
                    if Path(name).name != name or name in {".", ".."}:
                        raise ValueError("SEC 文件名无效")
                    dest = config.filings.output_dir / meta["ticker"] / meta["form"] / (meta["accession_number"] + "-" + name)
                    if not dest.exists():
                        atomic_write(dest, content)
                        result["downloaded_count"] += 1
                    paths.append(str(dest))
                base_url = meta["edgar_url"].rsplit("/", 1)[0] + "/"
                meta.update(path=paths[0], attachments=paths[1:], downloaded=True,
                            document_urls={path: base_url + name for path, (name, _) in zip(paths, documents)})
                entry["status"] = "stored"
            else:
                entry["status"] = "excluded"
            save()
        if entry["status"] == "stored":
            # Failure here preserves a resumable entry; it is never considered delivered.
            persist([meta])
            entry["reports"] = reports([meta])
            entry["status"] = "ready"
            save()
        if entry["status"] == "ready":
            result["filings"].append(meta)
            from investment_assistant.filings.report import filing_notification
            content = filing_notification(meta, entry.get("reports", []))
            result["event_ids"].append(_event(state, "filing:" + key, content))
        elif entry["status"] == "excluded":
            result["other_8k"].append(meta)
            result["event_ids"].append(_event(state, "other:" + key,
                f"【其他 8-K】{meta['ticker']} {meta['filing_date']} {meta['primary_document']}\n"
                f"未见 Item 2.02 或 EX-99.1，未存入正式来源库。\n{meta['edgar_url']}"))
    if ticker_errors:
        # Coverage is incomplete: no "nothing new" claim and no advance of the last complete scan.
        result["coverage"] = "partial_for_declared_universe"
        save()
        return result
    result["coverage"] = "complete_for_declared_universe"
    state["last_complete_scan"] = {"at": datetime.now(UTC).isoformat(), "start": start.isoformat(), "end": end.isoformat()}
    save()
    return result


def scan_and_notify(config, start: date, end: date, *, source=None, client=None, notify_cfg=None,
                    persist=None, reports=None) -> dict:
    cfg = config.sec_monitor
    if not cfg.state_dir:
        raise ValueError("SEC monitor state_dir 未配置")
    directory = Path(cfg.state_dir)
    source = source or EdgarSource(directory / "evidence")
    client = client or DiscordBotClient(cfg.discord_channel_id)
    if notify_cfg is None:
        from investment_assistant.services.settings import effective_notify_config
        notify_cfg = effective_notify_config(config.notify)
    with locked_state(directory) as (state, save):
        try:
            result = collect(config, start, end, state, save, source, persist=persist, reports=reports)
        except Exception as exc:
            result = {"start_date": start.isoformat(), "end_date": end.isoformat(), "coverage": "unavailable",
                      "errors": {"collection": str(exc)}, "filings": [], "downloaded_count": 0, "event_ids": []}
        result["evidence"] = source.evidence
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        scan_key = f"{today}:{start}:{end}"
        if result["errors"]:
            if "collection" in result["errors"]:
                detail = (f"{str(result['errors']['collection'])[:800]}\n未能完成查源/归档，不能判断为零命中。"
                          "成功查找记录未前移。")
            else:
                failed = "; ".join(f"{ticker}: {error}" for ticker, error in sorted(result["errors"].items()))
                detail = (f"部分股票查源失败：{failed[:700]}\n其余股票已正常处理（归档与通知照常）；覆盖不完整，"
                          "不能判断为零命中，成功查找记录未前移。")
            title = "SEC 采集失败" if "collection" in result["errors"] else "SEC 采集部分失败"
            content = (f"【{title}】本地投研工作台 · {today}\n范围 {start} 至 {end}（美东申报日期）\n"
                       f"{detail}运行记录：http://127.0.0.1:8787/")
            result["event_ids"].append(_event(state, "failure:" + today + ":" + content, content))
        elif (not state.get("notified_scans", {}).get(scan_key)
              and not any(state["events"][i]["status"] != "sent" for i in result["event_ids"])):
            # Only a complete scan can assert no new qualifying filings.
            content = (f"【SEC】{today} 观察名单无新符合规则的 10-Q/10-K/8-K。\n"
                       f"已完整检查 {len(result['tickers'])} 只，范围 {start} 至 {end}（美东申报日期），"
                       f"已知申报不重复推送。历史待核验 {result['legacy_pending_verification']} 条。\n"
                       "来源：https://www.sec.gov/edgar/search/")
            result["event_ids"].append(_event(state, f"zero:{today}:{start}:{end}", content))
        save()
        if notify_cfg.channel != "discord" or not notify_cfg.discord_enabled or notify_cfg.task_enabled.get("filings") is False:
            result["delivery"] = {"status": "disabled", "receipts": []}
        else:
            receipts = _deliver(state, save, result["event_ids"], client)
            failed = any(r["status"] != "sent" for r in receipts)
            result["delivery"] = {"status": "needs_attention" if failed else "sent", "receipts": receipts}
            if failed:
                result["errors"]["delivery"] = "Discord 投递失败或待核验；详见 delivery.receipts"
            elif not result["errors"]:
                state.setdefault("notified_scans", {})[scan_key] = True
                save()
        return result


def run_monitor(config, *, start_date=None, end_date=None, trigger_source="scheduled") -> dict:
    from investment_assistant.tasks._harness import run_task

    start = start_date or date.fromisoformat(config.sec_monitor.start_date)
    end = end_date or (start_date if start_date else datetime.now(ZoneInfo("America/New_York")).date())
    if start > end:
        raise ValueError("SEC 起始日期晚于结束日期")
    return run_task("filings", lambda: scan_and_notify(config, start, end), config=config,
                    target_start_date=start, target_end_date=end, trigger_source=trigger_source, notify=False)
