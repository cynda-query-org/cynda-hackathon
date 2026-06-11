// ── Sticky nav on scroll ────────────────────────────────────────
const nav = document.getElementById('main-nav');
window.addEventListener('scroll', () => {
  nav.classList.toggle('scrolled', window.scrollY > 60);
}, { passive: true });

// ── HIGHLIGHT SECTION ────────────────────────────────────────────
// Live demo: calls POST /public-demo on the backend with the user's
// question and maintains conversation history client-side.

const BACKEND_URL = '__BACKEND_URL__';

const DEMO_SUGGESTIONS = [
  'Which product categories generate the most revenue?',
  'What is the average order value per customer state?',
  'How many orders were delivered late?',
];

let demoHistory = [];

function escapeHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function highlightSQL(sql) {
  return hljs.highlight(sql, { language: 'sql' }).value;
}

const _SVG_DOWN = '<svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor" style="pointer-events:none;display:block"><polygon points="1,2 9,2 5,8"/></svg>';
const _SVG_UP   = '<svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor" style="pointer-events:none;display:block"><polygon points="5,2 1,8 9,8"/></svg>';

function buildSqlBlock(sql) {
  const wrap = document.createElement('div');
  wrap.className = 'demo-code-block collapsed';
  const header = document.createElement('div');
  header.className = 'demo-code-header';
  const label = document.createElement('span');
  label.className = 'demo-code-label';
  label.textContent = 'SQL';
  const actions = document.createElement('div');
  actions.className = 'demo-code-actions';
  const copyBtn = document.createElement('button');
  copyBtn.className = 'demo-code-btn';
  copyBtn.type = 'button';
  copyBtn.textContent = 'Copy';
  copyBtn.addEventListener('click', () => {
    navigator.clipboard.writeText(sql).then(() => {
      copyBtn.textContent = 'Copied!';
      copyBtn.classList.add('copied');
      setTimeout(() => { copyBtn.textContent = 'Copy'; copyBtn.classList.remove('copied'); }, 2000);
    });
  });
  const toggleBtn = document.createElement('button');
  toggleBtn.className = 'demo-code-btn demo-code-toggle';
  toggleBtn.type = 'button';
  toggleBtn.innerHTML = _SVG_DOWN;
  toggleBtn.addEventListener('click', () => {
    const collapsed = wrap.classList.toggle('collapsed');
    toggleBtn.innerHTML = collapsed ? _SVG_DOWN : _SVG_UP;
  });
  actions.appendChild(copyBtn);
  actions.appendChild(toggleBtn);
  header.appendChild(label);
  header.appendChild(actions);
  const pre = document.createElement('pre');
  const code = document.createElement('code');
  code.innerHTML = highlightSQL(sql);
  pre.appendChild(code);
  wrap.appendChild(header);
  wrap.appendChild(pre);
  return wrap;
}

function buildTableBlock(tableHtml) {
  const wrap = document.createElement('div');
  wrap.className = 'cynda-table-block collapsed';
  const header = document.createElement('div');
  header.className = 'cynda-table-header';
  const label = document.createElement('span');
  label.className = 'cynda-table-label';
  label.textContent = 'TABLE';
  const actions = document.createElement('div');
  actions.className = 'cynda-table-actions';
  const copyBtn = document.createElement('button');
  copyBtn.className = 'cynda-table-btn';
  copyBtn.type = 'button';
  copyBtn.textContent = 'Copy';
  copyBtn.addEventListener('click', () => {
    const tableEl = wrap.querySelector('.cynda-table');
    const tsv = Array.from(tableEl.querySelectorAll('tr'))
      .map(r => Array.from(r.querySelectorAll('th,td')).map(c => c.textContent).join('\t'))
      .join('\n');
    navigator.clipboard.writeText(tsv).then(() => {
      copyBtn.textContent = 'Copied!';
      copyBtn.classList.add('copied');
      setTimeout(() => { copyBtn.textContent = 'Copy'; copyBtn.classList.remove('copied'); }, 2000);
    });
  });
  const toggleBtn = document.createElement('button');
  toggleBtn.className = 'cynda-table-btn cynda-table-toggle';
  toggleBtn.type = 'button';
  toggleBtn.innerHTML = _SVG_DOWN;
  toggleBtn.addEventListener('click', () => {
    const collapsed = wrap.classList.toggle('collapsed');
    toggleBtn.innerHTML = collapsed ? _SVG_DOWN : _SVG_UP;
  });
  actions.appendChild(copyBtn);
  actions.appendChild(toggleBtn);
  header.appendChild(label);
  header.appendChild(actions);
  const body = document.createElement('div');
  body.className = 'cynda-table-body';
  body.innerHTML = tableHtml;
  wrap.appendChild(header);
  wrap.appendChild(body);
  return wrap;
}

function renderBubbleContent(text, tableHtml) {
  const frag = document.createDocumentFragment();
  const codeBlockRe = /```(?:sql)?\s*([\s\S]*?)```/g;
  const proseTexts = [], sqlBlocks = [];
  let last = 0, match;
  while ((match = codeBlockRe.exec(text)) !== null) {
    if (match.index > last) {
      const p = text.slice(last, match.index).trim();
      if (p) proseTexts.push(p);
    }
    sqlBlocks.push(match[1].trim());
    last = match.index + match[0].length;
  }
  if (last < text.length) {
    const p = text.slice(last).trim();
    if (p) proseTexts.push(p);
  }
  proseTexts.forEach(p => {
    const div = document.createElement('div');
    div.className = 'demo-bubble-text';
    div.innerHTML = marked.parse(p);
    frag.appendChild(div);
  });
  if (tableHtml) frag.appendChild(buildTableBlock(tableHtml));
  sqlBlocks.forEach(sql => frag.appendChild(buildSqlBlock(sql)));
  return frag;
}

function demoBubble(type, text, tableHtml) {
  const isCynda = type === 'cynda';
  const el = document.createElement('div');
  el.className = `demo-bubble ${type}`;
  const icon = document.createElement('div');
  icon.className = `demo-bubble-icon ${type}`;
  icon.textContent = isCynda ? 'C' : 'Y';
  const body = document.createElement('div');
  body.className = 'demo-bubble-body';
  const sender = document.createElement('div');
  sender.className = `demo-bubble-sender${isCynda ? ' cynda' : ''}`;
  sender.textContent = isCynda ? 'Cynda' : 'You';
  body.appendChild(sender);
  body.appendChild(renderBubbleContent(text, tableHtml));
  el.appendChild(icon);
  el.appendChild(body);
  return el;
}

function demoTypingBubble() {
  const el = document.createElement('div');
  el.className = 'demo-bubble cynda';
  el.id = 'demo-typing';
  el.innerHTML = `
    <div class="demo-bubble-icon cynda">C</div>
    <div class="demo-bubble-body">
      <div class="demo-bubble-sender cynda">Cynda</div>
      <div class="demo-typing">
        <div class="demo-typing-dot"></div>
        <div class="demo-typing-dot"></div>
        <div class="demo-typing-dot"></div>
      </div>
    </div>`;
  return el;
}

function scrollDemoToBottom() {
  const msgs = document.getElementById('demo-messages');
  msgs.scrollTop = msgs.scrollHeight;
}

function renderSuggestions() {
  const el = document.getElementById('demo-suggestions');
  el.innerHTML = DEMO_SUGGESTIONS.map(s =>
    `<button class="demo-pill" type="button">${s}</button>`
  ).join('');
  el.querySelectorAll('.demo-pill').forEach(btn => {
    btn.addEventListener('click', () => {
      document.getElementById('demo-input').value = btn.textContent;
      el.innerHTML = '';
      document.getElementById('demo-form').dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    });
  });
}

document.getElementById('demo-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const input = document.getElementById('demo-input');
  const sendBtn = document.getElementById('demo-send-btn');
  const msgs = document.getElementById('demo-messages');
  const question = input.value.trim();
  if (!question) return;

  document.getElementById('demo-suggestions').innerHTML = '';
  input.value = '';
  sendBtn.disabled = true;

  msgs.appendChild(demoBubble('user', question));
  const typing = demoTypingBubble();
  msgs.appendChild(typing);
  scrollDemoToBottom();

  try {
    const res = await fetch(`${BACKEND_URL}/public-demo`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, history: demoHistory }),
    });
    typing.remove();
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      msgs.appendChild(demoBubble('cynda', err.detail || `Error ${res.status}`));
    } else {
      const data = await res.json();
      msgs.appendChild(demoBubble('cynda', data.answer, data.table_html || null));
      demoHistory.push({ role: 'user', content: question });
      demoHistory.push({ role: 'assistant', content: data.answer });
    }
  } catch {
    typing.remove();
    msgs.appendChild(demoBubble('cynda', 'Something went wrong. Please try again.'));
  } finally {
    sendBtn.disabled = false;
    scrollDemoToBottom();
    input.focus();
  }
});

renderSuggestions();
// ── END HIGHLIGHT SECTION ────────────────────────────────────────
