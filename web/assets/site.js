'use strict';
const root=document.documentElement,theme=document.querySelector('#theme-toggle');
function setTheme(value){root.dataset.theme=value;theme.textContent=value==='dark'?'☀':'☾';theme.setAttribute('aria-label',value==='dark'?'切换为浅色主题':'切换为深色主题');try{localStorage.setItem('gpt-policy-theme',value)}catch{}}
try{setTheme(localStorage.getItem('gpt-policy-theme')||'dark')}catch{setTheme('dark')}
theme.addEventListener('click',()=>setTheme(root.dataset.theme==='dark'?'light':'dark'));
const task=document.querySelector('#task-filter'),method=document.querySelector('#method-filter'),status=document.querySelector('#status-filter'),search=document.querySelector('#case-search');
const cards=[...document.querySelectorAll('.episode')],count=document.querySelector('#episode-count');
function filter(){let n=0;const q=search.value.trim().toLowerCase();for(const card of cards){const shown=(task.value==='all'||card.dataset.task===task.value)&&(method.value==='all'||card.dataset.method===method.value)&&(status.value==='all'||card.dataset.status===status.value)&&card.dataset.search.toLowerCase().includes(q);card.hidden=!shown;if(shown)n++;else card.querySelector('video')?.pause()}count.textContent=`${n} / ${cards.length} 条案例记录`;document.querySelector('#empty-state').hidden=n>0}
for(const input of [task,method,status,search])input.addEventListener('input',filter);
document.querySelector('.filters').addEventListener('reset',()=>setTimeout(filter,0));
function focusCase(id){const card=document.getElementById(id);if(!card?.classList.contains('episode'))return;task.value='all';method.value='all';status.value='all';search.value='';filter();cards.forEach(c=>c.classList.remove('focused'));card.classList.add('focused');card.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'instant':'smooth',block:'center'});history.replaceState(null,'','#'+id)}
document.querySelectorAll('[data-focus]').forEach(link=>link.addEventListener('click',event=>{event.preventDefault();focusCase(link.dataset.focus)}));
document.querySelectorAll('.task-link').forEach(button=>button.addEventListener('click',()=>{task.value=button.dataset.task;method.value='pi05_prefix15';status.value='all';search.value='';filter();document.querySelector('#episodes').scrollIntoView()}));
document.querySelector('#show-chunk50').addEventListener('click',()=>{task.value='all';method.value='pi05_chunk50';status.value='all';search.value='';filter();document.querySelector('#episodes').scrollIntoView()});
const videos=[...document.querySelectorAll('video')];videos.forEach(video=>video.addEventListener('play',()=>videos.forEach(other=>{if(other!==video)other.pause()})));
filter();if(location.hash){const id=decodeURIComponent(location.hash.slice(1));if(document.getElementById(id)?.classList.contains('episode'))setTimeout(()=>focusCase(id),100)}
