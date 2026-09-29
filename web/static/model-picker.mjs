// The credentials stay in the form and in requests to the local server.
// Each change invalidates older requests before the next list is loaded.
export class ModelPicker {
    constructor(element, request, option = (value, text) => new Option(text, value)) {
        this.element = element;
        this.request = request;
        this.option = option;
        this.kind = 'chatgpt';
        this.generation = 0;
        this.timer = null;
        this.connected = false;
        this.element('providerModels').onchange = () => {
            this.element('providerModel').value = this.element('providerModels').value;
        };
        for (const id of ['key', 'endpoint']) {
            this.element(id).addEventListener('input', () => this.credentialsChanged());
        }
        this.element('listModels').onclick = () => this.load();
        this.element('manualModel').onclick = () => {
            this.element('manualModelField').hidden = false;
            this.element('providerModel').focus();
        };
        this.element('providerModel').addEventListener('input', () => {
            this.element('providerModels').value = this.element('providerModel').value;
        });
    }

    invalidate() {
        clearTimeout(this.timer);
        this.generation += 1;
        this.element('listModels').disabled = false;
    }

    reset(kind, connected = false, models = [], selected = '') {
        this.invalidate();
        this.kind = kind;
        this.connected = connected;
        this.element('providerModel').value = '';
        this.element('manualModelField').hidden = true;
        this.element('listModelsRow').hidden = kind === 'chatgpt' && !connected;
        this.show(models, selected);
        if (kind === 'ollama') this.credentialsChanged();
    }

    show(models, selected = '') {
        const select = this.element('providerModels');
        const names = [...new Set(models)].sort((a, b) => a.localeCompare(b));
        select.replaceChildren(this.option('', names.length ? 'Choose a model' : 'No models loaded'),
            ...names.map(name => this.option(name, name)));
        select.disabled = names.length === 0;
        select.value = names.includes(selected) ? selected : '';
        this.element('providerModel').value = select.value;
        this.element('providerModelsStatus').textContent = names.length
            ? `${names.length} models available. Choose one from the list.`
            : this.kind === 'chatgpt' ? 'Sign in to see the available models.'
            : 'Models load automatically after you enter the API key or URL.';
    }

    credentialsChanged() {
        this.invalidate();
        this.show([]);
        const key = this.element('key').value.trim();
        const endpoint = this.element('endpoint').value.trim();
        const ready = this.kind === 'ollama' || (this.kind === 'compatible' ? !!endpoint : !!key);
        if (this.kind !== 'chatgpt' && ready) {
            this.timer = setTimeout(() => this.load(), 600);
        }
    }

    async load() {
        this.invalidate();
        const generation = this.generation;
        const selected = this.element('providerModel').value;
        this.element('listModels').disabled = true;
        this.element('providerModelsStatus').textContent = 'Loading models…';
        try {
            const {models} = await this.request('provider/models', {
                kind: this.kind, endpoint: this.element('endpoint').value,
                key: this.kind === 'chatgpt' ? '' : this.element('key').value
            });
            if (generation !== this.generation) return;
            this.show(models, selected);
            if (!models.length) this.element('providerModelsStatus').textContent = 'The provider listed no models. You can enter a model ID.';
        } catch (error) {
            if (generation === this.generation) {
                this.element('providerModelsStatus').textContent = `${error.message} Retry or enter a model ID.`;
            }
        } finally {
            if (generation === this.generation) this.element('listModels').disabled = false;
        }
    }
}
