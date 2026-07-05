-- 财报文件索引：sec_downloader 每下载/发现一份文件写一行，
-- 供数据模块「财报」Tab 筛选与单个下载；文件本体仍在文件系统。
CREATE TABLE IF NOT EXISTS filings (
  id BIGSERIAL PRIMARY KEY,
  ticker TEXT NOT NULL,
  form TEXT NOT NULL,
  filing_date DATE NOT NULL,
  accession_number TEXT NOT NULL,
  primary_document TEXT NOT NULL,
  file_path TEXT NOT NULL,
  run_id TEXT,
  downloaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (accession_number, primary_document)
);
CREATE INDEX IF NOT EXISTS idx_filings_ticker_date ON filings (ticker, filing_date DESC);
CREATE INDEX IF NOT EXISTS idx_filings_date ON filings (filing_date DESC);
