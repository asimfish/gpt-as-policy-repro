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
