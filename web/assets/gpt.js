'use strict';
const theme = document.querySelector('#gpt-theme');
function setTheme(value) {
  document.documentElement.dataset.theme = value;
  theme.textContent = value === 'dark' ? '☀' : '☾';
  theme.setAttribute('aria-label', value === 'dark' ? '切换为浅色主题' : '切换为深色主题');
  try { localStorage.setItem('gpt-policy-theme', value); } catch {}
}
try { setTheme(localStorage.getItem('gpt-policy-theme') || 'dark'); } catch { setTheme('dark'); }
theme.addEventListener('click', () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));
const task = document.querySelector('#gpt-task'), method = document.querySelector('#gpt-method');
const status = document.querySelector('#gpt-status'), search = document.querySelector('#gpt-search');
const cards = [...document.querySelectorAll('.gpt-episode')];
function filter() {
  let n = 0;
  for (const card of cards) {
    const shown = (task.value === 'all' || card.dataset.task === task.value)
      && (method.value === 'all' || card.dataset.method === method.value)
      && (status.value === 'all' || card.dataset.status === status.value)
      && card.dataset.search.toLowerCase().includes(search.value.trim().toLowerCase());
    card.hidden = !shown;
    if (shown) n++; else card.querySelector('video').pause();
  }
  document.querySelector('#gpt-count').textContent = `${n} / ${cards.length} 条`;
  document.querySelector('#gpt-empty').hidden = n > 0;
}
for (const input of [task, method, status, search]) input.addEventListener('input', filter);
document.querySelector('#gpt-filters').addEventListener('reset', () => setTimeout(filter, 0));
function focusEpisode() {
  const card = document.getElementById(location.hash.slice(1));
  if (card?.classList.contains('gpt-episode')) {
    task.value = method.value = status.value = 'all'; search.value = ''; filter();
    card.scrollIntoView({block: 'start'});
  }
}
window.addEventListener('hashchange', focusEpisode);
filter(); focusEpisode();
