// AGIOS Live workspace: one sunrise scene. Talk → find room for the preview → the sun rises while it builds →
// the preview VM stands on the horizon under the sun → install or put it back → the sun rises again while it installs → good morning.
const $ = id => document.getElementById(id);
const gib = bytes => (bytes / 2**30).toFixed(1) + ' GiB';
// Like the site, the workspace always plays its motion: the system reduced-motion setting is not honored.
let current, busy = false, client, keyboard, mouse, connected = false, consoleId = null, lastConnect = 0;
let lastMessages = '', lastPlan = '', lastFacts = '', sheet = '', modal = '', installStep = 1, stopping = false, chatView = false, changeAsked = false, revertAsk = false, orphanAsk = '', replanning = false;
let providerKind = 'chatgpt', shown = 0, placeStep = 1, foundAsk = '', lastFound = '', lastFiles = '', lastHardware = '', lastLogin = '';

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
    // The back arrow of the preview returns to the conversation; the preview keeps running meanwhile.
    if (chatView) return 'talk';
    if (s.running || s.built || ['stopped', 'error'].includes(s.phase)) return 'preview';
    return 'talk';
}
function chapter(s) {
    const place = scene(s);
    if (place === 'done' || place === 'install' || modal === 'install') return 3;
    if (place === 'build' || place === 'preview') return 2;
    if (chatView) return 0;
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
const sun = {now: {hy: -1, rs: .17, arc: 0, grow: 0, energy: .3, lift: 0, dim: 1}, goal: {hy: .42, rs: .17, arc: 1, grow: .8, energy: .3, lift: 1, dim: 1},
             dots: [], far: false, share: 0};
function drawSun(time) {
    const canvas = $('sky'), w = innerWidth, h = innerHeight, dpr = Math.min(2, devicePixelRatio || 1);
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); }
    const k = .045;
    for (const key in sun.goal) sun.now[key] += (sun.goal[key] - sun.now[key]) * k;
    const s = sun.now, ctx = canvas.getContext('2d'); ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, h);
    const hy = s.hy * h, r = Math.min(s.rs * h, w * .36), cx = w / 2, cy = hy + (1 - s.lift) * r * 1.25, t = time;
    ctx.save(); ctx.globalAlpha = s.dim;
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
    if (sun.far) { ctx.fillStyle = '#ff6a3d'; ctx.globalAlpha = s.dim; for (const side of [-1, 1]) { ctx.beginPath(); ctx.arc(cx + side * r * 2.35, cy - r * .55, 2.4, 0, 6.283); ctx.fill(); } }
    ctx.restore();
    const line = ctx.createLinearGradient(0, 0, w, 0); line.addColorStop(0, 'rgba(255,255,255,0)'); line.addColorStop(.5, 'rgba(255,255,255,.14)'); line.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.fillStyle = line; ctx.fillRect(0, hy, w, 1);
    // The percentage counts up with the arc instead of jumping between engine messages.
    shown += (sun.share - shown) * .08;
    if (!$('rise').hidden) $('pct').textContent = Math.round(shown * 100);
}
// Nothing is drawn before the first state arrives, so the sun starts where the scene needs it.
function frame(time) { if (!document.hidden && current) drawSun(time / 1000); requestAnimationFrame(frame); }
requestAnimationFrame(frame);

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
        for (const box of [$('messages')]) {
            box.replaceChildren();
            state.messages.forEach((message, index) => {
                const line = document.createElement('div'); line.className = 'line ' + (message.role === 'user' ? 'user' : 'assistant') + (index >= fresh ? ' fresh' : '');
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
        $('lines').scrollTop = $('lines').scrollHeight;
    }
    $('talk').classList.toggle('chatting', state.messages.length > 0 || busy);
    $('welcome').hidden = state.messages.length > 0 || busy;
    $('thinking').hidden = !busy;
    if (busy) $('thinkingText').textContent = state.status;
    $('error').hidden = !state.error || place !== 'talk';
    if (state.error) $('error').textContent = state.error;

    const consentError = state.consent && state.consent.error;
    $('consentError').hidden = !consentError;
    if (consentError) $('consentError').textContent = 'The target disk is unavailable: ' + consentError;
    const hasPreview = !!(state.built || state.running || ['stopped', 'error'].includes(state.phase));
    if (!hasPreview) chatView = false;
    $('previewButton').hidden = !chatView || busy;
    $('placeButton').hidden = !config || place !== 'talk' || busy || hasPreview;
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
            : !state.running ? ['VM stopped · preview kept', 'Start it again to keep checking — or install it now.']
            : !connected ? ['Connecting the screen…', ''] : null;
        $('vmState').hidden = !stateText;
        if (stateText) { $('vmStateLabel').textContent = stateText[0]; $('vmStateText').textContent = stateText[1]; $('vmStateText').hidden = !stateText[1]; }
        $('resumeInline').hidden = !state.can_resume;
        $('reconnect').hidden = !state.running || connected;
        $('revertInline').hidden = state.phase !== 'error';
        $('install').disabled = state.phase === 'error' || !state.built;
        const [dot, label] = state.phase === 'error' ? ['', 'needs a look'] : !state.running ? ['off', 'vm stopped'] : connected ? ['ok', 'live · connected'] : ['blink', 'connecting'];
        $('vmStatus').querySelector('.dot').className = 'dot ' + dot; $('vmStatus').querySelector('span').textContent = label;
        // The agent's answer to a change asked for during the preview stands above the bar.
        const answer = [...state.messages].reverse().find(message => message.role !== 'user');
        $('said').hidden = !changeAsked;
        if (changeAsked) $('saidText').innerHTML = busy ? '<span class="typing"><i></i><i></i><i></i></span>' : '';
        if (changeAsked && !busy && answer) $('saidText').textContent = answer.content;
    }
    if (place !== 'preview') changeAsked = false;
    $('said').hidden = place !== 'preview' || !changeAsked;
    document.body.classList.toggle('has-said', changeAsked);
    $('vmStatus').hidden = $('vmbar').hidden;
    $('fullscreen').hidden = !(place === 'preview' && state.running);
    $('stop').hidden = !state.running;
    $('resume').hidden = state.running || !state.can_resume;

    // Place sheet.
    if (state.plan) {
        $('estimate').textContent = `The system takes ${gib(state.plan.estimate.installed)} (${state.plan.estimate.packages} packages, ${gib(state.plan.estimate.download)} to download). `
            + `The preview needs ${gib(state.plan.needed)} with headroom. Target disk: ${config ? config.disk : ''}.` + (state.plan.encrypt ? ' The root will be encrypted.' : '')
            + (state.plan.secure_boot ? ' The bootloader and kernel will be signed for Secure Boot.' : '');
        $('passphraseField').hidden = !state.plan.encrypt;
        if (lastPlan !== state.plan.digest) {
            lastPlan = state.plan.digest; renderOptions(state.plan);
            $('memory').value = String(state.plan.memory); $('encrypt').checked = state.plan.encrypt; $('secureBoot').checked = !!state.plan.secure_boot;
        }
    }
    if (config && JSON.stringify(config) !== lastFacts) { lastFacts = JSON.stringify(config); renderFacts(config); }
    $('replanning').hidden = !replanning;
    validateBuild();

    // Decide sheet.
    if (state.built) {
        $('finalTarget').textContent = 'The system goes on ' + state.built.target + (state.built.encrypted ? ', with the root encrypted' : '') + '.';
        $('targetLabel').textContent = 'Type ' + state.built.target + ' to confirm';
        $('installFinal').innerHTML = 'Install on ' + state.built.target + ' <span class="arr">→</span>';
        $('finalPassphraseField').hidden = !state.built.encrypted;
        $('targetConfirm').placeholder = state.built.target;
        $('finalHint').textContent = state.built.on_target
            ? 'The preview already lives on this disk, so its partitions simply become the system.'
            : 'The system you tried is copied to the disk and checked file by file.';
        $('revertHint').textContent = 'You tried the system. Installing makes it this computer’s system. Putting it back removes the preview — '
            + (state.built.revert || 'nothing else changes') + '.';
    }
    // Installing needs the preview off: step 1 turns it off, step 2 installs.
    if (modal === 'install') {
        if (state.running && !stopping) installStep = 1; else if (!state.running) installStep = 2;
        $('installStep1').hidden = installStep !== 1; $('finalInstallForm').hidden = installStep !== 2;
        $('stopForFinal').disabled = stopping;
        $('stopForFinal').innerHTML = stopping ? '<span class="spin"></span> Turning off…' : 'Turn off and continue <span class="arr">→</span>';
    }
    $('finalInstallForm').querySelectorAll('input, #installFinal').forEach(el => { el.disabled = !state.can_finalize; });
    // The server stops a running VM before it removes the preview, so putting it back works either way.
    $('revert').disabled = !(state.can_revert || state.running || state.phase === 'error');
    $('revert').textContent = revertAsk ? 'Confirm: put everything back' : 'Not right — put everything back';
    $('revert').className = 'btn ' + (revertAsk ? 'danger' : 'outline');
    $('keep').hidden = !revertAsk;
    $('finalError').hidden = !state.final.error || place === 'install';
    if (state.final.error) $('finalError').textContent = state.final.error;
    updateLayoutWarning(); validateFinal();
    if (sheet === 'place' && (place !== 'talk' || !state.plan)) openSheet('');
    if (modal === 'install' && !state.built) openModal('');
    if (modal && place !== 'preview') openModal('');

    // Log: the build or the final installation.
    const events = place === 'install' || place === 'done' ? state.final.events : state.events;
    $('events').textContent = events.map(event => event.text || event.kind).join('\n') || 'Nothing yet.';

    // Guacamole: connect while the VM runs, drop the client when it stops.
    if (state.running && (!client || consoleId !== state.console_id || (!connected && Date.now() - lastConnect > 6000))) { consoleId = state.console_id; connect(); }
    if (!state.running && client) disconnect();

    renderFound(state, place);
    renderHardware(state.hardware, state);
    renderFiles(state.files || []);
    renderLogin(state.login || []);
    renderSecureBoot(state);
    renderFinalNotes(state);
    aimSun(state, place);
}
const horizon = () => Math.min(230, Math.max(170, innerHeight * .24));
function aimSun(state, place) {
    sun.far = place === 'preview';
    document.documentElement.style.setProperty('--horizon', horizon() + 'px');
    const thinking = busy && place === 'talk';
    if (place === 'done') Object.assign(sun.goal, {hy: .5, rs: .2, arc: 1, grow: 1.1, energy: .6, lift: 1, dim: 1});
    else if (place === 'build' || place === 'install') {
        const p = sun.share, failed = state.final.phase === 'error';
        Object.assign(sun.goal, {hy: .7, rs: .24, arc: Math.max(.02, p), grow: .5 + .6 * p, energy: failed ? .1 : .9, lift: .35 + .65 * p, dim: failed ? .45 : 1});
    }
    // The preview stands on the horizon like the hero headline: one sun above the window's top edge.
    else if (place === 'preview') Object.assign(sun.goal, {hy: horizon() / innerHeight, rs: Math.min(118, innerWidth * .12) / innerHeight, arc: 1, grow: 1,
                                                          energy: busy ? 1.1 : state.running ? .35 : .1, lift: 1, dim: state.phase === 'error' ? .3 : state.running ? 1 : .45});
    // While talking the sun stays at the bottom, dimmed behind the conversation that runs over it.
    else if (state.messages.length || busy) Object.assign(sun.goal, {hy: 1, rs: .2, arc: 1, grow: 1, energy: thinking ? .9 : .3, lift: 1, dim: sheet ? .2 : .35});
    else Object.assign(sun.goal, {hy: .42, rs: .17, arc: 1, grow: state.model ? 1 : .8, energy: .35, lift: 1, dim: 1});
    if (place === 'build' && sun.now.arc > sun.goal.arc + .05) Object.assign(sun.now, {arc: 0, grow: 0, lift: .35});
    // The sun never slides across the page: when it has to move far (the first paint after F5, a new scene)
    // it appears in its new place below the horizon and rises from there.
    if (Math.abs(sun.goal.hy - sun.now.hy) > .2 || Math.abs(sun.goal.rs - sun.now.rs) > .15)
        Object.assign(sun.now, {hy: sun.goal.hy, rs: sun.goal.rs, lift: 0, grow: 0});
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
        const tags = [option.recommended && 'recommended', !option.fits && (option.blocked ? 'not possible now' : 'not enough room'), option.destructive && (option.kind === 'erase' ? 'irreversible' : 'changes a partition')].filter(Boolean);
        for (const tag of tags) { const i = document.createElement('i'); i.textContent = tag; title.append(' ', i); }
        detail.textContent = option.detail; undo.textContent = 'Undo: ' + option.revert;
        body.append(title, detail, undo); card.append(radio, body); box.append(card);
        card.onclick = () => pickOption(option.id);
        card.onkeydown = event => { if (event.key === ' ' || event.key === 'Enter') { event.preventDefault(); pickOption(option.id); if (event.key === 'Enter') showPlaceStep(2); } };
        card.ondblclick = () => { pickOption(option.id); showPlaceStep(2); };
    }
    const kept = plan.options.find(o => o.id === chosen && o.fits);
    const preferred = kept || plan.options.find(o => o.recommended && o.fits) || plan.options.find(o => o.fits);
    pickOption(preferred ? preferred.id : null, !!kept);
}
let chosen = null;
function selectedOption() { return current && current.plan ? current.plan.options.find(o => o.id === chosen) : null; }
function pickOption(id, keep) {
    const option = current && current.plan && current.plan.options.find(o => o.id === id);
    if (id && (!option || !option.fits)) return;
    if (!keep) { $('optionAccepted').checked = false; $('optionPath').value = ''; }
    chosen = id;
    $('placeNext').disabled = !option;
    if (option) { $('chosenTitle').textContent = option.title; $('chosenUndo').textContent = 'Undo: ' + option.revert; }
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
    if (current && (current.login || []).length) needs.push([$('loginReviewed').checked, 'Read what starts at login']);
    needs.push([$('password').value.length >= 8, 'Password of 8+ characters']);
    if (encrypt) needs.push([$('passphrase').value.length >= 8, 'Encryption password']);
    const consent = current && current.consent && current.consent.error;
    $('build').disabled = !needsHTML($('buildNeeds'), needs) || !!consent || replanning;
}
function validateFinal() {
    if (!current || !current.built) return;
    const needs = [[$('finalAccepted').checked, 'Confirm you tried it'], [$('targetConfirm').value.trim() === current.built.target, 'Type ' + current.built.target]];
    if (current.built.encrypted) needs.push([$('finalPassphrase').value.length >= 8, 'Encryption password']);
    $('installFinal').disabled = !needsHTML($('finalNeeds'), needs) || !current.can_finalize;
}
function updateLayoutWarning() {
    if (!current || !current.built) return;
    const erase = document.querySelector('input[name=layout]:checked').value === 'erase';
    $('layoutWarning').textContent = erase ? 'Everything on ' + current.built.target + ' will be deleted, including other systems.'
        : 'Your files and other systems on ' + current.built.target + ' stay as they are.';
    $('layoutWarning').className = erase ? 'line error' : 'hint';
}
const FOUND_STATUS = {ready: 'Installed in the preview', finalizing: 'Installing on the disk was interrupted — success is not confirmed',
                      installing: 'Installing into the preview was interrupted — not finished', failed: 'Installing into the preview did not finish'};
function renderFound(state, place) {
    const found = place === 'talk' ? state.found || [] : [];
    $('orphans').hidden = !found.length && !state.scan_error;
    $('scanError').hidden = !state.scan_error; $('scanError').textContent = state.scan_error || '';
    const key = JSON.stringify([found, foundAsk]);
    if (key === lastFound) return; lastFound = key;
    $('orphanList').replaceChildren(...found.map(item => {
        const row = document.createElement('div'); row.className = 'found';
        const title = document.createElement('b'); title.textContent = item.title || (item.kind === 'file' ? 'Preview file' : 'Preview partition');
        const where = document.createElement('small');
        where.textContent = (item.kind === 'file' ? 'AGIOS-PREVIEW/preview.qcow2 on ' : 'Partition ') + item.device + ' · ' + gib(item.size) + ' · ' + (item.medium || item.disk)
            + (item.created ? ' · created ' + item.created.replace('T', ' ').slice(0, 16) : '');
        const status = document.createElement('small');
        status.textContent = item.status ? FOUND_STATUS[item.status] + (item.target ? ' · target disk ' + item.target : '') + (item.encrypted ? ' · root encrypted' : '') + (item.error ? ' · ' + item.error : '') : (item.problem || '');
        row.append(title, where, status);
        if (item.journal && item.journal.length) { const log = document.createElement('pre'); log.textContent = item.journal.join('\n'); row.append(log); }
        const actions = document.createElement('div'); actions.className = 'row';
        const action = (label, path, confirmText, style) => {
            const button = document.createElement('button'), asking = confirmText && foundAsk === path + item.id;
            button.className = 'btn ' + (asking ? 'danger' : style || 'outline'); button.textContent = asking ? confirmText : label;
            button.onclick = async () => {
                if (confirmText && !asking) { foundAsk = path + item.id; render(current); return; }
                foundAsk = ''; try { render(await api(path, {id: item.id})); } catch (error) { showError(error); }
            };
            return button;
        };
        if (item.can_continue) actions.append(action('Continue the preview', 'previews/continue'));
        if (item.can_retry) actions.append(action('Retry the installation', 'previews/retry', 'Confirm: remove ' + item.device + ' and measure again'));
        if (item.can_remove) actions.append(action('Remove', 'previews/remove', 'Confirm: remove ' + item.device, 'ghost'));
        row.append(actions); return row;
    }));
}
function renderHardware(hardware, state) {
    $('hardware').hidden = !hardware;
    if (!hardware) { $('hardwareUnverified').hidden = true; return; }
    const done = state.final.phase === 'complete', key = JSON.stringify(hardware) + done;
    if (key === lastHardware) return; lastHardware = key;
    $('hardwareLines').replaceChildren(...hardware.lines.map(line => { const li = document.createElement('li'); li.textContent = line; return li; }));
    $('hardwareDrivers').textContent = (hardware.configured ? 'The installer adds drivers and firmware for this hardware: ' : 'Chosen from the hardware so far (the desktop adds more): ')
        + (hardware.packages.join(', ') || 'none needed') + (hardware.services.length ? '; services: ' + hardware.services.join(', ') : '') + '.'
        + (hardware.notes.length ? ' ' + hardware.notes.join('. ') + '.' : '');
    $('hardwareUnverified').hidden = false;
    $('hardwareUnverified').className = hardware.unverified.length ? 'line warn' : 'hint';
    $('hardwareUnverified').textContent = !hardware.unverified.length
        ? (hardware.virtual ? 'The hardware is virtual: the preview checks all of it.' : 'Nothing here needs a check the preview can’t do.')
        : 'The preview runs on virtual devices and does not check: ' + hardware.unverified.join(', ') + '. You can only check these after installing on the computer.';
    $('doneCheck').hidden = !hardware.unverified.length;
    $('doneCheck').textContent = 'Now check on the computer itself: ' + hardware.unverified.join(', ') + ' — the preview could not check these.';
}
function highlight(content) {
    // Text nodes only: a file is data from the model and must never become markup.
    const pre = document.createElement('pre'); pre.className = 'code';
    for (const line of content.split('\n')) {
        const row = document.createElement('span'); let match;
        if (/^\s*(#|;|\/\/|--)/.test(line)) { row.className = 'c'; row.textContent = line; }
        else if (/^\s*\[[^\]]*\]\s*$/.test(line) || /^\s*(Section|EndSection|SubSection|EndSubSection)\b/i.test(line)) { row.className = 's'; row.textContent = line; }
        else if ((match = line.match(/^(\s*"?[\w.$@:\/\[\]-]+"?)(\s*[=:]\s*|\s+)(.*)$/))) {
            const key = document.createElement('span'); key.className = 'k'; key.textContent = match[1];
            row.append(key, document.createTextNode(match[2] + match[3]));
        } else row.textContent = line;
        pre.append(row, document.createTextNode('\n'));
    }
    return pre;
}
function renderFiles(files) {
    $('files').hidden = !files.length;
    const key = JSON.stringify(files); if (key === lastFiles) return; lastFiles = key;
    $('fileList').replaceChildren(...files.map(file => {
        const box = document.createElement('details'); box.className = 'file';
        const head = document.createElement('summary'), path = document.createElement('b'), checks = document.createElement('small');
        path.textContent = file.display;
        checks.textContent = file.checks.length ? 'Checked with ' + file.checks.join(', ') : 'No automatic check for this format — read it yourself';
        checks.className = file.checks.length ? '' : 'unchecked';
        head.append(path, checks); box.append(head, highlight(file.content)); return box;
    }));
}
function renderLogin(login) {
    $('login').hidden = !login.length;
    const key = JSON.stringify(login); if (key === lastLogin) return; lastLogin = key;
    $('loginReviewed').checked = false;
    $('loginList').replaceChildren(...login.map(entry => {
        const li = document.createElement('li'), head = document.createElement('b'), why = document.createElement('span'), code = document.createElement('pre');
        head.textContent = entry.path; why.textContent = ' — ' + entry.why; code.textContent = entry.commands.join('\n');
        li.append(head, why, code); return li;
    }));
}
function renderSecureBoot(state) {
    const offered = state.firmware === 'uefi' && state.configuration && state.configuration.bootloader === 'systemd-boot';
    $('secureBootField').hidden = !offered; if (!offered) $('secureBoot').checked = false;
    if (!state.built) return;
    const setupMode = !!(state.hardware && state.hardware.setup_mode);
    $('secureBootFinal').hidden = !state.built.secure_boot;
    $('enrollKeys').disabled = !setupMode; if (!setupMode) $('enrollKeys').checked = false;
    $('secureBootHint').textContent = setupMode
        ? 'The firmware is in Setup Mode. After the keys are enrolled the computer boots only signed systems: this one, Windows and other systems signed by Microsoft. The AGIOS Live stick is not signed — turn Secure Boot off to boot it. BitLocker may ask for its recovery key once.'
        : 'The firmware is not in Setup Mode, so the keys can’t be enrolled now. The system is already signed: to turn Secure Boot on later, clear the keys in the UEFI settings (Setup Mode), run “sudo sbctl enroll-keys --microsoft” in the installed system and turn Secure Boot on.';
}
function renderFinalNotes(state) {
    const warnings = state.final.warnings || [];
    $('finalWarnings').hidden = !warnings.length;
    $('finalWarnings').replaceChildren(...warnings.map(text => { const p = document.createElement('p'); p.className = 'line warn'; p.textContent = text; return p; }));
}

/* ── sheets and modals ────────────────────────────────── */
// Placing the preview goes one step at a time: first where it lives, then its settings and the password.
function showPlaceStep(step) {
    if (step === 2 && !selectedOption()) return;
    placeStep = step;
    $('placeStep1').hidden = step !== 1; $('buildForm').hidden = step !== 2;
    $('placeSheet').querySelector('.sheet-in').scrollTop = 0;
    setTimeout(() => (step === 1 ? document.querySelector('.option.selected') || $('placeNext') : $('password')).focus({preventScroll: true}), 60);
}
function openSheet(name) {
    if (name === 'place' && sheet !== 'place') showPlaceStep(1);
    sheet = name; revertAsk = false;
    $('placeSheet').classList.toggle('on', sheet === 'place'); $('placeSheet').inert = sheet !== 'place';
    $('veil').classList.toggle('on', !!sheet);
    if (current) render(current);
}
// Install and Put it back each open their own modal over the preview.
function openModal(name) {
    modal = name; revertAsk = false;
    if (modal === 'install') installStep = current && current.running ? 1 : 2;
    $('installModal').hidden = modal !== 'install'; $('backModal').hidden = modal !== 'back';
    if (modal) setTimeout(() => (modal === 'install' ? (installStep === 1 ? $('stopForFinal') : $('finalAccepted')) : $('revert')).focus({preventScroll: true}), 60);
    if (current) render(current);
}
function closeAll() { if (sheet) openSheet(''); if (modal) openModal(''); }
$('veil').onclick = closeAll;
for (const id of ['installModal', 'backModal']) $(id).onclick = event => { if (event.target === $(id)) openModal(''); };
document.querySelectorAll('[data-close]').forEach(button => button.onclick = closeAll);
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
$('changeForm').onsubmit = event => { event.preventDefault(); if ($('changePrompt').value.trim()) changeAsked = true; send($('changePrompt').value); };
document.querySelectorAll('[data-prompt]').forEach(chip => chip.onclick = () => { $('prompt').value = chip.dataset.prompt; $('prompt').focus(); });

async function plan() {
    try { render(await api('plan', {memory: +$('memory').value, encrypt: $('encrypt').checked, secure_boot: $('secureBoot').checked})); return true; }
    catch (error) { showError(error); return false; }
}
$('placeButton').onclick = async () => {
    if (current.plan) { openSheet('place'); return; }
    $('placeButton').disabled = true; $('placeText').innerHTML = '<span class="spin"></span> Measuring the system…';
    if (await plan()) openSheet('place');
};
// Memory and encryption change the room the preview needs, so the options are measured again.
for (const id of ['memory', 'encrypt', 'secureBoot']) $(id).onchange = async () => { replanning = true; validateBuild(); render(current); await plan(); replanning = false; render(current); };
for (const id of ['optionAccepted', 'optionPath', 'password', 'passphrase', 'loginReviewed']) $(id).oninput = validateBuild;
$('buildForm').onsubmit = async event => {
    event.preventDefault(); const option = selectedOption(); if (!option || $('build').disabled) return; $('build').disabled = true;
    const password = $('password').value, passphrase = $('passphrase').value; $('password').value = ''; $('passphrase').value = '';
    try {
        await api('build', {digest: current.plan.digest, option: option.id, accepted: $('optionAccepted').checked, login_reviewed: $('loginReviewed').checked, confirmation: $('optionPath').value.trim(),
                            password, passphrase, memory: +$('memory').value, cpus: +$('cpus').value});
        $('optionAccepted').checked = false; $('loginReviewed').checked = false; $('optionPath').value = ''; shown = 0; sun.share = 0; openSheet(''); await refresh();
    } catch (error) { showError(error); validateBuild(); }
};
const post = path => async () => { try { render(await api(path, {})); } catch (error) { showError(error); } };
$('stop').onclick = $('stopBuild').onclick = post('stop');
$('stopForFinal').onclick = async () => {
    stopping = true; render(current);
    try { render(await api('stop', {})); installStep = 2; setTimeout(() => $('finalAccepted').focus({preventScroll: true}), 60); }
    catch (error) { showError(error); }
    finally { stopping = false; render(current); }
};
$('toChat').onclick = () => { chatView = true; render(current); setTimeout(() => $('prompt').focus({preventScroll: true}), 60); };
$('previewButton').onclick = () => { chatView = false; render(current); };
$('resume').onclick = $('resumeInline').onclick = post('resume');
async function revert() {
    if (!revertAsk) { revertAsk = true; render(current); return; }
    revertAsk = false; closeAll();
    try { render(await api('revert', {})); } catch (error) { showError(error); }
}
$('revert').onclick = revert;
$('revertInline').onclick = () => openModal('back');
$('placeNext').onclick = () => showPlaceStep(2);
$('placeBack').onclick = () => showPlaceStep(1);
$('keep').onclick = () => { revertAsk = false; render(current); };
$('install').onclick = $('retryFinal').onclick = () => openModal('install');
$('putBack').onclick = () => openModal('back');
document.querySelectorAll('input[name=layout]').forEach(input => input.onchange = updateLayoutWarning);
for (const id of ['finalAccepted', 'targetConfirm', 'finalPassphrase']) $(id).oninput = validateFinal;
$('finalInstallForm').onsubmit = async event => {
    event.preventDefault(); if ($('installFinal').disabled) return; $('installFinal').disabled = true;
    const passphrase = $('finalPassphrase').value; $('finalPassphrase').value = '';
    try {
        await api('final/finalize', {layout: document.querySelector('input[name=layout]:checked').value, confirmation: $('targetConfirm').value.trim(),
                                     accepted: $('finalAccepted').checked, enroll_keys: $('enrollKeys').checked, passphrase});
        shown = 0; sun.share = 0; Object.assign(sun.now, {arc: 0, grow: 0, lift: .35}); openModal(''); await refresh();
    } catch (error) { $('finalError').textContent = error.message; $('finalError').hidden = false; validateFinal(); }
};
async function powerAction(action) {
    try { const result = await api('final/power', {action}); $('rebootLive').disabled = $('poweroffLive').disabled = true; $('powerMessage').textContent = result.message; }
    catch (error) { showError(error); }
}
$('rebootLive').onclick = () => powerAction('reboot');
$('rescan').onclick = post('previews/scan');
$('diagnosticsButton').onclick = async () => {
    const button = $('diagnosticsButton'); button.disabled = true; button.textContent = 'Collecting…';
    try {
        const response = await fetch('/api/diagnostics', {method: 'POST', headers: {'X-AGIOS': 'local'}});
        if (!response.ok) throw new Error('Could not collect diagnostics: ' + (await response.text()).slice(0, 300));
        const name = (response.headers.get('Content-Disposition') || '').match(/filename="([^"]+)"/);
        const link = document.createElement('a'); link.href = URL.createObjectURL(await response.blob());
        link.download = name ? name[1] : 'agios-diagnostics.tar.gz'; document.body.append(link); link.click();
        setTimeout(() => { URL.revokeObjectURL(link.href); link.remove(); }, 1000);
    } catch (error) { showError(error); } finally { button.disabled = false; button.textContent = 'Diagnostics'; }
};
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
    // The site runs as a system user without the desktop, so this tab opens the ChatGPT sign-in page itself.
    // It is opened right in the click so the browser does not block it as a pop-up.
    const chatgpt = providerKind === 'chatgpt';
    let tab = chatgpt ? window.open('about:blank', '_blank') : null, opened = false;
    const watch = chatgpt ? setInterval(async () => {
        let url; try { url = (await api('state')).login_url; } catch { return; }
        if (!url || opened || !url.startsWith('https://')) return;
        opened = true;
        if (tab && !tab.closed) { tab.opener = null; tab.location.href = url; }
        const link = document.createElement('a'); link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.textContent = 'Open the ChatGPT sign-in page';
        $('providerError').replaceChildren('Finish signing in on the ChatGPT page. If no tab opened: ', link);
    }, 700) : null;
    try {
        render(await api('provider', {kind: providerKind, model: $('providerModel').value, endpoint: $('endpoint').value, key: $('key').value}));
        $('key').value = ''; $('providerError').hidden = true; $('settings').close();
    } catch (error) { $('providerError').className = 'line error'; $('providerError').textContent = error.message; }
    finally { clearInterval(watch); if (tab && !opened && !tab.closed) tab.close(); $('providerSubmit').disabled = false; }
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
document.addEventListener('fullscreenchange', () => { $('fullscreen').title = $('fullscreen').ariaLabel = document.fullscreenElement ? 'Exit full screen' : 'Full screen'; });
addEventListener('resize', () => { if (current) render(current); });
new ResizeObserver(scaleDisplay).observe($('screen'));
window.addEventListener('beforeunload', () => { if (keyboard) keyboard.reset(); if (client) client.disconnect(); });
window.addEventListener('blur', () => { if (keyboard) keyboard.reset(); });
setInterval(refresh, 1500);
refresh();

/* ── version of this Live image and an update check only on request (CMP-137) ── */
function describeVersion(info) {
    const built = info.built ? ' · built ' + info.built.slice(0, 10) : '', revision = info.revision ? ' · ' + info.revision.slice(0, 7) : '';
    return 'AGIOS ' + (info.release ? info.version : 'development build') + built + revision;
}
api('version').then(info => { $('version').textContent = describeVersion(info); }).catch(() => {});
$('checkUpdates').onclick = async () => {
    const box = $('updateResult'); $('checkUpdates').disabled = true; box.hidden = false; box.replaceChildren('Checking…');
    try {
        const result = await api('version/check', {});
        box.replaceChildren();
        if (result.error) { box.textContent = result.error; return; }
        const latest = result.latest, line = document.createElement('p');
        line.textContent = {update: 'Version ' + latest.version + ' is available.', latest: 'You have the latest version (' + latest.version + ').',
                            development: 'This is a development build. The latest release is ' + latest.version + '.'}[result.verdict];
        box.append(line);
        if (result.verdict !== 'latest') {
            const link = document.createElement('a'); link.href = latest.url || result.download_page; link.target = '_blank'; link.rel = 'noopener'; link.textContent = 'Release ' + latest.version;
            const how = document.createElement('a'); how.href = result.download_page; how.target = '_blank'; how.rel = 'noopener'; how.textContent = 'how to verify the signature and write the stick';
            const hint = document.createElement('p'); hint.append(link, ' · ', how, latest.signed ? '' : ' · this release is not signed'); box.append(hint);
            if (latest.notes) { const notes = document.createElement('pre'); notes.textContent = latest.notes; box.append(notes); }
        }
    } catch (error) { box.textContent = error.message || error; }
    finally { $('checkUpdates').disabled = false; }
};
