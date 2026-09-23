const $ = id => document.getElementById(id);
let current, busy = false, client, keyboard, mouse, connected = false, lastMessages = '', consoleId = null, lastConnect = 0, lastPlan = '';
const gib = bytes => (bytes / 2**30).toFixed(1) + ' ГиБ';
async function api(path, data) {
    const response = await fetch('/api/' + path, data === undefined ? {} : {
        method: 'POST', headers: {'Content-Type': 'application/json', 'X-AGIOS': 'local'}, body: JSON.stringify(data)
    });
    const text = await response.text();
    let result; try { result = JSON.parse(text); } catch { result = {error: text}; }
    if (!response.ok) throw new Error(result.error || 'Запрос не выполнен');
    return result;
}
function showError(error) { $('error').textContent = error.message || error; $('error').hidden = false; }
function selectedOption() {
    const input = document.querySelector('input[name=option]:checked');
    return input && current.plan ? current.plan.options.find(o => o.id === input.value) : null;
}
function renderOptions(plan) {
    const box = $('options'); box.replaceChildren();
    for (const option of plan.options) {
        const label = document.createElement('label'); label.className = 'option' + (option.fits ? '' : ' unfit') + (option.recommended ? ' recommended' : '');
        const input = document.createElement('input'); input.type = 'radio'; input.name = 'option'; input.value = option.id; input.disabled = !option.fits;
        if (option.recommended) input.checked = true;
        input.onchange = updateOptionConsent;
        const body = document.createElement('div');
        const title = document.createElement('b'); title.textContent = option.title + (option.recommended ? ' — рекомендуем' : '') + (option.fits ? '' : ' — не хватает места');
        const detail = document.createElement('span'); detail.textContent = option.detail;
        const revert = document.createElement('small'); revert.textContent = 'Откат: ' + option.revert;
        body.append(title, detail, revert); label.append(input, body); box.append(label);
    }
    updateOptionConsent();
}
function updateOptionConsent() {
    const option = selectedOption();
    $('optionConfirm').hidden = !(option && option.destructive);
    if (option && option.destructive) { $('optionWarning').textContent = option.kind === 'erase' ? 'Все данные на ' + option.confirm + ' будут удалены до превью. Это необратимо.' : 'Раздел ' + option.confirm + ' будет уменьшен. Данные сохраняются, но сделайте резервную копию.'; $('optionPath').placeholder = option.confirm; }
    $('optionAcceptText').textContent = option ? (option.destructive ? 'Я понимаю последствия и подтверждаю' : 'Я понимаю, что будет сделано. Откат: ' + option.revert) : 'Выберите вариант';
    $('build').disabled = !option;
}
function render(state) {
    current = state;
    $('model').textContent = state.model || 'Выберите модель';
    $('status').textContent = state.status;
    $('phase').textContent = ({idle:'Ожидает сборки',starting:'Подготовка',installing:'Установка в превью',ready:'Превью запущено',stopped:'Остановлено',error:'Нужна проверка',finalized:'Установлено на компьютер'})[state.phase] || state.phase;
    const serialized = JSON.stringify(state.messages);
    if (serialized !== lastMessages && state.messages.length) {
        lastMessages = serialized;
        $('messages').replaceChildren();
        for (const message of state.messages) {
            const div = document.createElement('div'); div.className = 'message ' + message.role;
            const role = document.createElement('span'); role.className = 'role'; role.textContent = message.role === 'user' ? 'ВЫ' : 'AGIOS';
            div.append(role, document.createTextNode(message.content));
            $('messages').append(div);
        }
        const last = state.messages.at(-1);
        for (const suggestion of last.suggestions || []) {
            if (typeof suggestion !== 'string') continue;
            const button = document.createElement('button'); button.className = 'suggestion'; button.textContent = suggestion;
            button.onclick = () => {$('prompt').value = suggestion; $('prompt').focus();}; $('messages').append(button);
        }
        $('messages').scrollTop = $('messages').scrollHeight;
    }
    $('error').hidden = !state.error;
    if (state.error) $('error').textContent = state.error;
    const finalizing = state.final.phase === 'working';
    const installing = ['starting','installing'].includes(state.phase) || finalizing;
    $('review').hidden = !state.configuration || !!state.built || installing || state.running;
    $('summary').textContent = state.summary || '';
    $('reviewDisk').textContent = state.consent && state.consent.disk ? state.consent.disk.path + ' · ' + gib(state.consent.disk.size) + ' · ' + (state.consent.disk.model || 'Диск') : (state.consent && state.consent.error ? 'Диск недоступен' : '');
    $('consentError').hidden = !(state.consent && state.consent.error);
    if (state.consent && state.consent.error) $('consentError').textContent = state.consent.error;
    $('planForm').hidden = !!state.plan;
    $('buildForm').hidden = !state.plan;
    if (state.plan) {
        $('estimate').textContent = `Система займёт ${gib(state.plan.estimate.installed)} (${state.plan.estimate.packages} пакетов, скачать ${gib(state.plan.estimate.download)}). Для превью с запасом нужно ${gib(state.plan.needed)}. Целевой диск: ${state.configuration.disk}.` + (state.plan.encrypt ? ' Корень будет зашифрован.' : '');
        $('passphraseField').hidden = !state.plan.encrypt; $('passphrase').required = !!state.plan.encrypt;
        if (lastPlan !== state.plan.digest) { lastPlan = state.plan.digest; renderOptions(state.plan); }
    }
    $('send').disabled = busy || installing;
    $('stop').hidden = !state.running && !installing;
    $('resume').hidden = !state.can_resume;
    $('reconnect').hidden = !state.running;
    $('fullscreen').hidden = !state.running;
    $('logs').hidden = !state.events.length;
    $('events').textContent = state.events.map(event => event.text || event.kind).join('\n');
    if (state.running && (!client || consoleId !== state.console_id || (!connected && Date.now() - lastConnect > 6000))) {consoleId = state.console_id; connect();}
    if (!state.running && client) disconnect();
    $('stop').disabled = finalizing;
    $('resume').disabled = finalizing;
    renderHardware(state.hardware);
    $('orphans').hidden = !state.orphans || !state.orphans.length;
    if (state.orphans && state.orphans.length && $('orphanList').dataset.key !== JSON.stringify(state.orphans)) {
        $('orphanList').dataset.key = JSON.stringify(state.orphans); $('orphanList').replaceChildren();
        for (const orphan of state.orphans) {
            const row = document.createElement('div'); row.className = 'actions';
            const text = document.createElement('span'); text.textContent = `${orphan.device} · ${gib(orphan.size)} на ${orphan.disk}`;
            const button = document.createElement('button'); button.className = 'quiet'; button.textContent = 'Убрать раздел превью';
            button.onclick = async () => { if (!confirm('Удалить временный раздел ' + orphan.device + '?')) return; try { render(await api('orphans/remove', {device: orphan.device})); } catch (error) { showError(error); } };
            row.append(text, button); $('orphanList').append(row);
        }
    }
    $('previewInfo').hidden = !state.built || state.final.phase === 'complete';
    if (state.built) { $('previewStorage').textContent = state.built.storage || ''; $('previewRevertHint').textContent = 'Превью можно убрать в любой момент: ' + (state.built.revert || '') + '. Диск ' + state.built.target + ' ещё не менялся' + (state.built.on_target ? ', кроме одной временной записи раздела' : '') + '.'; }
    $('revert').disabled = !state.can_revert;
    $('finalStage').hidden = !state.can_finalize && state.final.phase === 'idle';
    $('finalInstallForm').hidden = !state.can_finalize || finalizing || state.final.phase === 'complete';
    if (state.built) {
        $('finalTarget').textContent = 'Конечный диск: ' + state.built.target + (state.built.encrypted ? ' · корень зашифрован' : '');
        $('finalPassphraseField').hidden = !state.built.encrypted;
        $('targetConfirm').placeholder = state.built.target;
        $('finalHint').textContent = state.built.on_target
            ? 'Превью уже лежит на этом диске: его разделы станут разделами системы без копирования. Перед установкой завершите работу внутри превью через меню выключения.'
            : 'Проверенная система будет скопирована пофайлово в новые разделы диска и проверена по контрольным суммам. Перед установкой завершите работу внутри превью через меню выключения.';
    }
    $('finalError').hidden = !state.final.error;
    if (state.final.error) $('finalError').textContent = state.final.error;
    $('finalProgress').hidden = state.final.phase === 'idle';
    $('finalPhase').textContent = ({working:'Установка на диск компьютера…',error:'Установка не завершена',complete:'Установка завершена'})[state.final.phase] || '';
    $('finalEvents').textContent = state.final.events.filter(e => e.kind !== 'final-warning').map(e=>e.text).join('\n');
    const warnings = state.final.warnings || [];
    $('finalWarnings').hidden = !warnings.length;
    $('finalWarnings').textContent = warnings.length ? 'Замечания: ' + warnings.join(' ') : '';
    $('finalDone').hidden = state.final.phase !== 'complete';
    $('finalDoneTitle').textContent = warnings.length ? 'Система установлена на диск компьютера — с замечаниями (см. выше)' : 'Система установлена на диск компьютера';
    updateLayoutWarning();
}
let lastHardware = '';
function renderHardware(hardware) {
    $('hardware').hidden = !hardware;
    if (!hardware) return;
    const key = JSON.stringify(hardware) + (current && current.final ? current.final.phase : ''); if (key === lastHardware) return; lastHardware = key;
    $('hardwareLines').replaceChildren(...hardware.lines.map(line => { const li = document.createElement('li'); li.textContent = line; return li; }));
    $('hardwareDrivers').textContent = (hardware.configured ? 'Установщик добавит драйверы и прошивки под это железо: ' : 'Пока выбрано по железу (список дополнится после выбора окружения): ')
        + (hardware.packages.join(', ') || 'дополнительных не требуется')
        + (hardware.services.length ? '; службы: ' + hardware.services.join(', ') : '') + '.' + (hardware.notes.length ? ' ' + hardware.notes.join('. ') + '.' : '');
    const done = current && current.final && current.final.phase === 'complete';
    $('hardwareUnverified').className = hardware.unverified.length ? 'notice' : 'hint';
    $('hardwareUnverified').textContent = !hardware.unverified.length
        ? (hardware.virtual ? 'Оборудование виртуальное: превью проверяет его полностью.' : 'Оборудования, которое превью не может проверить, не найдено.')
        : done ? 'Теперь проверьте на самом компьютере: ' + hardware.unverified.join(', ') + ' — в превью это проверить было нельзя.'
        : 'Превью работает на виртуальных устройствах и не проверяет: ' + hardware.unverified.join(', ') + '. Это проверяется только после установки на компьютер.';
}
function updateLayoutWarning() {
    if (!current || !current.built) return;
    const layout = document.querySelector('input[name=layout]:checked').value;
    $('layoutWarning').textContent = layout === 'erase' ? 'Все остальные разделы и данные на ' + current.built.target + ' будут удалены.' : 'Существующие разделы ' + current.built.target + ' сохраняются; система займёт свободное место.';
}
async function refresh() { try { render(await api('state')); } catch (error) { showError(error); } }
$('chatForm').onsubmit = async event => {
    event.preventDefault(); if (busy) return;
    const text = $('prompt').value.trim(); if (!text) return;
    busy = true; $('send').disabled = true; $('prompt').value = '';
    try { render(await api('chat', {text})); } catch (error) { showError(error); $('prompt').value = text; }
    finally { busy = false; $('send').disabled = false; }
};
$('prompt').onkeydown = event => { if (event.key === 'Enter' && !event.shiftKey) {event.preventDefault(); $('chatForm').requestSubmit();} };
document.querySelectorAll('[data-prompt]').forEach(button => button.onclick = () => {$('prompt').value = button.dataset.prompt; $('prompt').focus();});
$('planForm').onsubmit = async event => {
    event.preventDefault(); $('planButton').disabled = true;
    try { render(await api('plan', {memory: +$('memory').value, encrypt: $('encrypt').checked})); } catch (error) { showError(error); } finally { $('planButton').disabled = false; }
};
$('buildForm').onsubmit = async event => {
    event.preventDefault(); const option = selectedOption(); if (!option) return; $('build').disabled = true;
    const password = $('password').value, passphrase = $('passphrase').value; $('password').value = ''; $('passphrase').value = '';
    try {
        await api('build', {digest: current.plan.digest, option: option.id, accepted: $('optionAccepted').checked, confirmation: $('optionPath').value.trim(),
                            password, passphrase, memory: +$('memory').value, cpus: +$('cpus').value});
        $('optionAccepted').checked = false; $('optionPath').value = ''; await refresh();
    } catch (error) {showError(error);} finally {$('build').disabled = false;}
};
$('stop').onclick = async () => {try {render(await api('stop', {}));} catch (error) {showError(error);}};
$('resume').onclick = async () => {try {render(await api('resume', {}));} catch (error) {showError(error);}};
$('revert').onclick = async () => {
    if (!confirm('Убрать превью и вернуть носители в исходное состояние?')) return;
    $('revert').disabled = true;
    try {render(await api('revert', {}));} catch (error) {showError(error);} finally {$('revert').disabled = false;}
};
$('settingsButton').onclick = () => $('settings').showModal();
$('closeSettings').onclick = () => $('settings').close();
$('providerForm').onsubmit = async event => {
    event.preventDefault();
    $('providerError').textContent = 'Подключаю модель. Если открылась вкладка входа, завершите вход в ней.';
    try {render(await api('provider', {kind:$('provider').value, model:$('providerModel').value, endpoint:$('endpoint').value, key:$('key').value})); $('key').value=''; $('settings').close();}
    catch (error) {$('providerError').textContent = error.message;}
};
function disconnect() {
    if (keyboard) keyboard.reset();
    if (client) client.disconnect();
    client = null; connected = false;
    $('screen').replaceChildren(); $('screen').hidden = true; $('emptyPreview').hidden = false;
}
function connect() {
    disconnect();
    lastConnect = Date.now();
    if (!window.Guacamole) {showError('Клиент Guacamole не установлен в этом образе'); return;}
    const screen = $('screen'); screen.hidden = false; $('emptyPreview').hidden = true;
    const tunnel = new Guacamole.WebSocketTunnel(`ws://${location.host}/tunnel`);
    client = new Guacamole.Client(tunnel);
    const active = client;
    const display = client.getDisplay(); screen.append(display.getElement());
    display.onresize = () => display.scale(Math.min(screen.clientWidth / display.getWidth(), $('preview').clientHeight / display.getHeight()));
    client.onerror = error => { $('previewStatus').textContent = error.message || 'Экран отключён'; connected = false; };
    client.onstatechange = state => {connected = state === 3; $('previewStatus').textContent = connected ? 'Экран подключён · нажмите на него для управления' : 'Подключение экрана…';};
    mouse = new Guacamole.Mouse(display.getElement());
    mouse.onmousedown = mouse.onmouseup = mouse.onmousemove = state => {if(client === active){if (state.left || state.right || state.middle) screen.focus({preventScroll:true}); active.sendMouseState(state, true);}};
    if (!keyboard) {
        keyboard = new Guacamole.Keyboard(screen);
        keyboard.onkeydown = keysym => {if(client) client.sendKeyEvent(1, keysym); return false;};
        keyboard.onkeyup = keysym => {if(client) client.sendKeyEvent(0, keysym);};
        screen.onblur = () => keyboard.reset();
    }
    client.connect();
}
$('reconnect').onclick = connect;
$('fullscreen').onclick = () => $('preview').requestFullscreen();
new ResizeObserver(() => {if(client){const d=client.getDisplay(); if(d.getWidth()) d.scale(Math.min($('screen').clientWidth/d.getWidth(),$('preview').clientHeight/d.getHeight()));}}).observe($('preview'));
window.addEventListener('beforeunload', () => {if(keyboard) keyboard.reset(); if(client) client.disconnect();});
setInterval(refresh, 1500); refresh();
window.addEventListener('blur', () => {if(keyboard) keyboard.reset();});

function finalError(error) {$('finalError').textContent=error.message || error; $('finalError').hidden=false;}
document.querySelectorAll('input[name=layout]').forEach(input => input.onchange = updateLayoutWarning);
$('finalInstallForm').onsubmit = async event => {
    event.preventDefault(); $('installFinal').disabled=true;
    const passphrase = $('finalPassphrase').value; $('finalPassphrase').value = '';
    try {await api('final/finalize',{layout: document.querySelector('input[name=layout]:checked').value, confirmation:$('targetConfirm').value.trim(), accepted:$('finalAccepted').checked, passphrase}); $('finalError').hidden = true; await refresh();}
    catch(error) {finalError(error);} finally {$('installFinal').disabled=false;}
};
async function powerAction(action, button) {
    try {const result=await api('final/power',{action}); $('rebootLive').disabled=true; $('poweroffLive').disabled=true; $('powerMessage').textContent=result.message;}
    catch(error) {finalError(error);}
}
$('rebootLive').onclick = () => powerAction('reboot');
$('poweroffLive').onclick = () => powerAction('poweroff');
