/* global Telegram */
const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
  tg.setHeaderColor("secondary_bg_color");
  // Configure MainButton for Start/Stop control
  tg.MainButton.setText("Stop");
  tg.MainButton.show();
}

const results = document.getElementById('results');
const bigCounter = document.getElementById('big-counter');
const toggleBtn = document.getElementById('toggle-btn');

let running = true;
let checked = 0;

function addLine(text, found=false){
  const el = document.createElement('div');
  el.className = 'result-item';
  el.textContent = text;
  if (found) el.style.borderLeft = '4px solid #22c55e';
  results.appendChild(el);
  results.scrollTop = results.scrollHeight;
}

function tick(){
  if(!running) return;
  checked += 1;
  bigCounter.textContent = checked.toLocaleString();
  const words = WORDS;
  const phrase = [0,1,2].map(()=>words[Math.floor(Math.random()*words.length)]).join(' ');
  if(checked % 37 === 0 && Math.random() < 0.001){
    addLine(`Balance > 0 | Found | ${phrase}`, true);
  } else {
    addLine(`Balance 0 | Wallet check | ${phrase}`);
  }
}

const timer = setInterval(tick, 12);

// Toggle via on-screen button (fallback for browsers)
toggleBtn.addEventListener('click', () => {
  running = !running;
  toggleBtn.textContent = running ? 'Stop' : 'Start';
  if (tg) tg.MainButton.setText(running ? 'Stop' : 'Start');
});

// Toggle via Telegram MainButton
if (tg) {
  tg.onEvent('mainButtonClicked', () => {
    running = !running;
    tg.MainButton.setText(running ? 'Stop' : 'Start');
    toggleBtn.textContent = running ? 'Stop' : 'Start';
  });
}

// Apply Telegram theme colors to CSS variables
function applyThemeFromTelegram(){
  if (!tg) return;
  const p = tg.themeParams || {};
  const root = document.documentElement.style;
  if (p.bg_color) root.setProperty('--bg', p.bg_color);
  if (p.secondary_bg_color) root.setProperty('--panel', p.secondary_bg_color);
  if (p.button_color) root.setProperty('--button-bg', p.button_color);
  if (p.button_text_color) root.setProperty('--button-fg', p.button_text_color);
  if (p.text_color) root.setProperty('--text', p.text_color);
  if (p.hint_color) root.setProperty('--muted', p.hint_color);
  if (p.link_color) root.setProperty('--accent', p.link_color);
}
applyThemeFromTelegram();
if (tg) tg.onEvent('themeChanged', applyThemeFromTelegram);

// Example of calling backend
async function fetchHealth(){
  try{
    const r = await fetch('/api/health');
    const j = await r.json();
    console.log('server health:', j);
  }catch(err){ console.warn('no backend running', err); }
}
fetchHealth();

const WORDS = (
  "private gun alien elite ten behave inject rotate say vague title prosper"
).split(' ').concat([
  "empower","profit","body","fog","buffalo","cabbage","tube","course","host","initial",
  "spider","glimpse","dog","category","pump","cinnamon","pride","inspire","day","carnivore",
  "boost","waste","fragile","tortoise","warm","drive","dead","palm","stamina","fragile",
  "witness","kite","kind","relax","brick","hour","lab","soul","solution","thirty",
  "quit","chisel","unable","throne","veteran","jaguar","sight","quarter","powder","aerobic",
  "despair","stumble","curtain","prayer","velvet","harbor","glory","stable","oxygen","explain",
  "bubble","dawn","zebra","ramp","noble","silver","cargo","couch","ember","forest",
  "magnet","gargle","marble","pencil","radar","salad","talent","umpire","vacuum","wagon",
  "yacht","zero","acorn","bacon","cannon","daisy","engine","fabric","galaxy","hammer",
  "icicle","jungle","kitten","ladder","mantle","nectar","oyster","pepper","quartz","rocket",
  "sandal","tartan","utopia","violet","willow","xenon","yellow","zephyr",
]);
