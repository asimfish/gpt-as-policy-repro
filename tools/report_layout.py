"""Shared presentation for the report; all values come from audited public data."""
from datetime import datetime
from html import escape as E
import json
from pathlib import Path
import re


def navigation(theme_id='theme-toggle', current='overview'):
    links=[('overview','scenes.html','报告'),('dojo','gpt-methods-valid.html','RoboDojo'),
           ('lab','robolab-methods.html','RoboLab'),('comparison','blog-comparison.html','原始结果对照')]
    items=''.join(f'<a href="{url}"'+(' aria-current="page"' if key==current else '')+f'>{label}</a>' for key,url,label in links)
    return f'<header class="topbar"><div class="wrap top-inner"><a class="brand" href="scenes.html"><span class="brand-mark">G↗</span><span>GPT-as-Policy<small>INDEPENDENT REPRODUCTION</small></span></a><nav class="page-navigation" aria-label="报告页面">{items}</nav><div class="top-right"><a class="repo-link" href="https://github.com/asimfish/gpt-as-policy-repro">Code ↗</a><button id="{theme_id}" class="theme-toggle" aria-label="切换为深色主题" title="切换主题">☾</button></div></div></header>'


def contents(items):
    return '<aside class="report-toc" aria-label="本页目录"><span>ON THIS PAGE</span><nav>'+''.join(f'<a href="{E(url,quote=True)}">{E(label)}</a>' for url,label in items)+'</nav><p>以实际执行与审计证据为准。</p></aside>'


def timestamp(value):
    try:return datetime.fromisoformat(value.replace('Z','+00:00')).strftime('%Y.%m.%d · %H:%M UTC')
    except (ValueError,AttributeError):return E(value)


def chart(title,subtitle,rows,identifier):
    bars=[]
    for label,value,detail,kind in rows:
        if value is None:
            bar='<span class="chart-unknown">尚无完整成绩</span>';number='—'
        else:
            assert 0<=value<=100
            bar=f'<span class="chart-track"><span class="chart-bar {kind}" style="width:{value:.4f}%"></span></span>'
            number=f'{value:.1f}'
        bars.append(f'<div class="chart-row"><span class="chart-label">{E(label)}<small>{E(detail)}</small></span>{bar}<b>{number}</b></div>')
    return f'<figure class="result-chart" id="{identifier}"><figcaption><h3>{E(title)}</h3><p>{E(subtitle)}</p></figcaption><div class="chart-scale"><span>0</span><span>50</span><span>100</span></div>'+''.join(bars)+'</figure>'


def benchmark_charts(dojo,lab):
    rows=[]
    for name,data in [('RoboDojo',dojo),('RoboLab',lab)]:
        if not data:continue
        for method,label,kind in [('gpt_only','GPT Direct','direct'),('pi05_plus_gpt','Hybrid','hybrid')]:
            m=data['summary']['methods'][method]['all_completed']
            rows.append((name+' · '+label,None if m['success_rate'] is None else 100*m['success_rate'],f'{m["successes"]} / {m["evaluated"]} 个完整回合',kind))
    scores=[]
    for method,label,kind in [('gpt_only','GPT Direct','direct'),('pi05_plus_gpt','Hybrid','hybrid')]:
        m=dojo['summary']['methods'][method]['all_completed']
        value=m.get('mean_score')
        scores.append((label,None if value is None else 100*value,f'RoboDojo · n={m["evaluated"]}',kind))
    return '<div class="chart-grid">'+chart('原生任务成功率','本次独立运行 · Success rate (%)',rows,'native-success-chart')+chart('RoboDojo 平均任务得分','原生得分 × 100 · 完整失败保留',scores,'native-score-chart')+'</div>'


def comparison_charts(value):
    rates=[];scores=[]
    for method,label in [('gpt_only','GPT Direct'),('pi05_plus_gpt','Hybrid')]:
        for source,source_label,kind in [('original','作者公开记录','original'),('reproduction','本次独立运行','direct' if method=='gpt_only' else 'hybrid')]:
            m=value['robodojo']['methods'][method][source]
            rates.append((label+' · '+source_label,100*m['success_rate'],f'{m["successes"]} / {m["episodes"]} 个记录',kind))
            scores.append((label+' · '+source_label,None if m['mean_score'] is None else 100*m['mean_score'],f'有得分的记录 n={m["score_samples"]}',kind))
    return '<div class="chart-grid">'+chart('RoboDojo 成功率对照','原记录与独立运行 · 口径差异见下表',rates,'comparison-success-chart')+chart('RoboDojo 平均得分对照','Score × 100 · 缺失得分保持未知',scores,'comparison-score-chart')+'</div>'


def board_hero(out,original):
    path=out/'data/gpt-methods-valid-progress.json'
    dojo=json.loads(path.read_text()) if path.exists() else original
    path=out/'data/robolab-methods-progress.json'
    lab=json.loads(path.read_text()) if path.exists() else None
    total=dojo['summary']['complete_method_runs']+(lab['summary']['complete_method_runs'] if lab else 0)
    pairs=dojo['summary']['completed_pairs']+(lab['summary']['completed_pairs'] if lab else 0)
    return f'''<section class="hero research-hero" id="overview"><span class="eyebrow accent">ROBOTICS / INDEPENDENT REPRODUCTION</span><h1>GPT as an Embodied Policy<span>独立复现与原始结果对照</span></h1><p class="hero-lead">GPT Direct 与 π0.5 + GPT Hybrid 的真实闭环评测</p><p class="paper-meta">GPT-6 Astra · xhigh <span>RoboDojo + RoboLab</span><span>{timestamp(original['snapshot'])}</span></p><div class="hero-actions"><a class="button primary" href="#main-methods">查看实验结果 ↓</a><a class="button" href="gpt-methods-valid.html#gpt-rollouts">完整轨迹 ↗</a><a class="button" href="blog-comparison.html">原始结果对照 ↗</a><a class="button" href="#downloads">数据与代码 ↓</a></div><div class="paper-summary"><span>实验摘要</span><p>两种方法，两个机器人基准。当前所选评测已审计 <b>{total} 个完整回合</b>、<b>{pairs} 个配对案例</b>，成功和完整失败均保留。复原历史控制器的独立实验继续推进；历史环境、实现与模型服务的严格等价性尚未证明。</p></div></section>''',dojo,lab


def decorate_board(document,out,original):
    if 'id="overview"' not in document:return document
    hero,dojo,lab=board_hero(out,original)
    document=re.sub(r'<section class="hero[^\"]*" id="overview">.*?</section>',lambda _:hero,document,count=1,flags=re.S)
    document=re.sub(r'<header class="topbar">.*?</header>',lambda _:navigation(),document,count=1,flags=re.S)
    document=re.sub(r'<nav class="section-nav".*?</nav>','<nav class="section-nav" aria-label="报告章节"><a href="#main-methods">01 实验结果</a><a href="gpt-methods-valid.html#gpt-rollouts">02 RoboDojo 轨迹</a><a href="robolab-methods.html">03 RoboLab 轨迹</a><a href="blog-comparison.html">04 原始结果对照</a><a href="#reading">05 方法与解读</a><a href="#downloads">数据下载 ↓</a></nav>',document,count=1,flags=re.S)
    start='<!-- GPT_PROGRESS_START -->';end='<!-- GPT_PROGRESS_END -->'
    before,rest=document.split(start,1);block,after=rest.split(end,1)
    # The home uses the selected, separately named panel. The original 99-run
    # page and data retain their own denominators and every old attempt.
    if (out/'data/gpt-methods-valid-progress.json').exists():
        s=dojo['summary'];direct=s['methods']['gpt_only']['all_completed'];hybrid=s['methods']['pi05_plus_gpt']['all_completed']
        supplemental=re.search(r'<details class="supplemental-note">.*?</details>',block,re.S)
        block=f'''<section class="report-section" id="main-methods"><div class="section-heading"><div><span class="eyebrow">01 / INDEPENDENT EVALUATION</span><h2>从模型推理，到机器人执行</h2></div><a class="text-link" href="gpt-methods-valid.html">完整矩阵与回放 ↗</a></div><p class="section-intro">所选 RoboDojo 与 RoboLab 面板分别包含 50 个案例，每个案例执行两种方法。仅完整原生终止并通过动作审计的轨迹进入分母。</p>{benchmark_charts(dojo,lab)}<div class="method-cards"><article><span class="method-dot direct"></span><h3>GPT Direct</h3><p>模型读取观测与状态，直接输出短段末端控制。此方法不调用 π0.5。</p><a href="gpt-methods-valid.html#gpt-rollouts">RoboDojo · 成功 {direct['successes']} / {direct['evaluated']} ↗</a></article><article><span class="method-dot hybrid"></span><h3>π0.5 + GPT Hybrid</h3><p>π0.5 提议动作，模型接受、纠正或接管，并核对实际执行的控制步。</p><a href="gpt-methods-valid.html#gpt-rollouts">RoboDojo · 成功 {hybrid['successes']} / {hybrid['evaluated']} ↗</a></article></div><div class="panel cohort-note"><b>面板与证据口径</b><p>主页展示独立补齐面板 {s['complete_method_runs']} / 100 条、{s['completed_pairs']} / 50 对。一个原生无效的 layout 4 配对改用预冻结 layout 5；其余 49 对共享原回合。<a href="gpt-methods.html">原面板 {original['summary']['complete_method_runs']} / 100 条及全部失败记录 ↗</a>。两个面板不能相加作为独立样本。</p></div></section>'''
        block=block.replace('<a href="gpt-methods.html">原面板',f'<a href="gpt-methods.html" aria-label="原面板完整可计分主方法回合：{original["summary"]["complete_method_runs"]} / 100">原面板',1)
        if supplemental:block+=supplemental.group(0)
    document=before+start+block+end+after
    document=document.replace(timestamp(original['snapshot'])+'</span></p>',f'<time datetime="{E(original["snapshot"],quote=True)}">{timestamp(original["snapshot"])}</time></span></p>',1)
    # Keep auxiliary experiments available, without letting them precede or
    # dominate the two-method reproduction.
    if '<!-- AUXILIARY_ARCHIVE_START -->' not in document:
        end_index=document.index(end)+len(end)
        reading_match=re.search(r'<section\b[^>]*\bid="reading"[^>]*>',document[end_index:])
        if reading_match:
            reading=end_index+reading_match.start()
            legacy=document[end_index:reading]
            document=document[:end_index]+'<!-- AUXILIARY_ARCHIVE_START --><details class="auxiliary-archive"><summary><span>历史辅助实验</span><small>π0.5 基线、前缀对照与原回放 · 展开查看 ↗</small></summary>'+legacy+'</details><!-- AUXILIARY_ARCHIVE_END -->'+document[reading:]
    if 'class="report-layout"' not in document:
        marker='</nav>'
        nav_start=document.index('<nav class="section-nav"')
        pos=document.index(marker,nav_start)+len(marker)
        toc=contents([('#main-methods','实验结果'),('gpt-methods-valid.html#gpt-rollouts','RoboDojo 回放'),('robolab-methods.html','RoboLab 回放'),('blog-comparison.html','原始结果对照'),('#reading','方法与解读'),('#infrastructure','基础设施与证据'),('#reference-links','参考与社区'),('#downloads','下载复现材料')])
        document=document[:pos]+'<div class="report-layout">'+toc+'<div class="report-body">'+document[pos:]
        document=document.replace('</main>','</div></div></main>',1)
    if 'id="reference-links"' not in document:
        refs='<section class="report-section" id="reference-links"><span class="eyebrow">REFERENCES / COMMUNITY</span><h2>参考报告与社区资源</h2><div class="reference-list"><a href="https://anonymous-report-421.github.io/public-website/?lang=en&amp;view="><span>01</span><div><b>GPT 6 Astra as an Embodied Policy</b><small>原始研究报告、实验方法与公开轨迹</small></div><i>↗</i></a><a href="https://robodojo-benchmark.com/report/gpt-6-astra-eval"><span>02</span><div><b>GPT-6 Astra on RoboDojo</b><small>官方评测报告、基准与案例分析</small></div><i>↗</i></a><a href="https://github.com/zjwzcx/Awesome-Astra-Embodied-AI"><span>03</span><div><b>Awesome Astra Embodied AI</b><small>具身智能评测与社区项目索引</small></div><i>↗</i></a></div></section>'
        document=re.sub(r'<section\b[^>]*\bid="downloads"[^>]*>',lambda match:refs+match.group(0),document,count=1)
    return document.replace('data-theme="dark"','data-theme="light"',1)


def decorate_method_page(document,current='dojo',theme_id='gpt-theme'):
    document=re.sub(r'<header class="topbar">.*?</header>',lambda _:navigation(theme_id,current),document,count=1,flags=re.S)
    if current=='dojo' and 'id="method-task-results"' in document and 'class="report-layout"' not in document:
        first=document.index('</section>')+len('</section>')
        toc=contents([('#method-task-results','逐任务结果'),('#gpt-case-matrix','50 案例配对矩阵'),('#gpt-rollouts','完整轨迹回放'),('blog-comparison.html','原始结果对照'),('scenes.html#downloads','下载复现材料')])
        document=document[:first]+'<div class="report-layout">'+toc+'<div class="report-body">'+document[first:]
        document=document.replace('</main>','</div></div></main>',1)
    return document.replace('data-theme="dark"','data-theme="light"',1)


def decorate_supplemental(out):
    for filename in ['robolab-methods.html','robolab.html']:
        path=out/filename
        if not path.exists():continue
        document=decorate_method_page(path.read_text(),'lab','theme-toggle')
        if '<script src="assets/site.js"' not in document:
            document=document.replace('</head>','<script src="assets/site.js" defer></script></head>',1)
        path.write_text(document)
