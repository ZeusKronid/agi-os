// AGIOS Live workspace: one sunrise scene. Talk → find room for the preview → the sun rises while it builds →
// the preview VM rises from the horizon → decide → the sun rises again while it installs → good morning.
const $ = id => document.getElementById(id);
const gib = bytes => (bytes / 2**30).toFixed(1) + ' GiB';
// Like the site, the workspace always plays its motion: the system reduced-motion setting is not honored.
let current, busy = false, client, keyboard, mouse, connected = false, consoleId = null, lastConnect = 0;
let lastMessages = '', lastPlan = '', lastFacts = '', sheet = '', revertAsk = false, orphanAsk = '', replanning = false;
let providerKind = 'chatgpt', labels = [], shown = 0;

async function api(path, data) {
    const response = await fetch('/api/' + path, data === undefined ? {} : {
        method: 'POST', headers: {'Content-Type': 'application/json', 'X-AGIOS': 'local'}, body: JSON.stringify(data)
    });
    const text = await response.text();
    let result; try { result = JSON.parse(text); } catch { result = {error: text}; }
    if (!response.ok) throw new Error(result.error || 'The request did not go through');
    return result;
}
let toastTimer;
function showError(error) {
    $('toast').textContent = error.message || error; $('toast').hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { $('toast').hidden = true; }, 7000);
}

/* ── where we are ─────────────────────────────────────── */
const CHAPTERS = ['Talk', 'Place', 'Preview', 'Install'];
function scene(s) {
    if (s.final.phase === 'complete') return 'done';
    if (s.final.phase === 'working' || s.final.phase === 'error') return 'install';
    if (['starting', 'installing'].includes(s.phase)) return 'build';
    if (s.running || s.built || ['stopped', 'error'].includes(s.phase)) return 'preview';
    return 'talk';
}
function chapter(s) {
    const place = scene(s);
    if (place === 'done' || place === 'install' || sheet === 'final') return 3;
    if (place === 'build' || place === 'preview') return 2;
    return s.configuration ? 1 : 0;
}
// The engine reports texts, not percentages; these are the shares of the sunrise the texts start at.
function buildShare(s) {
    if (s.built) return 1;
    let share = {starting: .02, installing: .08}[s.phase] || 0;
    const marks = [[/^Starting the installer VM/, .05], [/^Waiting for the installer/, .08], [/^Checking repositories/, .12],
                   [/^Creating the agreed partitions/, .18], [/^Encrypting the root/, .22], [/^Installing the base system/, .26],
                   [/^Setting up boot/, .84], [/^Written and set up/, .92], [/^Booting the installed system/, .96]];
    for (const text of [...s.events.map(e => e.text || ''), s.status]) {
        for (const [pattern, value] of marks) if (pattern.test(text)) share = Math.max(share, value);
        const packages = /^Installing your packages \((\d+) of (\d+)\)/.exec(text);
        if (packages) share = Math.max(share, .3 + .5 * packages[1] / Math.max(1, packages[2]));
    }
    return share;
}
function installShare(s) {
    if (s.final.phase === 'complete') return 1;
    let share = .02;
    const marks = [[/^Opening the preview/, .05], [/^Creating partitions/, .15], [/^Encrypting the root/, .22], [/^Promoting/, .3],
                   [/^Copying the checked system/, .35], [/^Verifying the copy/, .65], [/^Updating partition IDs/, .75],
                   [/^Rebuilding initramfs/, .85], [/^Registering the boot/, .93], [/^The system on/, 1]];
    for (const event of s.final.events) for (const [pattern, value] of marks) if (pattern.test(event.text || '')) share = Math.max(share, value);
    return share;
}
const BUILD_STEPS = [['Storage', 0], ['VM', .05], ['Base', .12], ['Packages', .3], ['Boot', .84]];
const INSTALL_STEPS = [['Check', 0], ['Partitions', .15], ['Copy', .35], ['Verify', .65], ['Boot', .85]];

/* ── the sun: the site's «Восход», drawn on a canvas behind everything ───────── */
function mulberry(seed) { let a = seed >>> 0; return () => { a = (a + 0x6d2b79f5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
const random = mulberry(11);
const RAYS = Array.from({length: 98}, (_, i) => ({f: i / 97, major: i % 4 === 0, len: i % 4 === 0 ? .62 : .16 + random() * .28,
                                                  voice: .4 + random() * .9, speed: 1 / (.26 + random() * .06), phase: random() * 6.283}));
const sun = {now: {hy: .42, rs: .17, arc: 0, grow: 0, energy: .3, lift: 1, dim: 1}, goal: {hy: .42, rs: .17, arc: 1, grow: .8, energy: .3, lift: 1, dim: 1},
             dots: [], alpha: {}, at: {}, share: 0};
function drawSun(time) {
    const canvas = $('sky'), w = innerWidth, h = innerHeight, dpr = Math.min(2, devicePixelRatio || 1);
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); }
    const k = .045;
    for (const key in sun.goal) sun.now[key] += (sun.goal[key] - sun.now[key]) * k;
    const s = sun.now, ctx = canvas.getContext('2d'); ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, h);
    const hy = s.hy * h, r = Math.min(s.rs * h, w * .36), cx = w / 2, cy = hy + (1 - s.lift) * r * 1.25, t = time;
    ctx.save(); ctx.globalAlpha = s.dim;
    const glow = ctx.createRadialGradient(cx, hy, 0, cx, hy, r * 2.4); glow.addColorStop(0, `rgba(255,106,61,${.1 + .1 * s.energy})`); glow.addColorStop(1, 'rgba(255,106,61,0)');
    ctx.fillStyle = glow; ctx.fillRect(0, 0, w, hy);
    ctx.beginPath(); ctx.rect(0, 0, w, hy); ctx.clip(); ctx.lineCap = 'round'; ctx.strokeStyle = '#ff6a3d'; ctx.lineWidth = 1.5;
    const inner = r + Math.max(4, r * .07);
    for (const ray of RAYS) {
        const grow = s.grow * Math.max(0, Math.min(1, (s.arc - ray.f) * 5 + (s.arc > .999 ? 1 : 0))); if (grow <= .001) continue;
        const wave = .65 + .35 * Math.sin(t * ray.speed * Math.PI + ray.phase), length = r * ray.len * grow * (1 + s.energy * ray.voice * .7 * wave), a = Math.PI + ray.f * Math.PI;
        ctx.globalAlpha = s.dim * (ray.major ? 1 : .8); ctx.beginPath(); ctx.moveTo(cx + Math.cos(a) * inner, cy + Math.sin(a) * inner); ctx.lineTo(cx + Math.cos(a) * (inner + length), cy + Math.sin(a) * (inner + length)); ctx.stroke();
    }
    ctx.globalAlpha = 1; ctx.globalCompositeOperation = 'destination-in';
    const fade = ctx.createRadialGradient(cx, cy, r, cx, cy, r * 2.05); fade.addColorStop(0, '#000'); fade.addColorStop(.45, 'rgba(0,0,0,.6)'); fade.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = fade; ctx.fillRect(0, 0, w, h); ctx.globalCompositeOperation = 'source-over'; ctx.globalAlpha = s.dim;
    ctx.beginPath(); ctx.arc(cx, cy, r, Math.PI, Math.PI + Math.max(.0001, s.arc) * Math.PI); ctx.stroke();
    if (s.arc > .98) {
        ctx.globalAlpha = Math.min(1, (s.arc - .98) * 50) * s.dim; ctx.beginPath(); ctx.moveTo(cx, cy - r - 6); ctx.lineTo(cx, cy - r * 1.9); ctx.stroke();
        ctx.fillStyle = '#ff6a3d'; ctx.beginPath(); ctx.arc(cx, cy - r * 1.9 - 5, 2.4, 0, 6.283); ctx.fill();
    }
    const pulse = (Math.sin(time * 4) + 1) / 2;
    for (const [f, state] of sun.dots) {
        const a = Math.PI + f * Math.PI, x = cx + Math.cos(a) * r, y = cy + Math.sin(a) * r, size = state === 'done' ? 2.6 : state === 'current' ? 2.8 + .9 * pulse : 1.8;
        ctx.fillStyle = '#ff6a3d';
        if (state === 'current') { ctx.globalAlpha = .18 * s.dim; ctx.beginPath(); ctx.arc(x, y, size + 5, 0, 6.283); ctx.fill(); }
        ctx.globalAlpha = (state === 'next' ? .5 : 1) * s.dim; ctx.beginPath(); ctx.arc(x, y, size, 0, 6.283); ctx.fill();
    }
    ctx.globalAlpha = 1; ctx.font = `500 ${Math.max(10, Math.min(12, r * .07))}px "Geist Mono", monospace`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    for (const word of Object.keys(sun.alpha)) {
        const index = labels.indexOf(word), goal = index < 0 ? 0 : 1, value = sun.alpha[word] += (goal - sun.alpha[word]) * .06;
        if (value < .01) { if (index < 0) delete sun.alpha[word]; continue; }
        const f = sun.at[word], a = Math.PI + f * Math.PI, distance = r * 1.62 + (1 - value) * 14;
        ctx.fillStyle = `rgba(217,210,199,${value * s.dim})`; ctx.fillText(word.toUpperCase(), cx + Math.cos(a) * distance, cy + Math.sin(a) * distance);
    }
    ctx.restore();
    const line = ctx.createLinearGradient(0, 0, w, 0); line.addColorStop(0, 'rgba(255,255,255,0)'); line.addColorStop(.5, 'rgba(255,255,255,.14)'); line.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.fillStyle = line; ctx.fillRect(0, hy, w, 1);
    // The percentage counts up with the arc instead of jumping between engine messages.
    shown += (sun.share - shown) * .08;
    if (!$('rise').hidden) $('pct').textContent = Math.round(shown * 100);
}
function frame(time) { if (!document.hidden) drawSun(time / 1000); requestAnimationFrame(frame); }
requestAnimationFrame(frame);
function setLabels(words) {
    labels = words.slice(0, 5);
    labels.forEach((word, index) => { if (!(word in sun.alpha)) sun.alpha[word] = 0; sun.at[word] = .12 + index * .19; });
}
function agreedWords(config) {
    const quiet = /^(greetd|pipewire|wireplumber|noto-|ttf-|xdg-|mesa|networkmanager|lib|base|linux|polkit|sudo)/;
    const words = config.session ? [config.session] : [];
    for (const name of config.packages) if (!quiet.test(name) && !words.includes(name)) words.push(name);
    return words;
}

/* ── render ───────────────────────────────────────────── */
function render(state) {
    current = state;
    const place = scene(state), step = chapter(state), config = state.configuration;
    document.querySelectorAll('#pips i').forEach((pip, i) => pip.classList.toggle('on', i <= step));
    $('chapter').textContent = CHAPTERS[step];
    sun.dots = [.14, .38, .62, .86].map((f, i) => [f, i < step ? 'done' : i === step ? 'current' : 'next']);
    $('model').textContent = state.model || 'no model';
    $('modelDot').className = 'dot ' + (state.model ? 'ok' : 'off');
    $('status').textContent = state.status;

    // What has touched the disks so far, always visible.
    const erased = state.built && state.built.revert === 'not reversible';
    const [write, safety] = state.final.phase === 'complete' ? [true, 'Installed on ' + state.final.target]
        : state.final.phase === 'working' ? [true, 'Writing to ' + state.final.target]
        : erased ? [true, 'Disk erased for the preview']
        : state.built || ['starting', 'installing'].includes(state.phase) ? [false, 'Preview' + (state.built && state.built.storage ? ': ' + state.built.storage : '') + ' · undo ready']
        : [false, 'Nothing written to disk'];
    $('safety').classList.toggle('write', write);
    $('safety').querySelector('.dot').className = 'dot ' + (write ? '' : 'ok');
    $('safety').querySelector('span').textContent = safety;

    // Conversation.
    const serialized = JSON.stringify(state.messages);
    if (serialized !== lastMessages) {
        const fresh = JSON.parse(lastMessages || '[]').length;
        lastMessages = serialized;
        for (const box of [$('messages'), $('history')]) {
            box.replaceChildren();
            state.messages.forEach((message, index) => {
                const line = document.createElement('div'); line.className = 'line ' + (message.role === 'user' ? 'user' : 'assistant') + (index >= fresh && box === $('messages') ? ' fresh' : '');
                const who = document.createElement('span'); who.className = 'who'; who.textContent = message.role === 'user' ? 'You' : 'AGIOS';
                const text = document.createElement('span'); text.className = 'text'; text.textContent = message.content;
                line.append(who, text); box.append(line);
            });
        }
        $('suggestions').replaceChildren();
        const last = state.messages.at(-1);
        for (const suggestion of (last && last.suggestions) || []) {
            if (typeof suggestion !== 'string') continue;
            const chip = document.createElement('button'); chip.className = 'chip'; chip.textContent = suggestion;
            chip.onclick = () => send(suggestion); $('suggestions').append(chip);
        }
        for (const box of [$('lines'), $('history')]) box.scrollTop = box.scrollHeight;
    }
    $('talk').classList.toggle('chatting', state.messages.length > 0 || busy);
    $('welcome').hidden = state.messages.length > 0 || busy;
    $('thinking').hidden = !busy;
    if (busy) $('thinkingText').textContent = state.status;
    $('error').hidden = !state.error || place !== 'talk';
    if (state.error) $('error').textContent = state.error;
    const lookup = /^Looking up packages: (.+)/.exec(state.status);
    if (place !== 'talk') setLabels([]);
    else if (config) setLabels(agreedWords(config)); else if (lookup) setLabels(lookup[1].split(',').map(term => term.trim())); else if (!busy) setLabels([]);

    const consentError = state.consent && state.consent.error;
    $('consentError').hidden = !consentError;
    if (consentError) $('consentError').textContent = 'The target disk is unavailable: ' + consentError;
    $('placeButton').hidden = !config || place !== 'talk' || busy;
    $('placeButton').disabled = !!consentError || (!state.plan && !state.can_plan);
    $('placeText').textContent = state.plan ? 'All set — pick where the preview lives' : 'All set — find room for the preview';
    $('connectButton').hidden = !!state.model;
    $('chatForm').hidden = !state.model;
    $('send').disabled = busy;
    $('suggestions').hidden = busy || !!config;

    // Scenes.
    $('talk').hidden = place !== 'talk';
    const rising = place === 'build' || place === 'install';
    $('rise').hidden = $('below').hidden = !rising;
    $('vm').hidden = $('vmbar').hidden = place !== 'preview';
    $('done').hidden = place !== 'done';
    if (rising) {
        const installing = place === 'install', share = installing ? installShare(state) : buildShare(state);
        sun.share = share;
        $('riseLabel').textContent = installing ? (state.final.phase === 'error' ? 'Installing stopped' : 'Installing on the computer') : 'Building the preview';
        const failed = state.final.phase === 'error';
        $('riseText').textContent = failed ? state.final.error : installing ? (state.final.events.at(-1) || {}).text || 'Starting…' : state.status;
        $('riseText').classList.toggle('error', failed);
        const steps = installing ? INSTALL_STEPS : BUILD_STEPS;
        $('substeps').replaceChildren(...steps.map(([name, at], i) => {
            const next = steps[i + 1] ? steps[i + 1][1] : 1.01, span = document.createElement('span');
            span.textContent = name; span.className = share >= next ? 'done' : share >= at && !failed ? 'current' : ''; return span;
        }));
        $('stopBuild').hidden = installing;
        $('retryFinal').hidden = !failed || !state.can_finalize;
    }
    if (place === 'preview') {
        const stateText = state.phase === 'error' ? ['The build stopped', state.error || 'Look at the log, then put everything back and try again.']
            : !state.running ? ['VM stopped · preview kept', 'Start it again to keep checking, or decide now.']
            : !connected ? ['Connecting the screen…', ''] : null;
        $('vmState').hidden = !stateText;
        if (stateText) { $('vmStateLabel').textContent = stateText[0]; $('vmStateText').textContent = stateText[1]; $('vmStateText').hidden = !stateText[1]; }
        $('resumeInline').hidden = !state.can_resume;
        $('reconnect').hidden = !state.running || connected;
        $('revertInline').hidden = state.phase !== 'error' || !state.can_revert;
        $('decide').disabled = state.phase === 'error' || !state.built;
    }
    $('screenStatus').hidden = place !== 'preview';
    $('screenStatus').textContent = state.running ? (connected ? 'Screen connected · click it to control' : 'Connecting the screen…') : 'Local VM · Apache Guacamole';
    $('fullscreen').hidden = $('stop').hidden = !state.running;

    // Place sheet.
    if (state.plan) {
        $('estimate').textContent = `The system takes ${gib(state.plan.estimate.installed)} (${state.plan.estimate.packages} packages, ${gib(state.plan.estimate.download)} to download). `
            + `The preview needs ${gib(state.plan.needed)} with headroom. Target disk: ${config ? config.disk : ''}.` + (state.plan.encrypt ? ' The root will be encrypted.' : '');
        $('passphraseField').hidden = !state.plan.encrypt;
        if (lastPlan !== state.plan.digest) {
            lastPlan = state.plan.digest; renderOptions(state.plan);
            $('memory').value = String(state.plan.memory); $('encrypt').checked = state.plan.encrypt;
        }
    }
    if (config && JSON.stringify(config) !== lastFacts) { lastFacts = JSON.stringify(config); renderFacts(config); }
    $('replanning').hidden = !replanning;
    validateBuild();

    // Decide sheet.
    if (state.built) {
        $('finalTarget').textContent = 'Target disk: ' + state.built.target + (state.built.encrypted ? ' · root encrypted' : '');
        $('finalPassphraseField').hidden = !state.built.encrypted;
        $('targetConfirm').placeholder = state.built.target;
        $('finalHint').textContent = state.built.on_target
            ? 'The preview already lives on this disk: its partitions become the system without copying.'
            : 'The checked system is copied file by file to new partitions and verified by checksums.';
        $('revertHint').textContent = 'You tried the system. Installing makes it this computer’s system. Putting it back removes the preview — '
            + (state.built.revert || 'nothing else changes') + '.';
    }
    $('finalBlocked').hidden = !(state.built && state.running);
    $('finalInstallForm').querySelectorAll('input, button').forEach(el => { el.disabled = !state.can_finalize; });
    $('revert').hidden = !state.can_revert;
    $('revert').textContent = revertAsk ? 'Confirm: put everything back' : 'Not right — put everything back';
    $('revert').className = 'btn ' + (revertAsk ? 'danger' : 'outline');
    $('keep').hidden = !revertAsk;
    $('finalError').hidden = !state.final.error || place === 'install';
    if (state.final.error) $('finalError').textContent = state.final.error;
    updateLayoutWarning(); validateFinal();
    if (sheet === 'place' && (place !== 'talk' || !state.plan)) openSheet('');
    if (sheet === 'final' && !state.built) openSheet('');

    // Log: the build or the final installation.
    const events = place === 'install' || place === 'done' ? state.final.events : state.events;
    $('events').textContent = events.map(event => event.text || event.kind).join('\n') || 'Nothing yet.';

    // Guacamole: connect while the VM runs, drop the client when it stops.
    if (state.running && (!client || consoleId !== state.console_id || (!connected && Date.now() - lastConnect > 6000))) { consoleId = state.console_id; connect(); }
    if (!state.running && client) disconnect();

    renderOrphans(place === 'talk' ? state.orphans || [] : []);
    aimSun(state, place);
}
function aimSun(state, place) {
    const thinking = busy && place === 'talk';
    if (place === 'done') Object.assign(sun.goal, {hy: .5, rs: .2, arc: 1, grow: 1.1, energy: .6, lift: 1, dim: 1});
    else if (place === 'build' || place === 'install') {
        const p = sun.share, failed = state.final.phase === 'error';
        Object.assign(sun.goal, {hy: .7, rs: .24, arc: Math.max(.02, p), grow: .5 + .6 * p, energy: failed ? .1 : .9, lift: .35 + .65 * p, dim: failed ? .45 : 1});
    }
    else if (place === 'preview') Object.assign(sun.goal, {hy: 1.02, rs: .5, arc: 1, grow: 1.2, energy: state.running ? .5 : .1, lift: 1, dim: state.phase === 'error' ? .35 : .7});
    else if (state.messages.length || busy) Object.assign(sun.goal, {hy: 1, rs: .17, arc: 1, grow: state.configuration ? 1 : .8, energy: thinking ? 1.1 : .35, lift: 1, dim: sheet ? .5 : 1});
    else Object.assign(sun.goal, {hy: .42, rs: .17, arc: 1, grow: state.model ? 1 : .8, energy: .35, lift: 1, dim: 1});
    if (place === 'build' && sun.now.arc > sun.goal.arc + .05) Object.assign(sun.now, {arc: 0, grow: 0, lift: .35});
}

function renderOptions(plan) {
    const box = $('options'); box.replaceChildren();
    for (const option of plan.options) {
        const card = document.createElement('div');
        card.className = 'option' + (option.fits ? '' : ' unfit') + (option.destructive ? ' destructive' : '');
        card.setAttribute('role', 'radio'); card.dataset.id = option.id; card.tabIndex = option.fits ? 0 : -1;
        card.setAttribute('aria-disabled', String(!option.fits));
        const radio = document.createElement('span'); radio.className = 'radio';
        const body = document.createElement('div'), title = document.createElement('b'), detail = document.createElement('span'), undo = document.createElement('small');
        title.textContent = option.title;
        const tags = [option.recommended && 'recommended', !option.fits && 'not enough room', option.destructive && (option.kind === 'erase' ? 'irreversible' : 'changes a partition')].filter(Boolean);
        for (const tag of tags) { const i = document.createElement('i'); i.textContent = tag; title.append(' ', i); }
        detail.textContent = option.detail; undo.textContent = 'Undo: ' + option.revert;
        body.append(title, detail, undo); card.append(radio, body); box.append(card);
        card.onclick = () => pickOption(option.id);
        card.onkeydown = event => { if (event.key === ' ' || event.key === 'Enter') { event.preventDefault(); pickOption(option.id); } };
    }
    const preferred = plan.options.find(o => o.recommended && o.fits) || plan.options.find(o => o.fits);
    pickOption(preferred ? preferred.id : null);
}
let chosen = null;
function selectedOption() { return current && current.plan ? current.plan.options.find(o => o.id === chosen) : null; }
function pickOption(id) {
    const option = current && current.plan && current.plan.options.find(o => o.id === id);
    if (id && (!option || !option.fits)) return;
    chosen = id; $('optionAccepted').checked = false; $('optionPath').value = '';
    document.querySelectorAll('.option').forEach(card => { const on = card.dataset.id === id; card.classList.toggle('selected', on); card.setAttribute('aria-checked', String(on)); });
    const destructive = option && option.destructive;
    $('optionConfirm').hidden = !destructive;
    if (destructive) {
        $('optionWarning').textContent = option.kind === 'erase' ? 'All data on ' + option.confirm + ' is deleted before the preview. This can’t be undone.'
            : 'Partition ' + option.confirm + ' will shrink. Data stays, but back it up first.';
        $('optionPathLabel').textContent = 'Type ' + option.confirm + ' to confirm'; $('optionPath').placeholder = option.confirm;
    }
    $('optionAcceptText').textContent = !option ? 'Pick a place first' : destructive ? 'I understand the consequences' : 'I understand what happens. Undo: ' + option.revert;
    validateBuild();
}
function renderFacts(config) {
    const facts = [['Disk', config.disk], ['Desktop', config.desktop], ['Session', config.session || 'console'],
                   ['Computer', config.hostname + ' · user ' + config.username], ['Language', config.locale + ' · ' + config.keyboard_layouts.join(', ') + ' · ' + config.timezone],
                   ['Filesystem', config.filesystem + ' · ' + config.bootloader], ['Packages', config.packages.join(', ') || 'base system only'],
                   ['Services', config.services.join(', ') || 'base services only'], ['Requirements', config.requirements.join(' · ')]];
    $('facts').replaceChildren(...facts.flatMap(([key, value]) => { const dt = document.createElement('dt'), dd = document.createElement('dd'); dt.textContent = key; dd.textContent = value; return [dt, dd]; }));
}
function needsHTML(box, needs) {
    box.replaceChildren(...needs.map(([ok, text]) => { const span = document.createElement('span'); span.className = ok ? 'ok' : ''; span.textContent = text; return span; }));
    return needs.every(([ok]) => ok);
}
function validateBuild() {
    const option = selectedOption(), encrypt = current && current.plan && current.plan.encrypt;
    const needs = [[!!option, 'Pick a place'], [$('optionAccepted').checked, option && option.destructive ? 'Accept the consequences' : 'Accept the plan']];
    if (option && option.destructive) needs.push([$('optionPath').value.trim() === option.confirm, 'Type ' + option.confirm]);
    needs.push([$('password').value.length >= 8, 'Password of 8+ characters']);
    if (encrypt) needs.push([$('passphrase').value.length >= 8, 'Encryption password']);
    const consent = current && current.consent && current.consent.error;
    $('build').disabled = !needsHTML($('buildNeeds'), needs) || !!consent || replanning;
}
function validateFinal() {
    if (!current || !current.built) return;
    const needs = [[$('finalAccepted').checked, 'I checked the preview'], [$('targetConfirm').value.trim() === current.built.target, 'Type ' + current.built.target]];
    if (current.built.encrypted) needs.push([$('finalPassphrase').value.length >= 8, 'Encryption password']);
    $('installFinal').disabled = !needsHTML($('finalNeeds'), needs) || !current.can_finalize;
}
function updateLayoutWarning() {
    if (!current || !current.built) return;
    const erase = document.querySelector('input[name=layout]:checked').value === 'erase';
    $('layoutWarning').textContent = erase ? 'Every other partition and all data on ' + current.built.target + ' will be deleted.'
        : 'Existing partitions on ' + current.built.target + ' stay; the system takes the free space.';
    $('layoutWarning').className = erase ? 'line error' : 'hint';
}
function renderOrphans(orphans) {
    $('orphans').hidden = !orphans.length;
    const key = JSON.stringify([orphans, orphanAsk]);
    if ($('orphanList').dataset.key === key) return;
    $('orphanList').dataset.key = key; $('orphanList').replaceChildren();
    for (const orphan of orphans) {
        const text = document.createElement('span'); text.textContent = `${orphan.device} · ${gib(orphan.size)} on ${orphan.disk}`;
        const button = document.createElement('button'); const asking = orphanAsk === orphan.device;
        button.className = 'btn ' + (asking ? 'danger' : 'outline'); button.textContent = asking ? 'Confirm: remove ' + orphan.device : 'Remove this preview partition';
        button.onclick = async () => {
            if (orphanAsk !== orphan.device) { orphanAsk = orphan.device; render(current); return; }
            orphanAsk = ''; try { render(await api('orphans/remove', {device: orphan.device})); } catch (error) { showError(error); }
        };
        $('orphanList').append(text, button);
    }
}

/* ── sheets and drawer ────────────────────────────────── */
function openSheet(name) {
    sheet = name; revertAsk = false;
    for (const [id, key] of [['placeSheet', 'place'], ['finalSheet', 'final']]) {
        const on = sheet === key; $(id).classList.toggle('on', on); $(id).inert = !on;
    }
    $('veil').classList.toggle('on', !!sheet || $('drawer').classList.contains('on'));
    if (sheet === 'place') setTimeout(() => (document.querySelector('.option.selected') || $('password')).focus({preventScroll: true}), 60);
    if (sheet === 'final') setTimeout(() => $('finalAccepted').focus({preventScroll: true}), 60);
    if (current) render(current);
}
function toggleDrawer(on) {
    $('drawer').classList.toggle('on', on); $('drawer').inert = !on;
    $('veil').classList.toggle('on', on || !!sheet);
    if (on) $('history').scrollTop = $('history').scrollHeight;
}
function closeAll() { toggleDrawer(false); if (sheet) openSheet(''); }
$('veil').onclick = closeAll;
document.querySelectorAll('[data-close]').forEach(button => button.onclick = closeAll);
$('drawerButton').onclick = () => toggleDrawer(!$('drawer').classList.contains('on'));
document.querySelectorAll('[data-log]').forEach(button => button.onclick = () => { $('logPanel').hidden = !$('logPanel').hidden; });
document.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || event.target === $('screen') || $('settings').open) return;
    if (!$('logPanel').hidden) $('logPanel').hidden = true; else closeAll();
});

/* ── actions ──────────────────────────────────────────── */
async function refresh() { try { render(await api('state')); } catch (error) { showError(error); } }
async function send(text) {
    text = text.trim(); if (!text || busy) return;
    busy = true; $('prompt').value = ''; $('changePrompt').value = '';
    current.messages = [...current.messages, {role: 'user', content: text}]; render(current);
    try { render(await api('chat', {text})); } catch (error) { showError(error); $('prompt').value = text; }
    finally { busy = false; if (current) render(current); }
}
$('chatForm').onsubmit = event => { event.preventDefault(); send($('prompt').value); };
$('changeForm').onsubmit = event => { event.preventDefault(); send($('changePrompt').value); };
document.querySelectorAll('[data-prompt]').forEach(chip => chip.onclick = () => { $('prompt').value = chip.dataset.prompt; $('prompt').focus(); });

async function plan() {
    try { render(await api('plan', {memory: +$('memory').value, encrypt: $('encrypt').checked})); return true; }
    catch (error) { showError(error); return false; }
}
$('placeButton').onclick = async () => {
    if (current.plan) { openSheet('place'); return; }
    $('placeButton').disabled = true; $('placeText').innerHTML = '<span class="spin"></span> Measuring the system…';
    if (await plan()) openSheet('place');
};
// Memory and encryption change the room the preview needs, so the options are measured again.
for (const id of ['memory', 'encrypt']) $(id).onchange = async () => { replanning = true; validateBuild(); render(current); await plan(); replanning = false; render(current); };
for (const id of ['optionAccepted', 'optionPath', 'password', 'passphrase']) $(id).oninput = validateBuild;
$('buildForm').onsubmit = async event => {
    event.preventDefault(); const option = selectedOption(); if (!option || $('build').disabled) return; $('build').disabled = true;
    const password = $('password').value, passphrase = $('passphrase').value; $('password').value = ''; $('passphrase').value = '';
    try {
        await api('build', {digest: current.plan.digest, option: option.id, accepted: $('optionAccepted').checked, confirmation: $('optionPath').value.trim(),
                            password, passphrase, memory: +$('memory').value, cpus: +$('cpus').value});
        $('optionAccepted').checked = false; $('optionPath').value = ''; shown = 0; sun.share = 0; openSheet(''); await refresh();
    } catch (error) { showError(error); validateBuild(); }
};
const post = path => async () => { try { render(await api(path, {})); } catch (error) { showError(error); } };
$('stop').onclick = $('stopBuild').onclick = $('stopForFinal').onclick = post('stop');
$('resumeInline').onclick = post('resume');
async function revert() {
    if (!revertAsk) { revertAsk = true; render(current); return; }
    revertAsk = false; closeAll();
    try { render(await api('revert', {})); } catch (error) { showError(error); }
}
$('revert').onclick = $('revertInline').onclick = revert;
$('keep').onclick = () => { revertAsk = false; render(current); };
$('decide').onclick = () => openSheet('final');
$('retryFinal').onclick = () => openSheet('final');
document.querySelectorAll('input[name=layout]').forEach(input => input.onchange = updateLayoutWarning);
for (const id of ['finalAccepted', 'targetConfirm', 'finalPassphrase']) $(id).oninput = validateFinal;
$('finalInstallForm').onsubmit = async event => {
    event.preventDefault(); if ($('installFinal').disabled) return; $('installFinal').disabled = true;
    const passphrase = $('finalPassphrase').value; $('finalPassphrase').value = '';
    try {
        await api('final/finalize', {layout: document.querySelector('input[name=layout]:checked').value, confirmation: $('targetConfirm').value.trim(),
                                     accepted: $('finalAccepted').checked, passphrase});
        shown = 0; sun.share = 0; Object.assign(sun.now, {arc: 0, grow: 0, lift: .35}); openSheet(''); await refresh();
    } catch (error) { $('finalError').textContent = error.message; $('finalError').hidden = false; validateFinal(); }
};
async function powerAction(action) {
    try { const result = await api('final/power', {action}); $('rebootLive').disabled = $('poweroffLive').disabled = true; $('powerMessage').textContent = result.message; }
    catch (error) { showError(error); }
}
$('rebootLive').onclick = () => powerAction('reboot');
$('poweroffLive').onclick = () => powerAction('poweroff');

/* ── model settings ───────────────────────────────────── */
const PROVIDER_NOTES = {chatgpt: 'Sign-in opens in a new tab of this browser. Finish it there.', ollama: 'For Ollama on the QEMU host, use http://10.0.2.2:11434.',
                        compatible: 'Any OpenAI-compatible API with structured JSON replies.'};
function pickProvider(kind) {
    providerKind = kind;
    document.querySelectorAll('#providerKinds .seg').forEach(seg => seg.setAttribute('aria-checked', String(seg.dataset.kind === kind)));
    $('keyField').hidden = ['chatgpt', 'ollama'].includes(kind);
    $('endpointField').hidden = kind === 'chatgpt';
    $('providerNote').textContent = PROVIDER_NOTES[kind] || 'The key stays in memory on this computer and never enters the chat. API usage may be billed separately.';
    $('providerSubmit').textContent = kind === 'chatgpt' ? 'Sign in to ChatGPT' : 'Connect';
    $('providerError').hidden = true;
}
document.querySelectorAll('#providerKinds .seg').forEach(seg => seg.onclick = () => pickProvider(seg.dataset.kind));
$('settingsButton').onclick = $('connectButton').onclick = () => { pickProvider(providerKind); $('settings').showModal(); };
$('closeSettings').onclick = () => $('settings').close();
$('providerForm').onsubmit = async event => {
    event.preventDefault();
    $('providerSubmit').disabled = true;
    $('providerError').hidden = false; $('providerError').className = 'hint';
    $('providerError').textContent = providerKind === 'chatgpt' ? 'Connecting. If a sign-in tab opened, finish signing in there.' : 'Connecting…';
    try {
        render(await api('provider', {kind: providerKind, model: $('providerModel').value, endpoint: $('endpoint').value, key: $('key').value}));
        $('key').value = ''; $('providerError').hidden = true; $('settings').close();
    } catch (error) { $('providerError').className = 'line error'; $('providerError').textContent = error.message; }
    finally { $('providerSubmit').disabled = false; }
};

/* ── the preview's screen through Guacamole ───────────── */
function disconnect() {
    if (keyboard) keyboard.reset();
    if (client) client.disconnect();
    client = null; connected = false;
    $('screen').replaceChildren();
}
function scaleDisplay() {
    if (!client) return;
    const display = client.getDisplay();
    if (display.getWidth()) display.scale(Math.min($('screen').clientWidth / display.getWidth(), $('screen').clientHeight / display.getHeight()));
}
function connect() {
    disconnect();
    lastConnect = Date.now();
    if (!window.Guacamole) { showError('The Guacamole client is not installed in this image'); return; }
    const screen = $('screen');
    const tunnel = new Guacamole.WebSocketTunnel(`ws://${location.host}/tunnel`);
    client = new Guacamole.Client(tunnel);
    const active = client, display = client.getDisplay();
    screen.append(display.getElement());
    display.onresize = scaleDisplay;
    client.onerror = error => { connected = false; showError(error.message || 'The screen disconnected'); if (current) render(current); };
    client.onstatechange = state => { connected = state === 3; if (current) render(current); };
    mouse = new Guacamole.Mouse(display.getElement());
    mouse.onmousedown = mouse.onmouseup = mouse.onmousemove = state => {
        if (client === active) { if (state.left || state.right || state.middle) screen.focus({preventScroll: true}); active.sendMouseState(state, true); }
    };
    if (!keyboard) {
        keyboard = new Guacamole.Keyboard(screen);
        keyboard.onkeydown = keysym => { if (client) client.sendKeyEvent(1, keysym); return false; };
        keyboard.onkeyup = keysym => { if (client) client.sendKeyEvent(0, keysym); };
        screen.onblur = () => keyboard.reset();
    }
    client.connect();
}
$('reconnect').onclick = connect;
$('fullscreen').onclick = () => document.fullscreenElement ? document.exitFullscreen() : $('vm').requestFullscreen().catch(showError);
document.addEventListener('fullscreenchange', () => { $('fullscreen').textContent = document.fullscreenElement ? 'Exit full screen' : 'Full screen'; });
new ResizeObserver(scaleDisplay).observe($('screen'));
window.addEventListener('beforeunload', () => { if (keyboard) keyboard.reset(); if (client) client.disconnect(); });
window.addEventListener('blur', () => { if (keyboard) keyboard.reset(); });
setInterval(refresh, 1500);
refresh();
