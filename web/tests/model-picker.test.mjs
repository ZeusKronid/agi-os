import assert from 'node:assert/strict';
import {test} from 'node:test';
import {ModelPicker} from '../static/model-picker.mjs';

class Element {
    value = '';
    hidden = false;
    disabled = false;
    textContent = '';
    children = [];
    events = {};
    addEventListener(event, callback) { this.events[event] = callback; }
    replaceChildren(...children) { this.children = children; }
    focus() { this.focused = true; }
}

function setup(request = async () => ({models: ['z-model', 'a-model', 'a-model']})) {
    const elements = new Map();
    const element = id => {
        if (!elements.has(id)) elements.set(id, new Element());
        return elements.get(id);
    };
    const picker = new ModelPicker(element, request, (value, text) => ({value, text}));
    return {picker, element};
}

test('models populate a dropdown and choosing one supplies its ID', async () => {
    const {picker, element} = setup();
    picker.reset('openai');
    await picker.load();
    assert.deepEqual(element('providerModels').children.map(option => option.value), ['', 'a-model', 'z-model']);
    assert.equal(element('providerModels').disabled, false);
    element('providerModels').value = 'z-model';
    element('providerModels').onchange();
    assert.equal(element('providerModel').value, 'z-model');
});

test('entering credentials automatically loads models after the debounce', async context => {
    context.mock.timers.enable({apis: ['setTimeout']});
    const calls = [];
    const {picker, element} = setup(async (path, body) => {
        calls.push({path, body});
        return {models: ['new-model']};
    });
    picker.reset('anthropic');
    element('key').value = 'public-test-key';
    element('key').events.input();
    context.mock.timers.tick(599);
    assert.equal(calls.length, 0);
    context.mock.timers.tick(1);
    await Promise.resolve();
    assert.equal(calls.length, 1);
    assert.deepEqual(calls[0], {path: 'provider/models', body: {kind: 'anthropic', key: 'public-test-key', endpoint: ''}});
    assert.equal(element('providerModels').disabled, false);
});

test('changing providers discards a late response', async () => {
    let resolve;
    const {picker, element} = setup(() => new Promise(done => { resolve = done; }));
    picker.reset('openai');
    const pending = picker.load();
    picker.reset('gemini');
    resolve({models: ['old-provider-model']});
    await pending;
    assert.deepEqual(element('providerModels').children.map(option => option.value), ['']);
    assert.equal(element('providerModel').value, '');
    assert.equal(element('listModels').disabled, false);
});

test('changing or clearing a key discards old models and a late error', async () => {
    let reject;
    const {picker, element} = setup(() => new Promise((_, fail) => { reject = fail; }));
    picker.reset('openai', false, ['old-model'], 'old-model');
    const pending = picker.load();
    element('key').value = '';
    element('key').events.input();
    reject(new Error('Old key failed'));
    await pending;
    assert.equal(element('providerModel').value, '');
    assert.equal(element('providerModels').disabled, true);
    assert.doesNotMatch(element('providerModelsStatus').textContent, /Old key failed/);
});

test('the newest request controls the list and loading state', async () => {
    const completions = [];
    const {picker, element} = setup(() => new Promise(done => completions.push(done)));
    picker.reset('openai');
    const old = picker.load();
    const latest = picker.load();
    completions[0]({models: ['old-model']});
    await old;
    assert.equal(element('listModels').disabled, true);
    completions[1]({models: ['current-model']});
    await latest;
    assert.equal(element('providerModels').children[1].value, 'current-model');
    assert.equal(element('listModels').disabled, false);
});

test('listing failures allow retry and manual model entry', async () => {
    const {picker, element} = setup(async () => { throw new Error('Key not accepted'); });
    picker.reset('openai');
    await picker.load();
    assert.match(element('providerModelsStatus').textContent, /Key not accepted/);
    assert.equal(element('listModels').disabled, false);
    element('manualModel').onclick();
    assert.equal(element('manualModelField').hidden, false);
    assert.equal(element('providerModel').focused, true);
});

test('an empty list offers manual entry without selecting a model', async () => {
    const {picker, element} = setup(async () => ({models: []}));
    picker.reset('compatible');
    await picker.load();
    assert.match(element('providerModelsStatus').textContent, /listed no models/);
    assert.equal(element('providerModel').value, '');
    assert.equal(element('providerModels').disabled, true);
});

test('signed-in ChatGPT lists models without sending API credentials', async () => {
    const calls = [];
    const {picker, element} = setup(async (path, body) => {
        calls.push(body);
        return {models: ['chat-model', 'another-model']};
    });
    element('key').value = 'unused-public-test-key';
    picker.reset('chatgpt', true, ['chat-model'], 'chat-model');
    await picker.load();
    assert.equal(calls[0].key, '');
    assert.equal(element('providerModels').value, 'chat-model');
    assert.equal(element('providerModel').value, 'chat-model');
});

test('Ollama loads automatically without an API key', async context => {
    context.mock.timers.enable({apis: ['setTimeout']});
    const {picker, element} = setup();
    picker.reset('ollama');
    context.mock.timers.tick(600);
    await Promise.resolve();
    assert.equal(element('providerModels').disabled, false);
});
