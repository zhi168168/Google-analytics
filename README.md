# GA4 多项目用户数仪表盘

这个工具会读取 `properties.csv`，查询每个 GA4 Property 指定日期的 `activeUsers`，并通过本地可视化页面展示。

## 打开可视化页面

直接双击：

```text
start-dashboard.command
```

浏览器会自动打开：

```text
http://127.0.0.1:8765
```

页面支持选择日期、刷新数据、查看项目对比图和导出 CSV。关闭启动窗口即可停止本地服务。

## 部署到 Vercel

将此仓库导入 Vercel 后，在项目的 Environment Variables 添加：

```text
GA4_SERVICE_ACCOUNT_JSON
```

值为服务账号 JSON 的完整内容，必须是单行 JSON。不要把 JSON 文件提交到 GitHub。

如需让线上页面的“添加项目”按钮永久保存项目列表，还需要添加：

```text
GITHUB_TOKEN
```

它需要对 `zhi168168/Google-analytics` 仓库拥有 Contents 读写权限。线上新增项目会更新仓库中的 `properties.csv`，并由 GitHub 的新提交触发 Vercel 自动部署。

## 第一次使用

在终端进入此文件夹后执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

把 Google Cloud 下载的服务账号 JSON 文件放在此文件夹中，例如：

```text
ga4-service-account.json
```

文件夹里只有一个 JSON 时，工具会自动识别它。

## 使用命令行查询昨天

直接双击：

```text
run.command
```

或者在终端执行：

```bash
python ga4_yesterday_users.py --key ga4-service-account.json
```

默认按 `Asia/Shanghai` 计算“昨天”，结果会保存到：

```text
yesterday_users.csv
```

## 查询指定日期

```bash
python ga4_yesterday_users.py --key ga4-service-account.json --date 2026-08-06
```

## 权限要求

服务账号邮箱需要在每个 GA4 账号或 Property 的访问权限中添加，并至少拥有“查看者”权限。Google Cloud 中启用 `Google Analytics Data API` 后才可以查询。
