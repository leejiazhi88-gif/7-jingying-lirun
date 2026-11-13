# 8- 利润表

通过飞书开放 API 同步申万一级行业和重点公司的季度财务数据。当前数据覆盖 2022Q1–2026Q3，共 19 个季度、31 个行业及 112 家公司，单位为亿元。

## 文件

- `data/quarter_profit.json`：已同步的数据矩阵及取数统计
- `data/derived_sheets.json`：TTM、同比和最新行业汇总审计数据
- `data/individual_profit.json`：112 家公司的季度利润、TTM利润和同比审计数据
- `data/individual_revenue.json`：112 家公司的单季营收及滚动四季TTM营收审计数据
- `data/q3_2026_delta.json`：2026Q3 行业及单股利润、营收增量审计数据
- `data/revenue_sheets.json`：2.1～2.3、4.1～4.3 的营收矩阵、行业覆盖统计、成分映射及源文件哈希
- `data/revenue_sheet_sync.json`：营收六页的写入范围、数值数量及回读后的条件格式规则
- `scripts/write_quarter_profit.py`：写入飞书并回读校验
- `scripts/write_derived_sheets.py`：写入第 2、3 表，并新增刷新后的第 4 表副本
- `scripts/write_individual_profit_sheets.py`：写入单股季度利润、TTM利润和同比三个工作表
- `scripts/write_individual_revenue_sheet.py`：写入单股滚动四季TTM营收工作表
- `scripts/inspect_feishu_sheet.py`：读取 Wiki 表格结构和内容快照
- `scripts/build_revenue_sheets.py`：从缓存的 Tushare 合并利润表重算营收单季值、TTM、同比
- `scripts/write_revenue_sheets.py`：补全营收六页，逐块回读，并设置数字及条件格式

## 使用

复制 `.env.example` 为 `.env`，填写飞书应用凭据。应用需要目标 Wiki/电子表格的读取和编辑权限。

```bash
cp .env.example .env
python3 scripts/write_quarter_profit.py --check
python3 scripts/write_quarter_profit.py
```

默认写入 Wiki `PkYRwLa92il1oEkLI0kcE8zknEc` 的首个工作表 `676109`。写入范围会随季度数量动态扩展，也可通过环境变量覆盖 Wiki token 和 Sheet ID。写入后脚本会回读全部单元格并逐项核对。

脚本始终写入数值类型：绝对值达到 10 的数值使用整数和千位分隔符显示；仅绝对值小于 10 的数值四舍五入到 1 位小数并使用常规数字格式。原始数值及精度保留在 `data/quarter_profit.json`。

“年TTM利润同比涨幅”以数值比例写入并使用两位小数的百分比格式，例如底层数值 `0.7174` 显示为 `71.74%`。

最新“汇总一览表”的 G、K、M、N～U、W、Y、Z 列以数值比例写入，并使用两位小数的百分比格式。

## 数据口径

- 数据源：Tushare 利润表
- 指标：归属于母公司股东的净利润（`n_income_attr_p`）
- 行业：申万 2021 一级行业
- 单季值：Q1 直接取累计值；Q2/Q3/Q4 使用本期累计值减上期累计值
- 重复报表：优先采用 `update_flag=1` 的最新记录
- 单位：亿元；显示规则为绝对值小于 10 保留一位小数，其余整数加千位分隔符

## 新增营收页（2026-11-13）

2.1～2.3 对应行业单季营收、年TTM营收、年TTM营收同比；4.1～4.3 对应相同的单股指标。覆盖 2022Q1～2026Q3，31 个行业、112 家公司，保留现有页签名称、顺序和链接。

营收取合并报表 `total_revenue`，为空时回退至 `revenue`。先按公司计算单季，再按当前申万2021一级行业成分汇总；单季缺少本期或前期累计报表的公司不进入该季度合计，数量见 `industry.stats`。行业历史采用当前成分回溯，季度之间可用公司数量可能不同。TTM 为连续四个单季之和，同比为本期TTM / 四季度前TTM - 1，分母为零或所需历史缺失时留空。同比始终以数值比例写入，显示两位小数百分比。

新取数补入长鑫科技原缺少的 2025Q1、Q2 营收，并重算相关 TTM。所有既有非空单股单季营收均与新取的历史合并报表交叉核对。

飞书公开 API 拒绝 `dataBar` 条件格式类型，`copySheet` 也未复制数据条规则。故五个新增空白页采用原生 `cellIs` 条件格式：正值浅蓝、负值浅红；条件覆盖全部数据区域。既有 4.2 数据条保持原样，回读确认覆盖全部非空财务单元格。未使用浏览器控制。标题行加粗，冻结标题行及首列。

```bash
# work/ 中需已有完整 income_YYYYMMDD.json、members.json 及工作表快照。
python3 scripts/build_revenue_sheets.py
python3 scripts/write_revenue_sheets.py --check
python3 scripts/write_revenue_sheets.py
```

写值和样式按最多 80 列分块，避免飞书 100 列限制；重复运行会复用已存在的相同条件格式，不重复新增。
