/* StatLines — daily sports stat-deduction game
 * Vanilla JS. Loads puzzles/<date>.json + players.json, tracks per-sport progress in localStorage.
 */
(() => {
  'use strict';

  const SPORT_ORDER = ['nba', 'mlb', 'nfl'];
  const STAGES_PER_SPORT = 5;
  const MAX_STRIKES = 3; // wrong guesses allowed per SPORT, shared across its 5 stages
  const TOTAL_STAGES = SPORT_ORDER.length * STAGES_PER_SPORT;
  const WIN_THRESHOLD = 12;
  const STAGE_NAMES = ['Stage 1', 'Stage 2', 'Stage 3', 'Stage 4', 'Stage 5'];
  const SPORTS_META = {
    nba: { name: 'NBA', ball: '🏀', accent: 'orange' },
    mlb: { name: 'MLB', ball: '⚾', accent: 'sky' },
    nfl: { name: 'NFL', ball: '🏈', accent: 'emerald' },
  };

  const ACCENTS = {
    orange: { text: 'text-orange-400', bg: 'bg-orange-500', ring: 'ring-orange-400', border: 'border-orange-400', soft: 'bg-orange-500/10' },
    sky: { text: 'text-sky-400', bg: 'bg-sky-500', ring: 'ring-sky-400', border: 'border-sky-400', soft: 'bg-sky-500/10' },
    emerald: { text: 'text-emerald-400', bg: 'bg-emerald-500', ring: 'ring-emerald-400', border: 'border-emerald-400', soft: 'bg-emerald-500/10' },
  };

  // ---------- DOM ----------
  const $ = (id) => document.getElementById(id);
  const el = {
    dateLabel: $('dateLabel'), tracker: $('tracker'), progressBar: $('progressBar'), resultsBtn: $('resultsBtn'),
    tabs: $('tabs'), loading: $('loading'), error: $('error'), game: $('game'),
    stagePills: $('stagePills'), card: $('card'), stageLabel: $('stageLabel'), stageType: $('stageType'),
    strikes: $('strikes'), stageContext: $('stageContext'), statGrid: $('statGrid'), hints: $('hints'),
    resultBanner: $('resultBanner'), guessForm: $('guessForm'), guessInput: $('guessInput'),
    suggestions: $('suggestions'), guessBtn: $('guessBtn'), formMsg: $('formMsg'), guessList: $('guessList'),
    nextBtn: $('nextBtn'), resetBtn: $('resetBtn'),
    modal: $('modal'), modalBackdrop: $('modalBackdrop'), modalClose: $('modalClose'), modalDate: $('modalDate'),
    modalTitle: $('modalTitle'), modalSub: $('modalSub'), modalScore: $('modalScore'), modalMatrix: $('modalMatrix'),
    modalShare: $('modalShare'), copyBtn: $('copyBtn'), copyMsg: $('copyMsg'),
  };

  // ---------- App state ----------
  let data = null;        // { sports, players }
  let day = null;         // { nba: [...], mlb: [...], nfl: [...] }
  let dateKey = '';       // 'YYYY-MM-DD'
  let activeSport = 'nba';
  const progress = {};    // sport -> { stageIndex, stages: [{ status, guesses: [{ name, correct }] }] }
  const viewIndex = {};   // sport -> stage being viewed (transient, for reviewing past stages)
  let suggestionItems = [];
  let highlighted = -1;

  // ---------- Helpers ----------
  const normalize = (s) =>
    String(s).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]/g, '');

  const escapeHtml = (s) =>
    String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  const todayLocal = () => {
    const d = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  };

  // Today's puzzle if published, otherwise the most recent earlier day.
  const pickDay = (dates) => {
    const keys = [...dates].sort();
    const today = todayLocal();
    if (keys.includes(today)) return today;
    const past = keys.filter((k) => k <= today);
    return past.length ? past[past.length - 1] : keys[0];
  };

  // Hints ship lightly obfuscated (reversed base64 of UTF-8 JSON) so they
  // aren't readable at a glance in the network tab. Mirrors encode_secret() in
  // pipeline/common.py. This is not security — anyone can decode it.
  const decodeSecret = (secret) => {
    const bin = atob(secret.split('').reverse().join(''));
    const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0));
    return JSON.parse(new TextDecoder().decode(bytes));
  };

  // localStorage can be missing or throw (private windows, sandboxed frames).
  const store = {
    get: (k) => { try { return localStorage.getItem(k); } catch (_) { return null; } },
    set: (k, v) => { try { localStorage.setItem(k, v); } catch (_) { /* progress just won't persist */ } },
    remove: (k) => { try { localStorage.removeItem(k); } catch (_) { /* ignore */ } },
  };

  const fetchJson = async (url) => {
    const res = await fetch(url, { cache: 'no-store' });
    if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`);
    return res.json();
  };

  // v2: strikes became per-sport; old per-stage saves are ignored.
  const KEY_PREFIX = 'statlines:v2';
  const storageKey = (sport) => `${KEY_PREFIX}:${dateKey}:${sport}`;
  const modalSeenKey = () => `${KEY_PREFIX}:${dateKey}:modalSeen`;
  const activeSportKey = () => `${KEY_PREFIX}:${dateKey}:activeSport`;

  const freshProgress = () => ({
    stageIndex: 0,
    stages: Array.from({ length: STAGES_PER_SPORT }, () => ({ status: 'pending', guesses: [] })),
  });

  const loadProgress = (sport) => {
    try {
      const raw = store.get(storageKey(sport));
      if (raw) {
        const p = JSON.parse(raw);
        if (p && Array.isArray(p.stages) && p.stages.length === STAGES_PER_SPORT) return p;
      }
    } catch (_) { /* corrupted -> reset */ }
    return freshProgress();
  };

  const saveProgress = (sport) => {
    store.set(storageKey(sport), JSON.stringify(progress[sport]));
  };

  const wrongCount = (stage) => stage.guesses.filter((g) => !g.correct).length;
  const sportStrikes = (sport) => progress[sport].stages.reduce((n, s) => n + wrongCount(s), 0);
  const strikesLeft = (sport) => Math.max(0, MAX_STRIKES - sportStrikes(sport));
  const isDone = (stage) => stage.status === 'solved' || stage.status === 'failed';
  const sportSolved = (sport) => progress[sport].stages.filter((s) => s.status === 'solved').length;
  const sportComplete = (sport) => progress[sport].stages.every(isDone);
  const totalSolved = () => SPORT_ORDER.reduce((n, s) => n + sportSolved(s), 0);
  const allComplete = () => SPORT_ORDER.every(sportComplete);
  const sportMeta = (sport) => data.sports[sport];
  const accent = (sport) => ACCENTS[sportMeta(sport).accent] || ACCENTS.orange;

  // Answers never reach the browser in readable form. Each stage carries a slow
  // PBKDF2 fingerprint per accepted name; a guess that matches also derives the key
  // that decrypts {answer, reveal}. Mirrors lock_answer() in pipeline/common.py.
  const b64bytes = (b64) => Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  const hex = (buf) => [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('');
  async function unlockGuess(guess, lock) {
    const g = normalize(guess);
    if (!g || !lock) return null;
    const base = await crypto.subtle.importKey('raw', new TextEncoder().encode(g), 'PBKDF2', false, ['deriveBits']);
    const bits = new Uint8Array(await crypto.subtle.deriveBits(
      { name: 'PBKDF2', salt: b64bytes(lock.salt), iterations: lock.iter, hash: 'SHA-256' }, base, 384));
    const check = hex(bits.slice(0, 16));
    const hit = lock.keys.find((k) => k.h === check);
    if (!hit) return null;
    const hk = await crypto.subtle.importKey('raw', bits.slice(16), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
    const data = b64bytes(hit.c);
    const out = new Uint8Array(data.length);
    for (let i = 0; i < data.length; i += 32) {
      const ctr = new Uint8Array(4);
      new DataView(ctr.buffer).setUint32(0, i / 32);
      const block = new Uint8Array(await crypto.subtle.sign('HMAC', hk, ctr));
      for (let j = 0; j < 32 && i + j < data.length; j++) out[i + j] = data[i + j] ^ block[j];
    }
    return JSON.parse(new TextDecoder().decode(out));
  }

  // ---------- Rendering ----------
  function renderHeader() {
    const solved = totalSolved();
    el.tracker.textContent = `${solved}/${TOTAL_STAGES}`;
    el.progressBar.style.width = `${(solved / TOTAL_STAGES) * 100}%`;
    el.progressBar.className = `h-full transition-all duration-500 bg-gradient-to-r ${
      solved >= WIN_THRESHOLD ? 'from-emerald-500 to-emerald-300' : 'from-amber-500 to-amber-300'
    }`;
    el.resultsBtn.classList.toggle('hidden', !allComplete());
  }

  function renderTabs() {
    el.tabs.innerHTML = '';
    SPORT_ORDER.forEach((sport) => {
      const meta = sportMeta(sport);
      const a = accent(sport);
      const active = sport === activeSport;
      const done = sportComplete(sport);
      const attempted = progress[sport].stages.filter(isDone).length;
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = [
        'relative flex items-center justify-center gap-2 py-2.5 rounded-t-xl text-sm font-semibold transition',
        active ? `bg-white/[0.06] ${a.text} border-b-2 ${a.border}` : 'text-slate-400 hover:text-slate-200 hover:bg-white/[0.03] border-b-2 border-transparent',
      ].join(' ');
      btn.innerHTML = `
        <span class="text-lg">${meta.ball}</span>
        <span class="tracking-wide">${escapeHtml(meta.name)}</span>
        ${done
          ? '<span class="ml-0.5 inline-flex items-center justify-center w-5 h-5 rounded-full bg-emerald-500 text-black text-xs font-black" title="All 5 stages attempted">✓</span>'
          : `<span class="font-mono text-[11px] text-slate-500">${attempted}/5</span>`}
      `;
      btn.addEventListener('click', () => switchSport(sport));
      el.tabs.appendChild(btn);
    });
  }

  function renderStagePills() {
    const p = progress[activeSport];
    const a = accent(activeSport);
    const ball = sportMeta(activeSport).ball;
    const viewing = viewIndex[activeSport];
    el.stagePills.innerHTML = '';
    p.stages.forEach((stage, i) => {
      const reachable = i <= p.stageIndex || sportComplete(activeSport);
      const b = document.createElement('button');
      b.type = 'button';
      b.disabled = !reachable;
      let face = `<span class="font-mono text-sm">${i + 1}</span>`;
      let cls = 'bg-white/5 text-slate-500 border-white/10';
      if (stage.status === 'solved') { face = `<span class="text-lg">${ball}</span>`; cls = `${a.soft} border-white/20`; }
      else if (stage.status === 'failed') { face = '<span class="text-lg">🔴</span>'; cls = 'bg-red-500/10 border-red-500/30'; }
      else if (i === p.stageIndex) { cls = `bg-white/10 text-white ${a.border}`; }
      const ring = i === viewing ? `ring-2 ring-offset-2 ring-offset-[#0b0f17] ${a.ring}` : '';
      b.className = `w-11 h-11 rounded-full border flex items-center justify-center transition ${cls} ${ring} ${reachable ? 'hover:scale-105' : 'opacity-50 cursor-not-allowed'}`;
      b.innerHTML = face;
      b.title = `${STAGE_NAMES[i]}${stage.status === 'pending' ? '' : ' · ' + (stage.status === 'solved' ? 'Solved' : stage.skipped ? 'Not reached' : 'Strike Out')}`;
      b.addEventListener('click', () => { if (reachable) { viewIndex[activeSport] = i; renderGame(); } });
      el.stagePills.appendChild(b);
    });
  }

  function renderStrikes() {
    const ball = sportMeta(activeSport).ball;
    const used = Math.min(sportStrikes(activeSport), MAX_STRIKES);
    el.strikes.innerHTML = '';
    for (let k = 0; k < MAX_STRIKES; k++) {
      const span = document.createElement('span');
      span.className = 'inline-flex w-9 h-9 items-center justify-center rounded-full transition';
      if (k < used) {
        span.textContent = '🔴';
        span.title = 'Strike';
        if (k === used - 1) span.className += ' pop';
      } else {
        span.textContent = ball;
        span.title = 'Strike remaining';
      }
      el.strikes.appendChild(span);
    }
  }

  function renderGame() {
    const sport = activeSport;
    const p = progress[sport];
    const i = viewIndex[sport];
    const puzzle = day[sport][i];
    const stage = p.stages[i];
    const meta = sportMeta(sport);
    const a = accent(sport);
    const wrong = wrongCount(stage);
    const done = isDone(stage);

    renderHeader();
    renderTabs();
    renderStagePills();
    renderStrikes();

    el.stageLabel.innerHTML = `<span class="${a.text}">${meta.ball} ${escapeHtml(meta.name)}</span> · ${STAGE_NAMES[i]}`;
    el.stageType.textContent = puzzle.type;
    el.stageContext.textContent = puzzle.context || '';

    // Stat grid (scoreboard)
    el.statGrid.innerHTML = puzzle.stats.map((s) => `
      <div class="scoreboard-cell rounded-xl border border-white/10 px-3 py-3 text-center">
        <div class="text-[10px] uppercase tracking-widest text-slate-500">${escapeHtml(s.label)}</div>
        <div class="font-mono text-2xl font-bold text-amber-300 mt-0.5">${escapeHtml(s.value)}</div>
      </div>`).join('');

    // Hints: one revealed per wrong guess
    const revealed = puzzle.hints.slice(0, Math.min(wrong, puzzle.hints.length));
    el.hints.innerHTML = revealed.map((h, k) => `
      <div class="fade-in flex gap-3 items-start rounded-lg border border-amber-400/20 bg-amber-400/5 px-3 py-2 text-sm">
        <span class="font-mono text-[10px] mt-0.5 px-1.5 py-0.5 rounded bg-amber-400/20 text-amber-300">HINT ${k + 1}</span>
        <span class="text-slate-200">${escapeHtml(h)}</span>
      </div>`).join('') || (done ? '' : `<p class="text-xs text-slate-500">Each wrong guess costs one of your ${meta.name} strikes and unlocks a hint.</p>`);

    // Result banner
    if (done) {
      const solved = stage.status === 'solved';
      el.resultBanner.className = `mt-5 rounded-xl border px-4 py-3 fade-in ${solved ? 'border-emerald-400/40 bg-emerald-500/10' : 'border-red-500/40 bg-red-500/10'}`;
      el.resultBanner.innerHTML = `
        <div class="font-display text-2xl tracking-wider ${solved ? 'text-emerald-300' : 'text-red-300'}">
          ${solved ? `${meta.ball} SOLVED${wrong === 0 ? ' — FIRST TRY!' : ''}` : stage.skipped ? '🔴 NOT REACHED' : '🔴 STRIKE OUT'}
        </div>
        ${!solved ? `<div class="text-xs text-red-200/80 mt-0.5">${stage.skipped ? `${escapeHtml(meta.name)} ran out of strikes before this stage.` : `That was your 3rd ${escapeHtml(meta.name)} strike — the rest of this sport counts as strikeouts.`}</div>` : ''}
        ${solved && stage.unlocked ? `<div class="text-sm text-slate-200 mt-0.5"><strong>${escapeHtml(stage.unlocked.answer)}</strong></div>
        ${stage.unlocked.reveal ? `<div class="text-xs text-slate-400 mt-0.5">${escapeHtml(stage.unlocked.reveal)}</div>` : ''}`
        : !solved ? `<div class="text-sm text-slate-300 mt-1">The answer unlocks tomorrow under <em>Yesterday's answers</em>.</div>` : ''}`;
    } else {
      el.resultBanner.className = 'hidden';
      el.resultBanner.innerHTML = '';
    }

    // Input
    el.guessForm.classList.toggle('hidden', done);
    el.guessInput.disabled = done;
    el.guessBtn.disabled = done;
    el.formMsg.textContent = done ? '' : strikesMsg(sport);
    hideSuggestions();

    // Guess history
    el.guessList.innerHTML = stage.guesses.map((g) => `
      <span class="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium border ${
        g.correct ? 'border-emerald-400/50 bg-emerald-500/10 text-emerald-200' : 'border-red-500/40 bg-red-500/10 text-red-200 line-through decoration-red-400/70'
      }">${g.correct ? meta.ball : '🔴'} ${escapeHtml(g.name)}</span>`).join('');

    // Next button
    renderNextButton(done, i);

    if (!done) setTimeout(() => el.guessInput.focus({ preventScroll: true }), 0);
  }

  function strikesMsg(sport) {
    const left = strikesLeft(sport);
    return `${left} ${sportMeta(sport).name} strike${left === 1 ? '' : 's'} left for this sport`;
  }

  function renderNextButton(done, i) {
    const p = progress[activeSport];
    if (!done) { el.nextBtn.classList.add('hidden'); return; }
    el.nextBtn.classList.remove('hidden');
    if (!sportComplete(activeSport) && i < p.stageIndex) {
      el.nextBtn.textContent = `Back to ${STAGE_NAMES[p.stageIndex]} →`;
      el.nextBtn.dataset.action = 'resume';
    } else if (!sportComplete(activeSport)) {
      el.nextBtn.textContent = 'Next Stage →';
      el.nextBtn.dataset.action = 'next';
    } else if (!allComplete()) {
      const nextSport = SPORT_ORDER.find((s) => !sportComplete(s));
      const how = strikesLeft(activeSport) === 0 ? 'struck out' : 'complete';
      el.nextBtn.textContent = `${sportMeta(activeSport).name} ${how} — On to ${sportMeta(nextSport).ball} ${sportMeta(nextSport).name} →`;
      el.nextBtn.dataset.action = 'sport:' + nextSport;
    } else {
      el.nextBtn.textContent = '🏆 View Daily Results';
      el.nextBtn.dataset.action = 'results';
    }
  }

  // ---------- Actions ----------
  function switchSport(sport) {
    activeSport = sport;
    store.set(activeSportKey(), sport);
    if (viewIndex[sport] == null) viewIndex[sport] = progress[sport].stageIndex;
    el.guessInput.value = '';
    renderGame();
  }

  let checking = false;
  async function submitGuess(raw) {
    if (checking) return;
    const name = raw.trim();
    const sport = activeSport;
    const p = progress[sport];
    const i = viewIndex[sport];
    const stage = p.stages[i];
    if (isDone(stage) || i !== p.stageIndex) return;
    if (!name) { flashMsg('Type a player name first.'); return; }
    if (stage.guesses.some((g) => normalize(g.name) === normalize(name))) {
      flashMsg('You already guessed that player.');
      return;
    }

    const puzzle = day[sport][i];
    checking = true;
    el.guessBtn.disabled = true;
    el.guessBtn.textContent = '…';
    let unlocked = null;
    try {
      unlocked = await unlockGuess(name, puzzle.lock);
    } finally {
      checking = false;
      el.guessBtn.disabled = false;
      el.guessBtn.textContent = 'Guess';
    }
    if (activeSport !== sport || isDone(stage)) return;
    const correct = !!unlocked;
    stage.guesses.push({ name, correct });

    if (correct) {
      stage.status = 'solved';
      stage.unlocked = unlocked;
    } else if (sportStrikes(sport) >= MAX_STRIKES) {
      // 3rd strike for this sport: this stage and every later one are strikeouts.
      stage.status = 'failed';
      p.stages.forEach((s, k) => {
        if (k > i && s.status === 'pending') { s.status = 'failed'; s.skipped = true; }
      });
    }

    saveProgress(sport);
    el.guessInput.value = '';
    renderGame();

    if (!correct) {
      el.card.classList.remove('shake');
      void el.card.offsetWidth; // restart animation
      el.card.classList.add('shake');
    }

    if (allComplete() && !store.get(modalSeenKey())) {
      store.set(modalSeenKey(), '1');
      setTimeout(openModal, 900);
    }
  }

  function flashMsg(msg) {
    el.formMsg.textContent = msg;
    el.formMsg.classList.add('text-amber-300');
    setTimeout(() => {
      el.formMsg.classList.remove('text-amber-300');
      const stage = progress[activeSport].stages[viewIndex[activeSport]];
      if (!isDone(stage)) el.formMsg.textContent = strikesMsg(activeSport);
    }, 1800);
  }

  function handleNext() {
    const action = el.nextBtn.dataset.action;
    const p = progress[activeSport];
    if (action === 'resume') {
      viewIndex[activeSport] = p.stageIndex;
      renderGame();
    } else if (action === 'next') {
      p.stageIndex = Math.min(p.stageIndex + 1, STAGES_PER_SPORT - 1);
      viewIndex[activeSport] = p.stageIndex;
      saveProgress(activeSport);
      renderGame();
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } else if (action && action.startsWith('sport:')) {
      switchSport(action.slice(6));
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } else if (action === 'results') {
      openModal();
    }
  }

  // ---------- Autocomplete ----------
  // players.json lists each sport's names most-famous first, so list position
  // is the tie-breaker. Normalized forms are precomputed once per sport.
  const searchIndex = {};
  function indexFor(sport) {
    if (!searchIndex[sport]) {
      searchIndex[sport] = (data.players[sport] || []).map((name, rank) => ({
        name,
        rank,
        full: normalize(name),
        words: name.split(/[\s.\-']+/).map(normalize).filter(Boolean),
      }));
    }
    return searchIndex[sport];
  }

  function updateSuggestions() {
    const raw = el.guessInput.value;
    const q = normalize(raw);
    const stage = progress[activeSport].stages[viewIndex[activeSport]];
    if (!q || isDone(stage)) { hideSuggestions(); return; }
    const tokens = raw.split(/[\s.\-']+/).map(normalize).filter(Boolean);
    const guessed = new Set(stage.guesses.map((g) => normalize(g.name)));

    const scored = [];
    for (const p of indexFor(activeSport)) {
      if (guessed.has(p.full)) continue;
      let score = -1;
      if (p.full.startsWith(q)) score = 0;                                   // "kevind" → Kevin Durant
      else if (tokens.every((t) => p.words.some((w) => w.startsWith(t)))) score = 1; // "dur" / "kev dur"
      else if (q.length >= 3 && p.full.includes(q)) score = 2;              // loose fallback
      if (score >= 0) scored.push({ p, score });
    }
    scored.sort((x, y) => x.score - y.score || x.p.rank - y.p.rank);
    suggestionItems = scored.slice(0, 8).map((x) => x.p.name);
    highlighted = suggestionItems.length ? 0 : -1;
    drawSuggestions();
  }

  // Bold the typed prefix of each word, e.g. "kev dur" → **Kev**in **Dur**ant.
  function highlightName(name, tokens) {
    return name.split(/([\s.\-']+)/).map((part) => {
      const n = normalize(part);
      const t = n && tokens.filter((tok) => n.startsWith(tok)).sort((a, b) => b.length - a.length)[0];
      if (!t) return escapeHtml(part);
      // Map normalized length back onto the original characters (handles accents).
      let cut = 0;
      while (cut < part.length && normalize(part.slice(0, cut)).length < t.length) cut++;
      return `<mark class="bg-transparent text-amber-300 font-semibold">${escapeHtml(part.slice(0, cut))}</mark>${escapeHtml(part.slice(cut))}`;
    }).join('');
  }

  function drawSuggestions() {
    if (!suggestionItems.length) { hideSuggestions(); return; }
    const tokens = el.guessInput.value.split(/[\s.\-']+/).map(normalize).filter(Boolean);
    el.suggestions.innerHTML = suggestionItems.map((name, k) => `
      <li role="option" data-k="${k}" aria-selected="${k === highlighted}"
        class="flex items-center gap-3 px-4 py-2.5 cursor-pointer text-sm border-l-2 ${
          k === highlighted ? 'bg-white/10 border-amber-400 text-white' : 'border-transparent text-slate-300 hover:bg-white/5'}">
        <span class="shrink-0 text-base opacity-70">${sportMeta(activeSport).ball}</span>
        <span class="truncate">${highlightName(name, tokens)}</span>
      </li>`).join('');
    el.suggestions.classList.remove('hidden');
    el.guessInput.setAttribute('aria-expanded', 'true');
    const hl = el.suggestions.querySelector(`[data-k="${highlighted}"]`);
    if (hl) hl.scrollIntoView({ block: 'nearest' });
  }

  function hideSuggestions() {
    suggestionItems = [];
    highlighted = -1;
    el.suggestions.classList.add('hidden');
    el.suggestions.innerHTML = '';
    el.guessInput.setAttribute('aria-expanded', 'false');
  }

  // ---------- Modal / share ----------
  function shareText() {
    const solved = totalSolved();
    const win = solved >= WIN_THRESHOLD;
    const lines = [
      `StatLines ${dateKey}`,
      `🏆 DAILY RESULT: ${win ? 'WIN 🎉' : 'LOSS 💔'}`,
      `📊 TOTAL SCORE: ${solved}/${TOTAL_STAGES} Solved`,
      '',
    ];
    SPORT_ORDER.forEach((sport) => {
      const meta = sportMeta(sport);
      const row = progress[sport].stages
        .map((s) => (s.status === 'solved' ? meta.ball : s.status === 'failed' ? '🔴' : '⬜'))
        .join(' ');
      lines.push(`${meta.ball} ${meta.name}: ${row} (${sportSolved(sport)}/${STAGES_PER_SPORT})`);
    });
    return lines.join('\n');
  }

  function openModal() {
    const solved = totalSolved();
    const win = solved >= WIN_THRESHOLD;
    el.modalDate.textContent = `StatLines · ${dateKey}`;
    el.modalTitle.textContent = win ? 'DAILY WIN 🎉' : 'DAILY LOSS 💔';
    el.modalTitle.className = `font-display text-5xl tracking-wider mt-1 ${win ? 'text-emerald-300' : 'text-red-300'}`;
    el.modalSub.textContent = win
      ? `You cleared the ${WIN_THRESHOLD}-stage win line. Elite film study.`
      : `${WIN_THRESHOLD - solved} more solve${WIN_THRESHOLD - solved === 1 ? '' : 's'} needed for the win. Back tomorrow?`;
    el.modalScore.textContent = solved;
    el.modalScore.className = `font-display text-7xl leading-none ${win ? 'text-emerald-300' : 'text-red-300'}`;

    el.modalMatrix.innerHTML = SPORT_ORDER.map((sport) => {
      const meta = sportMeta(sport);
      const cells = progress[sport].stages.map((s, i) => {
        const p = day[sport][i];
        const icon = s.status === 'solved' ? meta.ball : s.status === 'failed' ? '🔴' : '⬜';
        return `<span title="${escapeHtml((s.unlocked && s.unlocked.answer) || '')}" class="w-9 h-9 inline-flex items-center justify-center rounded-lg ${
          s.status === 'solved' ? accent(sport).soft : s.status === 'failed' ? 'bg-red-500/10' : 'bg-white/5'
        } text-lg">${icon}</span>`;
      }).join('');
      return `<div class="flex items-center justify-between gap-3 rounded-xl bg-white/[0.03] border border-white/10 px-3 py-2">
        <span class="font-semibold text-sm w-16">${meta.ball} ${escapeHtml(meta.name)}</span>
        <span class="flex gap-1">${cells}</span>
        <span class="font-mono text-sm text-slate-300 w-10 text-right">${sportSolved(sport)}/5</span>
      </div>`;
    }).join('');

    el.modalShare.textContent = shareText();
    el.copyMsg.textContent = '';
    el.modal.classList.remove('hidden');
  }

  const closeModal = () => el.modal.classList.add('hidden');

  async function copyResults() {
    const text = shareText();
    let ok = false;
    try {
      await navigator.clipboard.writeText(text);
      ok = true;
    } catch (_) {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      try { ok = document.execCommand('copy'); } catch (_) { ok = false; }
      ta.remove();
    }
    el.copyMsg.className = `text-xs mt-2 h-4 ${ok ? 'text-emerald-400' : 'text-red-400'}`;
    el.copyMsg.textContent = ok ? '✓ Copied to clipboard!' : 'Copy failed — select the text above manually.';
  }

  // ---------- Events ----------
  function bindEvents() {
    el.guessForm.addEventListener('submit', (e) => {
      e.preventDefault();
      const pick = highlighted >= 0 && suggestionItems[highlighted] && !el.suggestions.classList.contains('hidden')
        ? suggestionItems[highlighted]
        : el.guessInput.value;
      submitGuess(pick);
    });

    el.guessInput.addEventListener('input', updateSuggestions);
    el.guessInput.addEventListener('focus', updateSuggestions);
    el.guessInput.addEventListener('keydown', (e) => {
      if (el.suggestions.classList.contains('hidden')) return;
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        highlighted = (highlighted + 1) % suggestionItems.length;
        drawSuggestions();
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        highlighted = (highlighted - 1 + suggestionItems.length) % suggestionItems.length;
        drawSuggestions();
      } else if (e.key === 'Tab' && highlighted >= 0) {
        e.preventDefault();
        el.guessInput.value = suggestionItems[highlighted];
        hideSuggestions();
      } else if (e.key === 'Escape') {
        hideSuggestions();
      }
    });
    el.suggestions.addEventListener('mousedown', (e) => {
      const li = e.target.closest('li[data-k]');
      if (!li) return;
      e.preventDefault(); // keep focus on input
      submitGuess(suggestionItems[Number(li.dataset.k)]);
    });
    el.guessInput.addEventListener('blur', () => setTimeout(hideSuggestions, 120));

    el.nextBtn.addEventListener('click', handleNext);
    el.resultsBtn.addEventListener('click', openModal);
    el.modalClose.addEventListener('click', closeModal);
    el.modalBackdrop.addEventListener('click', closeModal);
    el.copyBtn.addEventListener('click', copyResults);
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeModal(); });

    // Two-tap confirm: confirm() dialogs are blocked in some embedded viewers.
    let resetArmed = null;
    const resetLabel = el.resetBtn.textContent;
    el.resetBtn.addEventListener('click', () => {
      if (!resetArmed) {
        el.resetBtn.textContent = "Tap again to erase today's progress";
        resetArmed = setTimeout(() => { resetArmed = null; el.resetBtn.textContent = resetLabel; }, 4000);
        return;
      }
      clearTimeout(resetArmed); resetArmed = null; el.resetBtn.textContent = resetLabel;
      SPORT_ORDER.forEach((s) => {
        store.remove(storageKey(s));
        progress[s] = freshProgress();
        viewIndex[s] = 0;
      });
      store.remove(modalSeenKey());
      closeModal();
      switchSport('nba');
    });
  }

  function renderYesterday(prev) {
    const box = $('yesterday');
    if (!box || !prev) return;
    $('yesterdayDate').textContent = prev.date;
    $('yesterdayList').innerHTML = SPORT_ORDER.filter((s) => prev[s]).map((s) => {
      const meta = SPORTS_META[s];
      return `<div><div class="font-semibold text-slate-300 mb-1">${meta.ball} ${escapeHtml(meta.name)}</div><ol class="space-y-1">${
        prev[s].map((a, i) => `<li class="flex gap-2"><span class="font-mono text-slate-500 w-4">${i + 1}</span><span><strong class="text-slate-100">${escapeHtml(a.answer)}</strong><span class="text-slate-500"> · ${escapeHtml(a.reveal)}</span></span></li>`).join('')
      }</ol></div>`;
    }).join('');
    box.classList.remove('hidden');
  }

  // ---------- Boot ----------
  async function init() {
    try {
      const index = await fetchJson('puzzles/index.json');
      if (!index.dates || !index.dates.length) throw new Error('no puzzle days published yet');
      dateKey = pickDay(index.dates);
      const [dayFile, players] = await Promise.all([
        fetchJson(`puzzles/${dateKey}.json`),
        fetchJson('players.json'),
      ]);
      data = { sports: SPORTS_META, players };
      day = {};
      for (const s of SPORT_ORDER) {
        day[s] = (dayFile[s] || []).map((stage) => ({ ...stage, hints: decodeSecret(stage.hints) }));
      }
      renderYesterday(dayFile.previous);
    } catch (err) {
      el.loading.classList.add('hidden');
      el.error.classList.remove('hidden');
      el.error.innerHTML = `<strong>Couldn't load today's puzzles</strong> (${escapeHtml(err.message)}).<br>
        Browsers block <code>fetch()</code> on <code>file://</code> pages — serve this folder locally, e.g.
        <code class="block mt-2 bg-black/40 rounded px-2 py-1">python3 -m http.server 8000</code>
        then open <code>http://localhost:8000</code>.`;
      return;
    }

    for (const s of SPORT_ORDER) {
      if (!day[s] || day[s].length !== STAGES_PER_SPORT) {
        el.loading.textContent = `Puzzle data for ${s.toUpperCase()} on ${dateKey} is incomplete.`;
        return;
      }
      progress[s] = loadProgress(s);
      viewIndex[s] = progress[s].stageIndex;
    }

    el.dateLabel.textContent = dateKey;
    const savedSport = store.get(activeSportKey());
    activeSport = SPORT_ORDER.includes(savedSport) ? savedSport : 'nba';

    el.loading.classList.add('hidden');
    el.game.classList.remove('hidden');
    bindEvents();
    switchSport(activeSport);
  }

  init();
})();
