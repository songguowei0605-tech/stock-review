# 收盘后模型选股器

当前实现的是以下模型：

- 上市时间超过 1 年
- 排除 ST、退市风险股
- 排除北交所、科创板
- 当日涨幅大于 5%
- 当日量比大于 1 且小于 6
- 当日换手率大于 3% 且小于 10%
- 总市值小于 350 亿元
- 股价大于 3 元且小于 50 元
- 最近 60 个交易日内至少出现一次单日涨幅大于 5%
- 默认不把当天计入 60 日强势窗口，只检查前 59 个交易日

## 运行

需要 Python 和 Node.js。Node.js 用于生成同花顺访问 token。

```powershell
python screener.py
```

如果当前系统没有 `node` 命令：

```powershell
python screener.py --node "C:\path\to\node.exe"
```

指定交易日：

```powershell
python screener.py --date 2026-09-30
```

把当天也纳入 60 日强势窗口：

```powershell
python screener.py --include-today-in-window
```

## 输出

运行后会在 `output/` 生成：

- `screen_YYYYMMDD.csv`
- `screen_YYYYMMDD.json`
- `screen_YYYYMMDD.md`

## 数据口径

- 同花顺行情中心：当日涨幅、量比、换手率
- 东方财富数据中心：总市值、上市日期、风险警示
- 同花顺日 K：最近 60 个交易日的强势记录

退市风险股当前按证券名称、交易所风险警示标记过滤。完整退市风险判断仍应接入公告、财务和交易所风险警示数据。

结果只是模型命中清单，不构成投资建议。

## 板块概念统计

每次运行还会统计全市场当日涨幅大于 6% 的股票，按股票去重后统计板块和概念出现次数，并输出行业前 10、概念前 10。

计数规则：

- 同一只股票出现同一板块或概念，只计 1 次；
- 不同股票出现同一标签，每次各加 1；
- 板块和概念分别统计。

例如：

- 1号股票：银行、非金融
- 2号股票：银行、科技

统计结果：

- 银行 2
- 非金融 1
- 科技 1

行业板块只统计一级行业，不包含地区板块；概念采用东方财富 F10 精确概念。

额外输出文件：

- `output/theme_stats_YYYYMMDD.md`
- `output/theme_stats_YYYYMMDD.json`
- `output/theme_membership_YYYYMMDD.csv`

可调整涨幅阈值：

```powershell
python screener.py --theme-threshold 6
```

跳过板块概念统计：

```powershell
python screener.py --skip-theme-stats
```

## iPhone 免费网页版

项目已加入 GitHub Pages 手机版：

- `docs/`：iPhone Safari 可打开的 PWA 网页
- `.github/workflows/update-dashboard.yml`：交易日收盘后自动运行并发布
- `publish_web.py`：把选股结果转换成网页数据

部署步骤见 `DEPLOY_IPHONE.md`。
