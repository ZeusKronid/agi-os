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
    const login = state.login || [];
    $('login').hidden = !login.length; $('loginReviewedField').hidden = !login.length; $('loginReviewed').required = !!login.length;
    $('loginList').replaceChildren(...login.map(entry => {
        const li = document.createElement('li'), head = document.createElement('b'), why = document.createElement('span'), code = document.createElement('pre');
        head.textContent = entry.path; why.textContent = ' — ' + entry.why; code.textContent = entry.commands.join('\n');
        li.append(head, why, code); return li;
    }));
    $('reviewDisk').textContent = state.consent && state.consent.disk ? state.consent.disk.path + ' · ' + gib(state.consent.disk.size) + ' · ' + (state.consent.disk.model || 'Диск') : (state.consent && state.consent.error ? 'Диск недоступен' : '');
    $('consentError').hidden = !(state.consent && state.consent.error);
    if (state.consent && state.consent.error) $('consentError').textContent = state.consent.error;
    $('planForm').hidden = !!state.plan;
    $('secureBootField').hidden = !(state.firmware === 'uefi' && state.configuration && state.configuration.bootloader === 'systemd-boot');
    if ($('secureBootField').hidden) $('secureBoot').checked = false;
    $('buildForm').hidden = !state.plan;
    if (state.plan) {
        $('estimate').textContent = `Система займёт ${gib(state.plan.estimate.installed)} (${state.plan.estimate.packages} пакетов, скачать ${gib(state.plan.estimate.download)}). Для превью с запасом нужно ${gib(state.plan.needed)}. Целевой диск: ${state.configuration.disk}.` + (state.plan.encrypt ? ' Корень будет зашифрован.' : '') + (state.plan.secure_boot ? ' Загрузчик и ядро будут подписаны ключами Secure Boot.' : '');
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
    renderFound(state);
    renderFiles(state.files || []);
    $('previewInfo').hidden = !state.built || state.final.phase === 'complete';
    if (state.built) { $('previewStorage').textContent = state.built.storage || ''; $('previewRevertHint').textContent = 'Превью можно убрать в любой момент: ' + (state.built.revert || '') + '. Диск ' + state.built.target + ' ещё не менялся' + (state.built.on_target ? ', кроме одной временной записи раздела' : '') + '.'; }
    $('revert').disabled = !state.can_revert;
    $('finalStage').hidden = !state.can_finalize && state.final.phase === 'idle';
    $('finalInstallForm').hidden = !state.can_finalize || finalizing || state.final.phase === 'complete';
    if (state.built) {
        $('finalTarget').textContent = 'Конечный диск: ' + state.built.target + (state.built.encrypted ? ' · корень зашифрован' : '');
        $('finalPassphraseField').hidden = !state.built.encrypted;
        const setupMode = !!(state.hardware && state.hardware.setup_mode);
        $('secureBootFinal').hidden = !state.built.secure_boot;
        $('enrollKeys').disabled = !setupMode; if (!setupMode) $('enrollKeys').checked = false;
        $('secureBootHint').textContent = setupMode
            ? 'Прошивка в режиме Setup Mode. После записи ключей компьютер будет загружать только подписанные системы: эту, Windows и другие системы с подписью Microsoft. Live AGIOS не подписан — для него Secure Boot придётся временно отключить. BitLocker может один раз запросить ключ восстановления.'
            : 'Прошивка не в режиме Setup Mode, ключи сейчас не записать. Система уже подписана: чтобы включить Secure Boot позже, сотрите ключи в настройках UEFI (Setup Mode), затем в установленной системе выполните «sudo sbctl enroll-keys --microsoft» и включите Secure Boot.';
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
const foundStatus = {ready: 'Установлено в превью', finalizing: 'Установка на диск была прервана — успех не подтверждён', installing: 'Установка в превью прервана — не завершена', failed: 'Установка в превью не завершена'};
function foundAction(label, path, item, question, quiet) {
    const button = document.createElement('button'); button.textContent = label; if (quiet) button.className = 'quiet';
    button.onclick = async () => { if (question && !confirm(question)) return; try { render(await api(path, {id: item.id})); } catch (error) { showError(error); } };
    return button;
}
function renderFound(state) {
    const found = state.found || [];
    $('orphans').hidden = !found.length && !state.scan_error;
    $('scanError').hidden = !state.scan_error; $('scanError').textContent = state.scan_error || '';
    const key = JSON.stringify(found);
    if ($('orphanList').dataset.key === key) return;
    $('orphanList').dataset.key = key; $('orphanList').replaceChildren();
    for (const item of found) {
        const row = document.createElement('div'); row.className = 'found';
        const title = document.createElement('b');
        title.textContent = item.title || (item.kind === 'file' ? 'Файл превью' : 'Раздел превью');
        const where = document.createElement('small');
        where.textContent = (item.kind === 'file' ? 'Файл AGIOS-PREVIEW/preview.qcow2 на ' : 'Раздел ') + item.device + ' · ' + gib(item.size) + ' · ' + (item.medium || item.disk)
            + (item.created ? ' · создано ' + item.created.replace('T', ' ').slice(0, 16) : '');
        const status = document.createElement('small');
        status.textContent = item.status ? foundStatus[item.status] + (item.target ? ' · конечный диск ' + item.target : '') + (item.encrypted ? ' · корень зашифрован' : '') + (item.error ? ' · ' + item.error : '') : item.problem;
        row.append(title, where, status);
        if (item.journal && item.journal.length) { const log = document.createElement('pre'); log.textContent = item.journal.join('\n'); row.append(log); }
        const actions = document.createElement('div'); actions.className = 'actions';
        if (item.can_continue) actions.append(foundAction('Продолжить превью', 'previews/continue', item));
        if (item.can_retry) actions.append(foundAction('Повторить установку', 'previews/retry', item, 'Временное хранилище ' + item.device + ' будет убрано, конфигурация вернётся к расчёту места. Продолжить?'));
        if (item.can_remove) actions.append(foundAction('Убрать', 'previews/remove', item, (item.kind === 'file' ? 'Удалить папку AGIOS-PREVIEW на ' : 'Удалить временный раздел ') + item.device + '? Остальные данные не меняются.', true));
        row.append(actions); $('orphanList').append(row);
    }
}
let lastFiles = '';
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
        const head = document.createElement('summary');
        const path = document.createElement('b'); path.textContent = file.display;
        const checks = document.createElement('small');
        checks.textContent = file.checks.length ? 'Проверка: ' + file.checks.join(', ') : 'Автоматической проверки для этого формата нет — прочитайте сами';
        checks.className = file.checks.length ? '' : 'unchecked';
        head.append(path, checks); box.append(head, highlight(file.content)); return box;
    }));
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
    try { render(await api('plan', {memory: +$('memory').value, encrypt: $('encrypt').checked, secure_boot: $('secureBoot').checked})); } catch (error) { showError(error); } finally { $('planButton').disabled = false; }
};
$('buildForm').onsubmit = async event => {
    event.preventDefault(); const option = selectedOption(); if (!option) return; $('build').disabled = true;
    const password = $('password').value, passphrase = $('passphrase').value; $('password').value = ''; $('passphrase').value = '';
    try {
        await api('build', {digest: current.plan.digest, option: option.id, accepted: $('optionAccepted').checked, login_reviewed: $('loginReviewed').checked, confirmation: $('optionPath').value.trim(),
                            password, passphrase, memory: +$('memory').value, cpus: +$('cpus').value});
        $('optionAccepted').checked = false; $('loginReviewed').checked = false; $('optionPath').value = ''; await refresh();
    } catch (error) {showError(error);} finally {$('build').disabled = false;}
};
$('stop').onclick = async () => {try {render(await api('stop', {}));} catch (error) {showError(error);}};
$('resume').onclick = async () => {try {render(await api('resume', {}));} catch (error) {showError(error);}};
$('rescan').onclick = async () => {try {render(await api('previews/scan', {}));} catch (error) {showError(error);}};
$('revert').onclick = async () => {
    if (!confirm('Убрать превью и вернуть носители в исходное состояние?')) return;
    $('revert').disabled = true;
    try {render(await api('revert', {}));} catch (error) {showError(error);} finally {$('revert').disabled = false;}
};
$('settingsButton').onclick = () => $('settings').showModal();
$('diagnosticsButton').onclick = async () => {
    const button = $('diagnosticsButton'); button.disabled = true; button.textContent = 'Собираю…';
    try {
        const response = await fetch('/api/diagnostics', {method: 'POST', headers: {'X-AGIOS': 'local'}});
        if (!response.ok) throw new Error('Не удалось собрать диагностику: ' + (await response.text()).slice(0, 300));
        const name = (response.headers.get('Content-Disposition') || '').match(/filename="([^"]+)"/);
        const link = document.createElement('a'); link.href = URL.createObjectURL(await response.blob());
        link.download = name ? name[1] : 'agios-diagnostics.tar.gz'; document.body.append(link); link.click();
        setTimeout(() => { URL.revokeObjectURL(link.href); link.remove(); }, 1000);
    } catch (error) { showError(error); } finally { button.disabled = false; button.textContent = 'Диагностика'; }
};
$('closeSettings').onclick = () => $('settings').close();
$('providerForm').onsubmit = async event => {
    event.preventDefault();
    $('providerError').textContent = 'Подключаю модель. Если открылась вкладка входа, завершите вход в ней.';
    // The site runs as a system user without the desktop: this tab opens the sign-in page.
    // The tab is opened right in the click so the browser does not block it as a pop-up.
    const chatgpt = $('provider').value === 'chatgpt';
    let tab = chatgpt ? window.open('about:blank', '_blank') : null, shown = false;
    const watch = chatgpt ? setInterval(async () => {
        let url; try { url = (await api('state')).login_url; } catch { return; }
        if (!url || shown || !url.startsWith('https://')) return;
        shown = true;
        if (tab && !tab.closed) { tab.opener = null; tab.location.href = url; }
        const link = document.createElement('a'); link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer';
        link.textContent = 'Открыть страницу входа ChatGPT';
        $('providerError').replaceChildren('Завершите вход на странице ChatGPT. Если вкладка не открылась: ', link);
    }, 700) : null;
    try {render(await api('provider', {kind:$('provider').value, model:$('providerModel').value, endpoint:$('endpoint').value, key:$('key').value})); $('key').value=''; $('settings').close();}
    catch (error) {$('providerError').textContent = error.message;}
    finally { clearInterval(watch); if (tab && !shown && !tab.closed) tab.close(); }
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
    try {await api('final/finalize',{layout: document.querySelector('input[name=layout]:checked').value, confirmation:$('targetConfirm').value.trim(), accepted:$('finalAccepted').checked, enroll_keys: $('enrollKeys').checked, passphrase}); $('finalError').hidden = true; await refresh();}
    catch(error) {finalError(error);} finally {$('installFinal').disabled=false;}
};
async function powerAction(action, button) {
    try {const result=await api('final/power',{action}); $('rebootLive').disabled=true; $('poweroffLive').disabled=true; $('powerMessage').textContent=result.message;}
    catch(error) {finalError(error);}
}
$('rebootLive').onclick = () => powerAction('reboot');
$('poweroffLive').onclick = () => powerAction('poweroff');
