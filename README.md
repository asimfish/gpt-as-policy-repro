# GPT-as-Policy 独立复现报告

在线站点：https://asimfish.github.io/gpt-as-policy-repro/

静态报告包含独立测量、逐任务矩阵、完整视频回放、案例 JSON、原报告解读和基建进度。公开报告复算与自有实验分开列示。页面支持深浅主题、手机浏览、任务/协议/结果筛选及案例深链接。

## 更新数据

需要 Python 3.10+、Pillow、Markdown 3.7、FFmpeg。数据源为实验输出目录，至少包含 `independent_report.json`、`prefix15_cohort_audit.json`、冻结案例清单和原生回放。

```sh
python3 -m pip install -r requirements.txt
python3 tools/build_site.py --source /path/to/experiment --out docs
python3 tools/verify_site.py docs
python3 -m http.server 8080 --directory docs
```

生成器采用明确字段列表导出案例身份、控制步、原生结果、模型身份和决策摘要。原始服务器配置、接入信息、机器路径和完整系统日志不进入公开数据。视频转换为 H.264 / 15 FPS / 1440 px 宽，保留整段时间线；`data/media-manifest.json` 记录原始视频和发布视频 SHA256。

`docs/` 是独立发布目录，无构建服务或外部 JavaScript 依赖。GitHub Pages 发布本仓库 `docs/site` 分支的 `/docs` 目录。

## 结果口径

- `pi05_prefix15`：每次预测 50 步，执行前 15 步再推理；不含 GPT。
- `pi05_chunk50`：缓存完整 50 步，以 15+15+15+5 分片传输；分片间不推理。
- 原生失败计入成功率，原生无效布局和基础设施中断不计入。
- RoboLab reset / 相机验证单列，不当作策略回合。

来源：[原报告](https://anonymous-report-421.github.io/public-website/?lang=en&view=1)、[上游代码](https://github.com/anonymous-report-421/GPT-as-Policy)。版式参考 [GoAI 场景看板](https://asimfish.github.io/goai-dashboard/scenes.html)。

## 浏览器验收

启动上面的本地 HTTP 服务后，运行 `npm install` 和 `npm run verify:browser`。也可设置 `BASE_URL` 验证线上站点，`CHROME_PATH` 指定 Chrome 可执行文件。验收覆盖桌面和 390 px 手机宽度、筛选、空结果、案例深链接、主题持久化和真实视频播放。结果和截图保存在 `.artifacts/`。

## 主方法状态更新

主板先展示 GPT Direct / π0.5 + GPT 的自有实验。`gpt-methods.html` 包含全部完整回放、
50 案例配对矩阵、筛选和中断记录；状态源为 `docs/data/gpt-methods-progress.json`（v2）。
生成器读取冻结面板和各运行的完整动作审计，核对原生终止、分数、步数、模型身份、
SHA256 与布局身份。选取每案例每方法首次通过完整审计的原生终止回合，完整失败也保留。
此前完整回合若尚未审计，不允许跳过它挑选后续高分回合。

运行以下命令重新生成、验证并预览主方法报告，无须手工编辑快照：

```bash
python3 tools/build_gpt_site.py --source /path/to/experiment --out docs
python3 -m unittest discover -s tools -p test_gpt_site.py
python3 tools/verify_site.py docs
```

仅原生有效完整回合且通过完整动作审计才计分；网络、容量、基础设施中断另列。
全部已完成样本与已配齐子集使用独立分母。任务覆盖不均衡时不能外推全量成功率。
模型为 GPT-6 Astra / xhigh，不能当作历史模型配置相同的复现。审计核对已执行关节动作，
不独立重算 IK；关节状态哈希也不代表完整物理初态。公开字段不含凭据、机器路径或模型内部推理。
完整构建会调用同一主方法生成器；`data/gpt-media-manifest.json` 保存每条完整视频的来源与发布 SHA256。

## 定时发布

`tools/publish_gpt_progress.py` 每次执行一个发布周期：加锁、检查分支和工作区、生成报告、
验证全部站点、提交限定的生成文件、普通 push，最后核对在线页面和 JSON 的精确字节。
在线部署尚未完成时使用新查询参数重试，最多等待 5 分钟；核对提交中的页面、JSON、JS 和 CSS
精确字节。超时记为 `pushed_pending_online_verification` 并保留独立待验记录，不覆盖已验证证据。
它通过已存在的 Git credential helper 读取授权，不保存凭据，不修改实验控制器或队列。

```bash
python3 tools/publish_gpt_progress.py --source /path/to/experiment \
  --credentials-repo /path/to/authorized-git-repository
```

生产环境使用 `gpt-policy-report-progress.timer` 每 10 分钟运行一次。编辑生成页面前先停止
该 timer；存在源码修改、用户暂存内容或意外文件时发布周期会退出，保留工作区。
发布回退使用普通 revert，不改写已发布历史。
