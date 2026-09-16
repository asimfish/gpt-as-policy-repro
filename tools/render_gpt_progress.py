"""Render the main board from the reviewed public progress snapshot, without raw logs."""
import json
from html import escape
from pathlib import Path

START = '<!-- GPT_PROGRESS_START -->'
END = '<!-- GPT_PROGRESS_END -->'


def render(out):
    data = json.loads((out / 'data/gpt-methods-progress.json').read_text())
    direct, hybrid = data['direct'], data['hybrid']
    assert not direct['eligible'] and not hybrid['eligible']
    assert not direct['complete'] and not hybrid['complete']
    snapshot = escape(data['snapshot'])
    steps = hybrid['audited_control_steps']
    decisions = hybrid['audited_decisions']
    block = f'''{START}<section class="report-section" id="main-methods"><div class="section-heading"><div><span class="eyebrow">PRIMARY REPRODUCTION / 两种主方法</span><h2>GPT Direct 与 π0.5 + GPT</h2></div><a class="text-link" href="gpt-methods.html">回放与审计证据 ↗</a></div><p>冻结计划：每种方法 50 个配对案例。当前主方法可计分完整回合：<b>0</b>；成功率暂无。以下为快照，运行进度不代表任务成功。</p><div class="published-grid"><article class="panel"><h3>GPT Direct · 中断</h3><p>已执行并审计 {direct['control_steps']} / {direct['native_horizon']} 步，{direct['decisions']} 次决策。模型连接中断，未达到原生终止条件，不计入成功率分母。</p><a href="{escape(direct['audit'])}">逐动作审计 ↗</a></article><article class="panel"><h3>π0.5 + GPT · 运行中</h3><p>已审计前 {steps} 步、{decisions} 次决策；student {hybrid['actions_by_mode']['student']} 步、edit {hybrid['actions_by_mode']['edit']} 步、eef 接管 {hybrid['actions_by_mode']['eef']} 步。尚无完整任务结果。</p><a href="{escape(hybrid['audit'])}">前缀动作审计 ↗</a></article><article class="panel"><h3>证据与边界</h3><p>真实 GPT-6 Astra / xhigh，原版持久控制器；两次运行的初始物理状态哈希一致。动作记录核对误差为零；未独立重算 IK，也不据此断言任务成功。</p><a href="data/gpt-methods-progress.json">下载状态快照 ↗</a></article></div><p class="updated">主方法状态快照 · {snapshot}</p></section>{END}'''
    for name in ('index.html', 'scenes.html'):
        path = out / name
        document = path.read_text()
        before, rest = document.split(START, 1)
        _, after = rest.split(END, 1)
        path.write_text(before + block + after)
    path = out / 'gpt-methods.html'
    document = path.read_text()
    start = '<section class="panel report-section"><h2>π0.5 + GPT（Hybrid）</h2>'
    before, rest = document.split(start, 1)
    _, after = rest.split('</section>', 1)
    path.write_text(before + start + f'<p>同一冻结场景仍在运行。已独立审计前 {decisions} 次决策、{steps} 个原生动作，动作核对误差为零。student / edit / eef 分别为 {hybrid["actions_by_mode"]["student"]} / {hybrid["actions_by_mode"]["edit"]} / {hybrid["actions_by_mode"]["eef"]} 步；审计不包含独立 IK 重算。未达到原生终止条件，不计算成功率或两方法胜负。</p><p>状态快照：{snapshot}。<a href="{escape(hybrid["audit"])}">下载 Hybrid 前缀审计</a></p></section>' + after)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('out', type=Path)
    render(parser.parse_args().out)
