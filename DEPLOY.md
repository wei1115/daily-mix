# 部署成公网站点

目标：每天 08:10 自动生成歌单，发布到 Cloudflare Pages，手机随时打开，**不需要你的电脑开机**。

```
GitHub Actions（每天生成 + 提交）
        ↓
GitHub 仓库（site/ 目录就是成品）
        ↓
Cloudflare Pages（自动构建部署）
        ↓
https://mix.soulboy.asia
```

---

## 第一步：建仓库并推上去

前提：已安装 Git，且有 GitHub 账号。

1. 在 GitHub 上新建一个 **私有** 仓库，比如 `daily-mix`
2. 在本项目目录执行（把地址换成你的）：

```bash
cd D:\deepseekwork\dailymix
git init
git add .
git commit -m "init"
git branch -M main
git remote add origin https://github.com/<你的用户名>/daily-mix.git
git push -u origin main
```

> 仓库设为私有也没问题，Cloudflare Pages 支持授权访问私有仓库。

---

## 第二步：跑一次 Actions

1. 打开仓库 → **Actions** 标签页
2. 左侧选 `daily-mix` → 右侧 **Run workflow**
3. 等 1–2 分钟，看到绿色勾

跑完之后仓库里会多出：

```
site/index.html          ← 最新一天的页面
site/2026-10-21.html     ← 历史页面
site/data/2026-10-21.json
data/dailymix.db         ← 去重和缓存，保证每天不重复、构建更快
```

**为什么要提交 `data/dailymix.db`**：不然每次 Action 都是全新环境，昨天的歌今天还会再选一遍。提交它，去重历史就保住了。

---

## 第三步：接 Cloudflare Pages

1. 登录 https://dash.cloudflare.com → 左侧 **Workers & Pages** → **Create** → **Pages** → **Connect to Git**
2. 选中刚才的仓库
3. 构建设置：

| 项目 | 填什么 |
|---|---|
| Framework preset | None |
| Build command | 留空 |
| Build output directory | `site` |

4. 点 **Save and Deploy**

一两分钟后你会拿到一个 `xxx.pages.dev` 地址，手机就能打开了。

---

## 第四步：绑自己的域名（可选）

前提：`soulboy.asia` 已完成实名，且 NS 已指向 Cloudflare。

1. Pages 项目 → **Custom domains** → **Set up a custom domain**
2. 输入 `mix.soulboy.asia`
3. Cloudflare 会自动加一条 CNAME 并签证书，等 1–2 分钟

完成。之后地址就是 `https://mix.soulboy.asia`，永久不变。

---

## 日常维护

**想立刻重新生成**：GitHub 仓库 → Actions → Run workflow。跑完 1–2 分钟后刷新页面。

**想让它显示“重新生成”按钮**：把 Actions 页面地址填进环境变量 `REGENERATE_URL` 再跑一次：

```bash
REGENERATE_URL=https://github.com/<你>/daily-mix/actions/workflows/daily.yml python export_site.py
```

**改样式**：改 `web/style.css`，下次生成会自动复制到 `site/assets/style.css`。

**换时间**：改 `.github/workflows/daily.yml` 里的 cron（UTC 时间，北京时间减 8 小时）。

---

## 已知限制

- GitHub 的定时任务可能延迟几分钟到半小时，不保证 8:10 整点
- 页面上的「云」按钮会触发浏览器的“是否打开网易云”询问，勾选“始终允许”后不再提示
- 手机上点「云」不会唤起桌面客户端，只会打开网页版
- 私有仓库的 Actions 每月有免费额度（公开仓库不限），个人用途绰绰有余
