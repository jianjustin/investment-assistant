-- 运行记录补充"指定日期"与触发来源：
-- target_start_date/target_end_date 为本次运行的目标数据日期（单日时两者相等），
-- trigger_source 区分定时(scheduled)与手动(manual)触发。
ALTER TABLE job_reports ADD COLUMN IF NOT EXISTS target_start_date DATE;
ALTER TABLE job_reports ADD COLUMN IF NOT EXISTS target_end_date DATE;
ALTER TABLE job_reports ADD COLUMN IF NOT EXISTS trigger_source TEXT NOT NULL DEFAULT 'scheduled';
