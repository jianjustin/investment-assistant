-- 023: 每日筛选（screen_runs / screen_results / pool_tiers.source，后续追加）与任务时区统一北京时间。
-- filings 改为北京 09:30：只改仍是纽约时区的行，不置空 next_run_at
-- （置空会让调度器在下一个 tick 立即运行一次），直接写入下一个北京 09:30（周一至周五）。
UPDATE scheduled_jobs
   SET timezone = 'Asia/Shanghai', time_local = '09:30',
       next_run_at = (
         SELECT min(ts) FROM (
           SELECT (((now() AT TIME ZONE 'Asia/Shanghai')::date + d) + time '09:30') AT TIME ZONE 'Asia/Shanghai' AS ts
             FROM generate_series(0, 7) AS d) s
          WHERE ts > now() AND extract(isodow FROM ts AT TIME ZONE 'Asia/Shanghai') BETWEEN 1 AND 5)
 WHERE name = 'filings' AND timezone = 'America/New_York';
