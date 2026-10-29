---
id: system.versions
title: "版本号"
group: system
version: 1
applies_to: []
summary: "plan-1、agent-2 这类标签标识每个口径的版本：改口径就发新版本，旧记录保留当时的版本，所以新旧口径的结果不会被悄悄混在一起。"
related: [system.concept_card, system.append_only, system.stages, agent.version_chain, system.my_knowledge]
sources: [investment_assistant/workbench/plans.py, investment_assistant/workbench/rules.py, investment_assistant/workbench/timeline.py, investment_assistant/workbench/stages.py, investment_assistant/workbench/retro.py]
---

## 是什么
系统里每套计算口径都有一个版本号，写在它产生的每一条记录上。规则：**改口径（阈值、公式、流程）就发新版本；旧记录保留原版本，不重算。**这样你读到一条旧记录，总能知道它是按哪套规矩算出来的。

## 怎么算 / 从哪来
当前版本标签与含义（括号里是它标识的东西）：

- `rules-1`：规则 v1 的八条规则与阈值（另两条持仓卖出规则同属此版）
- `plan-1`：规则计划的公式；`context-2`：计划里冻结的市场环境
- `screen-1`：每日筛选；`regime-2`：区制判定（`regime-1` 是旧口径）
- `agent-2`：带论点、失效条件、版本链的 Agent 计划（`agent-1` 是旧版，见 [agent-1 旧版](agent.legacy.md)）；`agent-review-1`：每日复查；`agent-brief-1`：解读
- `condition-1`：失效与复查条件登记表；`timeline-1`：版本链、信号与链状态
- `derivation-1`：计划推导与一致性核对
- `plan-shadow-1`：计划影子；`tracks-1`：三方对比；`review-7`：周度复盘（新增"你学到了什么"，`review-6` 是旧口径）；`monthly-3`：月度复盘；`backcheck-2`：上线前检查
- `stages-3`：九个阶段的运行证据（`stages-2` 是八个阶段、`stages-1` 是七个阶段的旧口径）
- `retro-1`：复盘卡的对象、结束事件判定、冻结事实与决定文案；`agent-retro-1`：复盘卡起草
- `my-knowledge-1`：我的知识的字段、挂靠、版本与截止时间可见性；`knowledge-perf-1`：知识表现回看的样本口径；`agent-discuss-1`：就此计划讨论的回答
- `knowledge-1`：概念卡与原理页的格式与加载规则

概念卡自己也有版本，是另一回事：见[概念卡](system.concept_card.md)。

## 在系统里哪里看到
计划、候选、复盘快照、阶段行上都带着版本号；就地展开的概念摘要里显示它适用的版本。

## 注意
版本号相同才可以直接比较。旧版本的行不会因为口径更新而改变，这是有意的。
