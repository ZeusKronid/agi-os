const $ = id => document.getElementById(id);
let current, busy = false, client, keyboard, mouse, connected = false, lastMessages = '', consoleId = null, lastConnect = 0;
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
function render(state) {
    current = state;
    $('model').textContent = state.model || 'Выберите модель';
    $('status').textContent = state.status;
    $('phase').textContent = ({idle:'Ожидает сборки',starting:'Запуск VM',installing:'Установка',ready:'Система запущена',stopped:'Остановлена',error:'Нужна проверка'})[state.phase] || state.phase;
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
    const deploying = state.deployment.phase === 'writing';
    const installing = ['starting','installing'].includes(state.phase) || deploying;
    $('review').hidden = !state.configuration;
    $('summary').textContent = state.summary || '';
    $('buildForm').hidden = state.running || installing;
    $('send').disabled = busy || installing;
    $('stop').hidden = !state.running && !installing;
    $('resume').hidden = !state.can_resume;
    $('reconnect').hidden = !state.running;
    $('fullscreen').hidden = !state.running;
    $('logs').hidden = !state.events.length;
    $('events').textContent = state.events.map(event => event.text || event.kind).join('\n');
    if (state.running && (!client || consoleId !== state.console_id || (!connected && Date.now() - lastConnect > 6000))) {consoleId = state.console_id; connect();}
    if (!state.running && client) disconnect();
    $('stop').disabled = deploying;
    $('resume').disabled = deploying;
    $('finalStage').hidden = !state.can_deploy && state.deployment.phase === 'idle';
    $('finalChoice').hidden = deploying || state.deployment.phase === 'complete';
    $('finalInstallForm').hidden = !state.final_review || deploying || state.deployment.phase === 'complete';
    if (state.final_review) {
        const d = state.final_review.disk;
        $('finalSummary').textContent = `${d.path} · ${(d.size / 2**30).toFixed(1)} ГиБ · ${d.model || 'Диск'}\nСерийный номер: ${d.serial || 'не указан'}\n\nБудет перенесена проверенная система вместе с файлами и настройками. Корневой раздел займёт доступное место на диске.`;
    }
    $('finalError').hidden = !state.deployment.error;
    if (state.deployment.error) $('finalError').textContent = state.deployment.error;
    $('finalProgress').hidden = state.deployment.phase === 'idle';
    $('finalPhase').textContent = ({writing:'Установка на конечный диск…',error:'Перенос не завершён',complete:'Перенос завершён'})[state.deployment.phase] || '';
    $('finalEvents').textContent = state.deployment.events.map(e=>e.text).join('\n');
    $('finalDone').hidden = state.deployment.phase !== 'complete';

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
$('buildForm').onsubmit = async event => {
    event.preventDefault(); $('build').disabled = true;
    const password = $('password').value; $('password').value = '';
    try {await api('build', {digest: current.digest, password, memory: +$('memory').value, cpus: +$('cpus').value}); await refresh();}
    catch (error) {showError(error);} finally {$('build').disabled = false;}
};
$('stop').onclick = async () => {try {render(await api('stop', {}));} catch (error) {showError(error);}};
$('resume').onclick = async () => {try {render(await api('resume', {}));} catch (error) {showError(error);}};
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
    if (!window.Guacamole) {showError('Клиент Guacamole не установлен. Запустите scripts/prepare-web.sh'); return;}
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
$('loadTargets').onclick = async () => {
    try {
        const result = await api('targets');
        $('targetDisk').replaceChildren(new Option('Выберите диск…',''));
        for (const d of result.disks) {
            const option = new Option(`${d.path} · ${(d.size/2**30).toFixed(1)} ГиБ · ${d.model || 'Диск'} · ${d.serial || ''}${d.eligible ? '' : ' — '+d.reason}`,d.path);
            option.disabled = !d.eligible; $('targetDisk').append(option);
        }
        $('targetForm').hidden=false;
    } catch(error) {finalError(error);}
};
$('targetForm').onsubmit = async event => {
    event.preventDefault();
    try {render(await api('final/review',{target:$('targetDisk').value})); $('targetConfirm').value=''; $('previewAccepted').checked=false;}
    catch(error) {finalError(error);}
};
$('finalInstallForm').onsubmit = async event => {
    event.preventDefault(); $('installFinal').disabled=true;
    try {await api('final/install',{digest:current.final_review.digest,confirmation:$('targetConfirm').value,preview_accepted:$('previewAccepted').checked}); await refresh();}
    catch(error) {finalError(error);} finally {$('installFinal').disabled=false;}
};
$('poweroffLive').onclick = async () => {
    try {const result=await api('final/poweroff',{});$('poweroffLive').disabled=true;$('poweroffLive').textContent=result.message;}
    catch(error) {finalError(error);}
};
