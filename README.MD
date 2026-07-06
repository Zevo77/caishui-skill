# 财税Skill

面向中国大陆企业、个体工商户和财税从业者的财税申报辅助 skill。

它用于协助整理账单凭证、核验官方税收政策、编制财务报表底稿、生成税务申报检查清单，并在季报/月报/年报前做数据体检。它不是自动报税机器人，也不替代会计、税务师或主管税务机关的最终判断。

核心原则：**不瞎编，不凭记忆报税。** 涉及税率、优惠政策、申报期限、数电票、电子税务局路径和地方执行口径时，必须查找最新官方权威来源。找不到官方依据、不能联网、地区口径未确认或证据不足时，必须明确标记为“无法核验/待核验”。

## 能做什么

- 财税问题解答：要求引用官方政策来源，区分全国口径和地方口径。
- 政策最新性核验：查询中国政府网、国家税务总局等官方来源。
- 地区差异处理：对电子税务局路径、地方附加税费、核定征收、数电票额度等事项标记地方待核验。
- 账单和凭证整理：扫描支付宝、微信、银行流水、发票、合同、工资社保、申报表、缴款回单等资料，生成索引和归档副本。
- 财务报表底稿：从账簿 CSV 生成试算平衡、资产负债表底稿、利润表底稿。
- 申报前体检：检查纳税人画像、政策核验状态、报表平衡、增值税发票与账面勾稽。
- 申报安全边界：正式提交、缴款、退税、红冲、作废等动作必须由用户明确确认。

## 可信度原则

- 优先使用法律法规、国务院文件、财政部/国家税务总局公告、国家税务总局政策法规库、地方税务局公告和电子税务局办税指南。
- 第三方文章、培训材料、新闻稿、经验总结只能作为线索，不能作为最终依据。
- 每个政策结论都应列出标题、发布机关、文号或页面标识、发布日期、链接和核验日期。
- 全国口径和地方口径要分开；涉及地方差异时，必须核验省市或主管税务机关材料。
- 如果证据不足，输出“无法核验/待核验”，而不是补一个看起来合理的答案。

## 目录结构

```text
caishui-skill/
  SKILL.md
  agents/
    openai.yaml
  references/
    bill-storage-and-organization.md
    controls-and-boundaries.md
    policy-freshness.md
    regional-source-strategy.md
    statement-and-filing-workflow.md
    taxpayer-data.md
  scripts/
    build_financial_statements.py
    index_bills.py
    search_official_policy.py
    validate_workpapers.py
  assets/templates/
    bill-index-template.csv
    filing-review-checklist.md
    invoice-ledger-template.csv
    ledger-template.csv
    taxpayer-profile.example.json
    vat-reconciliation-template.csv
```

## 安装

把 `caishui-skill` 目录复制到 Codex skills 目录：

```bash
cp -R caishui-skill ~/.codex/skills/caishui-skill
```

使用时可以直接说：

```text
使用 $caishui-skill 帮我体检 2026 年二季度增值税申报底稿。
```

或：

```text
使用 $caishui-skill 整理这批支付宝账单、发票和银行流水，并生成归档索引。
```

## 常用脚本

### 官方政策检索

```bash
python3 caishui-skill/scripts/search_official_policy.py "小规模纳税人 增值税 2027" --source all --limit 5
```

用途：查找中国政府网和国家税务总局官方来源，作为政策证据候选。正式使用前仍需打开原文核对施行日期、截止日期、废止状态和适用地区。

### 账单归档索引

```bash
python3 caishui-skill/scripts/index_bills.py \
  --source 原始资料目录 \
  --out 账单索引.csv \
  --copy-to 资料归档
```

用途：扫描账单/凭证目录，计算 SHA256，推断资料类别和日期，生成中文索引，并可选复制到归档目录。脚本不会删除原始文件。

### 财务报表底稿

```bash
python3 caishui-skill/scripts/build_financial_statements.py \
  --ledger caishui-skill/assets/templates/ledger-template.csv \
  --out 输出目录
```

用途：从账簿 CSV 生成试算平衡、资产负债表底稿和利润表底稿。支持中文表头。

### 申报前体检

```bash
python3 caishui-skill/scripts/validate_workpapers.py \
  --profile caishui-skill/assets/templates/taxpayer-profile.example.json \
  --statement-summary 输出目录/summary.json \
  --vat-reconciliation caishui-skill/assets/templates/vat-reconciliation-template.csv
```

用途：检查纳税人画像、政策核验状态、报表平衡和增值税勾稽。模板中的政策核验时间默认留空，因此会提示需要核验官方来源和地方口径。

## 数据安全

- 不要把真实账单、发票、银行流水、工资表、税务申报表提交到公开 GitHub 仓库。
- 不要向 AI 或脚本提供电子税务局密码、UKey/CA PIN、短信验证码、人脸认证信息、银行扣款凭据或私钥。
- 真实业务数据应保存在企业自己的加密目录、内网存储或受控文档系统中。
- 该 skill 默认只生成底稿、索引、检查清单和辅助说明；正式申报和缴款必须由用户确认。

## 适用边界

适合：

- 小微企业、个体工商户、财税顾问做申报前资料整理和风险体检。
- 对账：发票、银行流水、支付宝/微信账单、账簿、申报表之间的差异。
- 查政策：确认某项税收优惠、数电票规则、申报期限或地方执行口径。

不适合：

- 代替专业会计、税务师、律师出具正式意见。
- 无人值守登录电子税务局并提交申报。
- 绕过验证码、CA/UKey、实名、人脸或平台风控。
- 设计偷逃税、虚开发票、虚列成本费用方案。

## 免责声明

本项目仅用于财税资料整理、政策检索、报表底稿和申报前检查辅助。税收政策具有时效性和地区差异，任何具体申报动作都应以现行官方文件、当地主管税务机关口径以及专业人员复核为准。

## 相关推荐

- AI 指令集：https://www.aizlj.com/
