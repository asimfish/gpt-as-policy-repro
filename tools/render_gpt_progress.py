"""Render all primary-method results from one audit-qualified public snapshot."""
from html import escape as E
import json
from pathlib import Path
import re

START, END = '<!-- GPT_PROGRESS_START -->', '<!-- GPT_PROGRESS_END -->'
METHODS = {'gpt_only': 'GPT Direct', 'pi05_plus_gpt': 'π0.5 + GPT Hybrid'}
STATES = {'pending': '待运行', 'running': '运行中', 'interrupted': '中断待重试',
          'audit_pending': '完整终止 · 待审计'}
REASONS = {'model_capacity': '模型服务容量不足', 'network': '网络中断',
           'model_response_timeout': '模型响应超时',
           'supervisor_interrupted': '监督进程中断', 'infrastructure': '基础设施错误',
           'invalid_native_layout': '原生布局无效 · 排除',
           'missing_or_inconsistent_complete_audit': '完整审计缺失或不一致'}


def summary_html(data):
    s = data['summary']
    blocks = [f'<article><span>已审计完整回合</span><strong>{s["complete_method_runs"]}<small> / {s["planned_method_runs"]}</small></strong><p>完整原生失败也计入分母</p></article>',
              f'<article><span>已完成配对案例</span><strong>{s["completed_pairs"]}<small> / {s["planned_pairs"]}</small></strong><p>同一冻结布局与种子，两方法都完成</p></article>']
    for method, label in METHODS.items():
        own = s['methods'][method]['all_completed']
        paired = s['methods'][method]['paired_completed']
        rate = '—' if own['success_rate'] is None else f'{own["success_rate"]:.1%}'
        blocks.append(f'<article><span>{label} · 已完成样本</span><strong>{rate}</strong><p>成功 {own["successes"]} / {own["evaluated"]}；已配齐子集 {paired["successes"]} / {paired["evaluated"]}</p></article>')
    return '<div class="stats gpt-stats">' + ''.join(blocks) + '</div>'


def active_html(data):
    active = [(c, m) for c in data['cases'] for m in METHODS if c['methods'][m]['status'] == 'running']
    if not active:
        return '<p class="updated">本快照没有运行中案例；后台运行状态以新快照为准。</p>'
    return '<p class="updated">快照时正在运行：' + '；'.join(E(c['case_id']) + ' · ' + METHODS[m] for c, m in active) + '。运行中轨迹不计分。</p>'


def robolab_html(data):
    value = data.get('supplementary', {}).get('robolab')
    if not value:
        return ''
    states = dict(not_started='待启动', starting='仿真与策略服务启动中',
                  controller_running='持久控制器运行中',
                  controller_finished='回合收尾，待完整审计',
                  infrastructure_interrupted='基础设施中断，待排查')
    summary=value.get('summary',{})
    overview='' if not summary else f'<p>补充组已审计 {summary["complete_method_runs"]} / 100 个完整回合，配齐 {summary["completed_pairs"]} / 50 个案例。<a href="robolab-methods.html">查看补充矩阵、结果与完整回放 ↗</a></p>'
    case = '' if value['task'] is None else f' · {E(value["task"])} / seed {value["seed"]}'
    method = METHODS.get(value['method'],'Hybrid')
    steps = value['observed_control_steps']
    state='完整原生回合已审计' if value['action_audit_status']=='complete_native_episode' else states[value['status']]
    audit_note='完整动作审计通过，已计入补充分母' if value['action_audit_status']=='complete_native_episode' else '完整动作审计待完成，暂不计分'
    direct_note='已通过完整原生回合审计' if value['direct_implementation_status']=='native_episode_audited' else '已通过接口测试，正在进行原生回合验证'
    prefix=value.get('last_prefix_audit')
    evidence='' if not prefix else f'<p>此前 Hybrid 中断尝试已有 {prefix["decisions"]} 轮 / {prefix["native_actions"]} 步通过前缀动作核对；不是完整回合，不计分。<a href="{prefix["evidence"]}">下载前缀审计 ↗</a></p>'
    return f'<div class="panel" id="robolab-methods-progress"><h3>RoboLab · 两方法补充进度</h3>{overview}<p>冻结计划：50 个案例 × 两种方法，共 100 条轨迹。当前 {method}：{state}{case}；当前尝试已记录 {steps} 个控制步，{audit_note}。</p>{evidence}<p>公开仓库的 RoboLab 入口仅提供 Hybrid。自有 Direct EEF 适配器{direct_note}；历史 Direct 源码与 prompt 未提供。采用新的固定种子组，历史原始初态尚未恢复，环境等价性仍有限制。</p></div>'


def render(out):
    data = json.loads((out / 'data/gpt-methods-progress.json').read_text())
    assert data['schema'] == 'gpt_policy_progress.v2'
    episodes = {e['id']: e for e in data['episodes']}
    s, snapshot = data['summary'], E(data['snapshot'])
    stats = summary_html(data)
    supplement = robolab_html(data)
    bundle=data.get('infrastructure')
    bundle_html='' if not bundle else f'<div class="panel" id="infra-bundle-download"><h3>复现实验基建下载</h3><p>运行脚本、两方法队列、动作审计、冻结场景、Direct 接口、测试与 systemd 模板。已核对归档内全部文件；这是当前基建快照，全量实验仍在推进。</p><p><a href="{E(bundle["archive"])}" download>下载基建包 · {bundle["bytes"]/2**20:.2f} MiB ↓</a> · <a href="data/infrastructure-bundle.json">文件校验与版本 JSON ↓</a></p><details><summary>SHA256 校验</summary><code>{bundle["sha256"]}</code></details></div>'

    task_rows = []
    for task in data.get('task_summary', []):
        values = [task['methods'][m]['all_completed'] for m in METHODS]
        cells = ''.join(f'<td>{v["successes"]} / {v["evaluated"]}<small>平均 score {v["mean_score"]:.3f}</small></td>' if v['evaluated'] else '<td>待完成</td>' for v in values)
        task_rows.append(f'<tr><td>{E(task["task_label"])}</td>{cells}<td>{task["completed_pairs"]} / {task["planned_pairs"]}</td></tr>')
    task_table = '<section class="report-section"><div class="section-heading"><h2>逐任务独立结果</h2><a href="#gpt-rollouts">跳转到完整回放 ↓</a></div><p class="section-intro">每格为成功数 / 已审计完整回合数；平均 score 使用同一分母。未运行案例不能当作零分失败。</p><div class="panel table-wrap"><table><thead><tr><th>任务</th><th>GPT Direct</th><th>Hybrid</th><th>已配齐案例</th></tr></thead><tbody>' + ''.join(task_rows) + '</tbody></table></div></section>'
    coverage='50个配对案例的100条轨迹均已完整执行和审计；这是本项目全量主实验结果，历史环境和模型服务等价性仍有限制。' if s['complete_method_runs']==100 and s['completed_pairs']==50 else '当前是部分样本，任务覆盖尚不均衡，不能视为全量成功率或原报告数值的复现结论。'
    intro = '<p class="section-intro">计划为 RoboDojo 50 个冻结案例 × 两种方法，共 100 条完整轨迹。'+coverage+'</p>'
    block = f'''{START}<section class="report-section" id="main-methods"><div class="section-heading"><div><span class="eyebrow">PRIMARY REPRODUCTION / 两种主方法</span><h2>我们复现的 GPT Direct 与 Hybrid</h2></div><a class="text-link" href="gpt-methods.html">全部回放、50 案例矩阵与审计 ↗</a></div>{intro}{stats}{active_html(data)}<p class="updated">主方法状态快照（UTC） · {snapshot}</p><p class="table-note">仅完整原生终止且通过完整动作审计的回合计分；容量不足、网络与基础设施中断另列。<a href="data/gpt-methods-progress.json">下载主方法结果 ↗</a></p></section>{END}'''
    block = block.replace('<p class="updated">主方法状态快照', supplement + '<p class="updated">主方法状态快照', 1)
    for name in ('index.html', 'scenes.html'):
        path = out / name
        document = path.read_text()
        before, rest = document.split(START, 1)
        _, after = rest.split(END, 1)
        document = before + block + after
        baseline = re.search(r'<section class="stats" aria-label="前缀基线关键指标">.*?</section>', document, re.S)
        if baseline and baseline.start() < document.index(START):
            document = document[:baseline.start()] + document[baseline.end():]
            document = document.replace(END, END + baseline.group(0), 1)
        document = document.replace('href="#episodes">查看实验回放', 'href="gpt-methods.html#gpt-rollouts">查看主方法回放')
        document = document.replace('<a href="#results">01 独立结果</a>', '<a href="#main-methods">主方法结果</a><a href="#results">历史辅助结果</a>')
        document = re.sub(r'完整可计分主方法回合：\d+(?: / \d+)*', f'完整可计分主方法回合：{s["complete_method_runs"]} / {s["planned_method_runs"]}', document)
        if 'href="assets/gpt.css"' not in document:
            document = document.replace('</head>', '<link rel="stylesheet" href="assets/gpt.css"></head>')
        # Upgrade the legacy sentence once; later renders use the stable element.
        document = document.replace('Direct 中断；Hybrid 运行中。实时性以主方法状态快照为准，详见主方法页', '<span id="gpt-infra-progress"></span>')
        document = re.sub(r'<span id="gpt-infra-progress">.*?</span>',
                          f'<span id="gpt-infra-progress">{s["completed_pairs"]} / {s["planned_pairs"]} 对已完成，{s["complete_method_runs"]} / {s["planned_method_runs"]} 条已审计。<a href="gpt-methods.html">主方法结果与回放 ↗</a></span>', document)
        document = document.replace('<td>RoboLab · GPT Direct / hybrid</td><td>各 50 案例</td><td>未运行</td>',
                                    '<td>RoboLab · GPT Direct / hybrid</td><td>各 50 案例</td><td><span id="robolab-infra-progress"></span></td>')
        if supplement:
            supplemental_summary=data['supplementary']['robolab']['summary']
            document = re.sub(r'<span id="robolab-infra-progress">.*?</span>',
                              f'<span id="robolab-infra-progress">{supplemental_summary["complete_method_runs"]} / {supplemental_summary["planned_method_runs"]} 条已完整审计，{supplemental_summary["completed_pairs"]} / {supplemental_summary["planned_pairs"]} 对已完成。<a href="robolab-methods.html">补充结果与完整回放 ↗</a></span>', document)
        document=re.sub(r'<div class="panel" id="infra-bundle-download">.*?</div>',bundle_html,document,flags=re.S)
        # Do not leave a historical baseline date beside current primary counts.
        document = re.sub(r'(<p class="updated">)(?:数据快照|主方法快照) · [^<]*(</p>)',
                          rf'\g<1>主方法快照 · {snapshot}\g<2>', document, count=1)
        path.write_text(document)
    rows, cards = [], []
    for case in data['cases']:
        cells = []
        for method in METHODS:
            value = case['methods'][method]
            episode = episodes.get(value['episode_id'])
            if episode:
                status = 'success' if episode['success'] else 'failure'
                label = '成功' if episode['success'] else '原生失败'
                cells.append(f'<td><a class="badge {status}" href="#{episode["id"]}">{label} · {episode["score"]:.2f}</a><small>{episode["control_steps"]} 步 / {episode["decisions"]} 决策</small></td>')
            else:
                cells.append(f'<td><span class="badge pending">{STATES[value["status"]]}</span></td>')
        label = '已配齐' if case['paired_complete'] else '待配齐'
        rows.append(f'<tr><td>{E(case["task_label"])}<small>{E(case["identity"]["variant"])} · layout {case["identity"]["layout_id"]}</small></td>{"".join(cells)}<td>{label}</td></tr>')
    for episode in sorted(data['episodes'], key=lambda e: (e['case_id'], e['method'])):
        status = 'success' if episode['success'] else 'failure'
        modes = episode.get('actions_by_mode')
        modes_html = '' if modes is None else f'<p>student / edit / eef 控制步：{modes["student"]} / {modes["edit"]} / {modes["eef"]}。</p>'
        warning = '' if episode['supervisor_status'] == 'complete' else '<p>监督进程报告清理或收尾异常；完整原生结果与动作审计已核对，按原生终止结果计分。</p>'
        cards.append(f'''<article class="episode gpt-episode" id="{episode['id']}" data-task="{E(episode['identity']['task'])}" data-method="{episode['method']}" data-status="{status}" data-search="{E(episode['case_id'] + ' ' + episode['task_label'])}"><div class="episode-head"><div><span class="eyebrow">{episode['method_label']}</span><h3>{E(episode['task_label'])} · {E(episode['identity']['variant'])} / {episode['identity']['layout_id']}</h3></div><span class="badge {status}">{'成功' if episode['success'] else '原生失败'}</span></div><video controls playsinline preload="none" poster="{episode['poster']}" aria-label="{E(episode['case_id'])} {episode['method_label']} 完整回放"><source src="{episode['video']}" type="video/mp4"></video><div class="episode-meta"><span>原生动作 <b>{episode['control_steps']}</b></span><span>决策 <b>{episode['decisions']}</b></span><span>Score <b>{episode['score']:.2f}</b></span></div><details><summary>完整审计与案例数据 ↗</summary><div class="evidence-detail"><code>{E(episode['case_id'])}</code><p>原生终止：terminated={str(episode['terminated']).lower()}，truncated={str(episode['truncated']).lower()}；完整动作核对通过。</p>{modes_html}{warning}<p><a href="{episode['audit']}">下载完整审计 JSON ↓</a> · <a href="{episode['evidence']}">案例 JSON ↓</a></p></div></details></article>''')
    interrupted = [a for a in data['attempts'] if a['status'] in ('interrupted', 'audit_pending')]
    attempts_html = ''
    for attempt in interrupted:
        links = []
        if attempt.get('audit'):
            links.append(f'<a href="{attempt["audit"]}">前缀审计 {attempt["audited_control_steps"]} 步</a>')
        if attempt.get('video'):
            links.append(f'<a href="{attempt["video"]}">中断前回放 ↗</a>')
        attempts_html += f'<tr><td><code>{E(attempt["case_id"])}</code><small>{E(attempt["run_id"])}</small></td><td>{METHODS[attempt["method"]]}</td><td>{attempt["control_steps"]} / {attempt["decisions"]}</td><td>{REASONS[attempt["reason_class"]]}<small>{" · ".join(links)}</small></td></tr>'
    counts = '；'.join(f'{REASONS[k]} {v} 次' for k, v in data['interruptions']['by_reason'].items()) or '暂无'
    task_options = ''.join(f'<option value="{task}">{E(label)}</option>' for task, label in dict((c['identity']['task'], c['task_label']) for c in data['cases']).items())
    document = f'''<!doctype html><html lang="zh-CN" data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>GPT Direct / Hybrid · 独立复现结果</title><link rel="stylesheet" href="assets/site.css"><link rel="stylesheet" href="assets/gpt.css"><script src="assets/gpt.js" defer></script></head><body><header class="topbar"><div class="wrap top-inner"><a class="brand" href="scenes.html">GPT-AS-POLICY / 复现主页</a><button id="gpt-theme" class="theme-toggle" aria-label="切换主题">☀</button></div></header><main class="wrap"><section class="report-section"><span class="eyebrow">OUR EXPERIMENTS / RoboDojo 主实验</span><h1>GPT Direct 与 π0.5 + GPT</h1><p class="hero-lead">GPT-6 Astra · xhigh · 原仓库持久控制器</p>{intro}{stats}{active_html(data)}<p class="updated">结果快照（UTC） · {snapshot}</p></section><section class="report-section"><div class="section-heading"><h2>50 个冻结案例的配对矩阵</h2><a href="data/gpt-methods-progress.json">下载全部结果 JSON ↓</a></div><p class="section-intro">点击已完成结果可跳转到对应回放。配对使用相同面板、布局文件 SHA256 与种子；机器人关节状态核对单列，不能据此声称完整物理初态逐位相同。</p><details class="panel" open><summary>查看全部 50 个案例 · 已配齐 {s['completed_pairs']} 对</summary><div class="table-wrap"><table id="gpt-case-matrix"><thead><tr><th>冻结案例</th><th>GPT Direct</th><th>Hybrid</th><th>配对</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></details></section><section class="report-section" id="gpt-rollouts"><div class="section-heading"><h2>全部已审计完整回放</h2><span id="gpt-count" class="muted" aria-live="polite">{len(episodes)} 条</span></div><form class="filters" id="gpt-filters" onsubmit="return false"><label>任务<select id="gpt-task"><option value="all">全部任务</option>{task_options}</select></label><label>方法<select id="gpt-method"><option value="all">两种方法</option><option value="gpt_only">GPT Direct</option><option value="pi05_plus_gpt">Hybrid</option></select></label><label>原生结果<select id="gpt-status"><option value="all">全部结果</option><option value="success">成功</option><option value="failure">原生失败</option></select></label><label class="search-field">搜索<input type="search" id="gpt-search" placeholder="案例 ID 或任务名"></label><button type="reset" class="reset-filter">重置</button></form><div class="episode-grid">{''.join(cards)}</div><p id="gpt-empty" class="panel empty-state" hidden>没有匹配的已完成案例。</p></section><section class="report-section"><h2>中断与重试记录</h2><p class="section-intro">{counts}。完整原生失败保留在上面的计分回合中；此处基础设施、容量与网络中断不计作任务失败。每次重试重新启动物理回合，所有尝试均保留。</p><details class="panel"><summary>查看 {len(interrupted)} 条未计分尝试</summary><div class="table-wrap"><table><thead><tr><th>案例与运行</th><th>方法</th><th>控制步 / 决策</th><th>原因</th></tr></thead><tbody>{attempts_html}</tbody></table></div></details></section><section class="report-section"><h2>复现口径与证据边界</h2><div class="panel prose"><p>Direct 使用 GPTOnlyTools，π0.5 调用数必须为零；Hybrid 使用 RoboDojoTools，核对 student、edit、eef 对应的已执行原生动作。采用原生成功判定、得分与终止条件。</p><p>每个案例、每种方法选取首次通过完整审计的原生终止回合；完整失败也保留，不能从多次有效运行中挑最高分。只有通过完整动作审计并核对原生终止结果的回合进入分母。</p><p>审计验证了记录的模型工具调用、动作与执行回执；未独立重算 IK。导出时再次核对终止结果、模型身份文件的 SHA256。公开审计提供相对路径与哈希，不包含原始模型内部推理或服务器配置。</p><p>当前使用原仓库指定的 GPT-6 Astra / xhigh；历史完整模型服务配置未全部公开，等价性尚未验证。这是相同方法与冻结任务的独立运行，尚不能称为历史配置和论文数值的完全复现。已配齐样本与全部已完成样本分别列示，避免不同覆盖范围造成误读。</p><p><a href="data/gpt-media-manifest.json">完整视频来源与发布 SHA256 ↓</a> · <a href="scenes.html#reading">原报告详细解读 ↗</a> · <a href="scenes.html#infrastructure">基础设施与历史辅助验证 ↗</a></p></div></section></main><footer class="wrap"><p>主方法快照（UTC） · {snapshot}<br><a href="scenes.html">返回复现主页 ↗</a></p></footer></body></html>'''
    document = document.replace('<section class="report-section"><div class="section-heading"><h2>50 个冻结案例', task_table + '<section class="report-section"><div class="section-heading"><h2>50 个冻结案例', 1)
    document = document.replace('<p class="updated">结果快照', supplement + '<p class="updated">结果快照', 1)
    (out / 'gpt-methods.html').write_text(document)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('out', type=Path)
    render(parser.parse_args().out)
