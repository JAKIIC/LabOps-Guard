# LabOps Guard 初赛公网 Evidence Replay 部署说明

## 结论

该 Demo **可以纯静态托管**，公网不需要 LabOps Python 后端、数据库、对象存储或 AgentTeams 控制面。

构建过程只在开发环境读取 AT-004 与 AT-002 的已归档证据，并复用 `labops.web` 中现有 Dashboard 解析函数。生成器先验证关键状态、指标、六角色顺序、审批顺序、Trace、Runner 隔离条件和证据包哈希，再把明确的公开白名单字段渲染成单个 HTML 文件：

```text
不可变归档证据
  → 现有 Dashboard 证据解析函数
  → 完整性与事实边界校验（失败即不生成）
  → 公开字段白名单
  → docs/public-demo/index.html
```

浏览器端不读取原始证据，不调用 API，不运行 JavaScript，也没有文件上传、实验执行或状态修改入口。

## 本地生成与校验

在仓库根目录运行：

```powershell
python -B scripts/build_public_demo.py
python -B scripts/build_public_demo.py --check
python -B -m unittest tests.test_public_demo
```

第一条命令生成静态页面；第二条命令验证已提交页面与当前归档证据完全一致；第三条命令同时检查必需内容、证据目录未被修改以及敏感暴露面。

生成产物：

```text
docs/public-demo/index.html
```

不要把 `demo/output-agentteams-*`、运行日志、原始 Artifact、Trace 明细或凭据目录复制到公网站点。公网只部署生成后的静态目录。

## 推荐部署：GitHub Pages

不要将整个 `docs/` 设置为 Pages 的 branch publishing 源。仓库内还有项目文档，公网 Demo 的部署边界应当只包含 `docs/public-demo/`。

项目已提供手动发布工作流 `.github/workflows/pages-public-demo.yml`。它先运行归档证据一致性校验，再将 **仅有的** `docs/public-demo/` 目录上传为 Pages artifact：

1. 打开仓库 **Settings → Pages**。
2. 在 **Build and deployment → Source** 中选择 **GitHub Actions**。
3. 打开仓库 **Actions → Deploy public evidence replay**。
4. 选择 **Run workflow**，确认从 `main` 运行。
5. 等待部署完成后访问：

```text
https://jakiic.github.io/LabOps-Guard/
```

报名表中的“对外 Demo URL”应填写上面的完整页面地址，而不是仓库地址、本地 Dashboard 地址或控制面地址。首次填写前，应在无登录的浏览器窗口中确认页面可访问，并核对页首存在 **Archived Verified Run / Evidence Replay** 标签。

工作流只支持人工触发，避免普通代码提交意外更新比赛演示。需要更新公网内容时，先重新生成并校验静态页面，合并到 `main` 后再人工运行部署工作流。

GitHub Pages 官方自定义工作流说明：<https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages>

## 其他静态托管方式

任何只提供静态文件的 HTTPS 服务都可使用。发布根目录可以是整个 `docs/`，此时路径保持 `/public-demo/`；也可以只发布 `docs/public-demo/`，此时页面位于站点根路径。

推荐配置：

- 仅允许 `GET`、`HEAD`；
- 强制 HTTPS；
- 禁止目录索引；
- 不挂载仓库、Docker socket、原始证据或用户目录；
- 不注入环境变量、密钥或控制面凭据；
- 对 `index.html` 使用短缓存或重新验证，避免更新后仍看到旧版本。

因为当前方案可静态化，**最小公网服务器需求为零**。如果评审平台必须使用自管服务器，只需一个能托管单个 HTML 文件的静态服务器；无需 Python 进程。建议 1 vCPU、128 MB 内存即可，并遵循上述只读与隔离要求。

## 安全暴露面检查

| 检查项 | 结果 | 实现方式 |
|---|---|---|
| 任意文件访问 | 不存在 | 无上传、文件选择器或文件读取逻辑 |
| 修改状态 | 不存在 | 单个静态 HTML，无写入接口 |
| 执行实验 | 不存在 | Runner 只作为归档结果展示，不部署执行端 |
| 原始证据访问 | 不存在 | Pages artifact 仅包含公开 Demo 目录，不发布证据、其他文档或 ZIP |
| Matrix / 对象存储凭据 | 不包含 | 不输出控制面地址、房间标识或凭据 |
| 本机路径与回环地址 | 不包含 | 构建和测试使用拒绝列表扫描 |
| Token、密钥与口令 | 不包含 | 构建和测试使用凭据模式扫描 |
| 浏览器主动网络请求 | 已禁用 | 无 JavaScript；CSP `connect-src 'none'` |
| 表单与外部跳转提交 | 已禁用 | 无表单；CSP `form-action 'none'` |
| 第三方脚本、字体、图片 | 不加载 | 所有样式内联；CSP 默认拒绝 |
| 实时运行误导 | 已避免 | 页首、正文和页尾均标注归档证据回放 |

静态 HTML 内的 CSP 已关闭脚本、连接、表单、对象和子框架。`frame-ancestors` 只能通过 HTTP 响应头可靠生效，不能依靠 HTML 的 CSP 元标签；如果选择支持自定义响应头的托管商，建议额外发送 `Content-Security-Policy: frame-ancestors 'none'`。GitHub Pages 不要求该配置才能安全展示当前无交互页面，但它属于静态托管的已知剩余项，不应宣称页面已通过响应头阻止第三方嵌入。

生成器采取 fail-closed 策略：如果 AT-004 不再是精确的三次 `71.875% → 97.8124976%`、六角色顺序变化、审批晚于执行、Trace 或哈希校验失败，静态页面不会生成。

## 发布前清单

- `python -B scripts/build_public_demo.py --check` 通过；
- 完整测试通过；
- AT-002/003/004 证据目录哈希在构建前后保持一致；
- 在桌面端和移动端检查页面；
- 在未登录窗口验证公网 URL；
- 页面显示 AT-004 `PASS / RESOLVED`、AT-002 `BLOCKED` 和非法篡改 `POLICY_VIOLATION / ROLLED_BACK`；
- 页面没有声称这是实时 Agent 运行。
