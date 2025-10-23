/* global Telegram */
const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
  tg.MainButton.hide();
  tg.setHeaderColor("secondary_bg_color");
}

const results = document.getElementById('results');
const bigCounter = document.getElementById('big-counter');
const toggleBtn = document.getElementById('toggle-btn');
const chains = document.getElementById('chains');
const fab = document.getElementById('fab');

let running = true;
let checked = 0;

function addLine({balanceZero, phrase}){
  const el = document.createElement('div');
  el.className = 'result-item';
  const balance = document.createElement('span');
  balance.className = 'balance';
  balance.textContent = balanceZero ? 'Balance 0' : 'Balance > 0';
  const pipe = document.createElement('span');
  pipe.className = 'pipe';
  pipe.textContent = '|';
  const status = document.createElement('span');
  status.className = 'status';
  status.textContent = balanceZero ? 'Wallet check' : 'Found';
  const pipe2 = pipe.cloneNode(true);
  const phraseEl = document.createElement('span');
  phraseEl.className = 'phrase';
  phraseEl.textContent = phrase;
  el.append(balance, pipe, status, pipe2, phraseEl);
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
    addLine({balanceZero:false, phrase});
  } else {
    addLine({balanceZero:true, phrase});
  }
}

const timer = setInterval(tick, 12);

// Toggle
 toggleBtn.addEventListener('click', () => {
  running = !running;
  toggleBtn.textContent = running ? 'Stop' : 'Start';
});

// Chain selection visuals
chains?.addEventListener('click', (e) => {
  const btn = e.target.closest('.chain');
  if(!btn) return;
  chains.querySelectorAll('.chain').forEach(el => el.classList.remove('active'));
  btn.classList.add('active');
});

// Floating search button
fab?.addEventListener('click', ()=>{
  // For demo, jump counter
  checked += 100;
  bigCounter.textContent = checked.toLocaleString();
});

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
