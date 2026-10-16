# CNEquity 局部复用记录

来源：[rootSunc/CNEquity](https://github.com/rootSunc/CNEquity/tree/c118038ea82b5bb78783c0c17a1d9251b36de71d)，版本 0.16.0，commit `c118038ea82b5bb78783c0c17a1d9251b36de71d`。核对日期：2026-10-16。

| 本地文件 | 上游路径 | 修改 |
| --- | --- | --- |
| numeric.py | src/cnequity/adapters/numeric.py | 无，逐字节比对相同 |
| holidays_cn.py | src/cnequity/adapters/calendar/holidays_cn.py | 无；调用方只允许已核对的 2025–2026 年 |
| LICENSE / NOTICE | 根目录同名文件 | 保留原文 |

`../sources.py` 的财务字段映射参考 `adapters/eastmoney/fundamentals.py`，数值转换参考 `adapters/eastmoney/common.py`，新浪因子解析参考 `adapters/sina/adj_factors.py`。工作台改写了 HTTP 请求、单证券过滤、分页、失败处理、空值处理和来源归档，额外加入股本主指标报告。

Apache-2.0 适用于复用的代码，不授予东方财富、新浪、交易所及指数数据的使用权。未安装 CNEquity 包或运行其全市场数据湖、MCP 服务。升级时须重新核对字段、因子语义、日历、上游许可和数据源条款；不自动跟随上游版本。
