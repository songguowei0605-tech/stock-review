# 免费部署到 iPhone

这个版本使用 GitHub Pages 免费发布，不需要服务器。

## 一、创建 GitHub 仓库

1. 登录 GitHub。
2. 新建一个 Public 仓库，例如 `stock-review`。
3. 不要勾选自动创建 README。

## 二、上传项目

把 `stock-screener` 整个目录上传到仓库，至少需要包含：

- `screener.py`
- `publish_web.py`
- `hexin-v.bundle.js`
- `docs/`
- `.github/workflows/update-dashboard.yml`

## 三、开启 GitHub Pages

进入仓库：

`Settings` → `Pages` → `Build and deployment` → `Source`

选择：

`GitHub Actions`

## 四、手动运行一次

进入仓库：

`Actions` → `Update stock dashboard` → `Run workflow`

运行成功后，网页地址通常是：

`https://你的用户名.github.io/仓库名/`

## 五、添加到 iPhone 主屏幕

1. 用 iPhone Safari 打开网页地址。
2. 点底部分享按钮。
3. 选择“添加到主屏幕”。
4. 桌面会出现“复盘助手”图标。

之后每天收盘后，GitHub Actions 会自动更新数据。iPhone 打开图标即可查看最新结果。

## 自动更新时间

工作流设置为每周一到周五 UTC 07:50，也就是北京时间 15:50。

如果遇到非交易日，脚本会使用东方财富返回的最近交易日数据。
