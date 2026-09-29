"""Render the main board from the reviewed public progress snapshot, without raw logs."""
import json
from html import escape
from pathlib import Path

START = '<!-- GPT_PROGRESS_START -->'
END = '<!-- GPT_PROGRESS_END -->'


def render(out):
    data = json.loads((out / 'data/gpt-methods-progress.json').read_text())
    direct, hybrid = data['direct'], data['hybrid']
    assert direct['eligible'] == direct['complete'] and hybrid['eligible'] == hybrid['complete']
    snapshot = escape(data['snapshot'])
    steps = hybrid['audited_control_steps']
    decisions = hybrid['audited_decisions']
    status = {'running':'运行中', 'capacity_interrupted':'模型服务容量不足，中断', 'native_completed':'完整原生回合'}[hybrid['status']]
    current = data.get('active_campaign')
    active = '' if current is None else f"<p>下一组冻结案例：{escape(current['case_id'])}，{escape(current['status'])}；按 Direct → Hybrid 顺序执行，前述中断记录保留。</p>"
    block = f'''{START}<section class="report-section" id="main-methods"><div class="section-heading"><div><span class="eyebrow">PRIMARY REPRODUCTION / 两种主方法</span><h2>GPT Direct 与 π0.5 + GPT</h2></div><a class="text-link" href="gpt-methods.html">回放与审计证据 ↗</a></div><p>冻结计划：每种方法 50 个配对案例。当前已有完整配对案例：<b>{data.get('summary',{}).get('eligible_pairs',0)}</b>；以下只统计原生完整终止回合。以下为快照，运行进度不代表任务成功。</p><div class="published-grid"><article class="panel"><h3>GPT Direct · {"成功" if direct["success"] else "失败"}</h3><p>原生完整回合：{direct["control_steps"]} 步、{direct["decisions"]} 次决策，score {direct.get("score")}. 已通过终止条件与逐动作审计。</p><a href="{escape(direct['audit'])}">逐动作审计 ↗</a></article><article class="panel"><h3>π0.5 + GPT · {status}</h3><p>已审计前 {steps} 步、{decisions} 次决策；student {hybrid['actions_by_mode']['student']} 步、edit {hybrid['actions_by_mode']['edit']} 步、eef 接管 {hybrid['actions_by_mode']['eef']} 步。原生回合到达 1050 步上限，任务未成功，计入失败分母。</p><a href="{escape(hybrid['audit'])}">前缀动作审计 ↗</a></article><article class="panel"><h3>证据与边界</h3><p>真实 GPT-6 Astra / xhigh，原版持久控制器；布局 0 的两次运行：场景布局记录与机器人 14 维关节状态哈希分别一致，不代表完整物理状态逐位一致。动作记录核对误差为零；未独立重算 IK，也不据此断言任务成功。</p><a href="data/gpt-methods-progress.json">下载状态快照 ↗</a> · <a href="data/gpt-initial-pairing.json">初态配对证据 ↗</a></article></div>{active}<p class="updated">主方法状态快照 · {snapshot}</p></section>{END}'''
    for name in ('index.html', 'scenes.html'):
        path = out / name
        document = path.read_text()
        before, rest = document.split(START, 1)
        _, after = rest.split(END, 1)
        path.write_text(before + block + after)
    video = ''
    if hybrid.get('video'):
        video = f"<video controls playsinline preload='none' style='width:100%;height:auto' aria-label='Hybrid 已执行轨迹'><source src='{escape(hybrid['video'])}' type='video/mp4'></video><p>已执行的完整原生时间线；可计分回合。</p>"
    path = out / 'gpt-methods.html'
    document = path.read_text()
    direct_start = '<section class="panel report-section"><h2>GPT Direct：网络中断，未完成</h2>'
    direct_end = '<section class="panel report-section"><h2>π0.5 + GPT（Hybrid）</h2>'
    d_before, d_rest = document.split(direct_start, 1)
    _, d_after = d_rest.split(direct_end, 1)
    dvideo = f"<video controls playsinline preload='none' style='width:100%;height:auto' aria-label='GPT Direct 布局1完整回放'><source src='{escape(direct['video'])}' type='video/mp4'></video>"
    direct_html = f'''<section class="panel report-section"><h2>GPT Direct：{'成功' if direct['success'] else '失败'}</h2><p>排列最大数字 · 冻结布局 1。原生完整回合 {direct['control_steps']} 步、{direct['decisions']} 次决策，score {direct['score']}；终止条件与逐动作审计均通过。</p>{dvideo}<p>完整原生回放；计入主方法结果。</p><p><a href="{escape(direct['audit'])}">下载完整动作审计</a> · <a href="data/gpt-methods-progress.json">下载实验状态</a></p></section>'''
    document = d_before + direct_html + direct_end + d_after
    start = '<section class="panel report-section"><h2>π0.5 + GPT（Hybrid）</h2>'
    before, rest = document.split(start, 1)
    _, after = rest.split('</section>', 1)
    path.write_text(before + start + video + f'<p>同一冻结场景：{status}。已独立审计前 {decisions} 次决策、{steps} 个原生动作，动作核对误差为零。student / edit / eef 分别为 {hybrid["actions_by_mode"]["student"]} / {hybrid["actions_by_mode"]["edit"]} / {hybrid["actions_by_mode"]["eef"]} 步；审计不包含独立 IK 重算。Hybrid 运行到原生 1050 步上限，任务未成功，计入失败分母。</p><p>状态快照：{snapshot}。<a href="{escape(hybrid["audit"])}">下载 Hybrid 前缀审计</a></p></section>' + after)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('out', type=Path)
    render(parser.parse_args().out)
