# 部署成公网站点

当前实际架构（已跑通）：

```
GitHub Actions（每天 08:10 生成 + 提交回仓库）
        ↓
Cloudflare Pages（wrangler 直传 site/，不走 Git 集成）
        ↓
https://daily-mix.pages.dev
        ↓
https://fm.soulboy.asia
```

本机不需要开机，也不需要手动上传。

---

## 已经配好的东西

| 项 | 值 |
|---|---|
| 仓库 | `github.com/wei1115/daily-mix` |
| 工作流 | `.github/workflows/daily.yml` |
| Pages 项目 | `daily-mix`（Direct Upload 创建） |
| 线上地址 | `https://fm.soulboy.asia`（备用 `https://daily-mix.pages.dev`） |

GitHub Secrets：

- `CLOUDFLARE_API_TOKEN` —— Cloudflare 令牌，权限 `Account → Cloudflare Pages → Edit`
- `CLOUDFLARE_ACCOUNT_ID` —— `520f723fe41615ec74c0af6f6bb3aad4`

> 注意：Cloudflare 的 Git 集成在部分地区会卡在 GitHub 授权回跳，所以 Pages 项目是用「直接上传」创建的，
> 之后由 workflow 里的 `cloudflare/wrangler-action` 把 `site/` 推上去。

---

## 每天会发生什么

1. 08:10（北京时间）GitHub Actions 自动触发
2. `python export_site.py` 抓四个源、生成当天歌单、渲染 `site/`
3. 把 `site/` 和 `data/dailymix.db` 提交回仓库
4. `wrangler pages deploy site` 发布到 Cloudflare Pages

GitHub 的 cron 可能延迟几分钟到半小时。

---

## 手动重新生成

仓库 → **Actions** → 左侧 `daily-mix` → **Run workflow**。

跑完约 1–2 分钟，线上页面就更新了。

---

## 自定义域名（已配置）

1. Cloudflare → **Workers & Pages** → 项目 `daily-mix` → **Custom domains**
2. **Set up a custom domain**
3. 输入 `fm.soulboy.asia`
4. Cloudflare 自动加 CNAME 并签证书，1–2 分钟生效

前提：`soulboy.asia` 的 NS 已指向 Cloudflare（`leah` / `miguel`）。

---

## 改样式 / 改逻辑

改本地的 `web/style.css`、`sources.py` 等，然后：

```bash
git add -A
git commit -m "..."
git push
```

或者直接改 GitHub 网页上的文件。下一次（或手动触发）Actions 就会用新代码。

---

## 成本

| 项目 | 费用 |
|---|---|
| GitHub 私有/公开仓库 + Actions | 免费 |
| Cloudflare Pages | 免费（每月 500 次构建、无限流量） |
| 域名 | 首年 ¥8（.asia），每年续费 |
