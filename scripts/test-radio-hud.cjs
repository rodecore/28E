'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'stream-study/embarcadero/hud.html'), 'utf8');
const moduleSource = html.match(/<script type="module">([\s\S]*?)<\/script>/)[1];
function createRadio(emitter = false, cachedNews = [], nowMs = 1000000, optionalAuth = false) {
    const timers = new Map();
    const subscriptions = new Map();
    const writes = [];
    const auth = { currentUser: null };
    let authCallback;
    let nextTimer = 0;
    let writeError = null;
    let now = nowMs;
    const baseURI = 'http://localhost:5500/stream-study/embarcadero/hud.html';
    const nodes = new Map();
    class Audio {
        constructor() {
            this.handlers = new Map();
            this.paused = true;
            this.ended = false;
            this.error = null;
            this.duration = 180;
            this.currentTime = 0;
            this.readyState = 0;
            this._src = '';
            this.loads = 0;
        }
        get src() { return this._src; }
        set src(value) { this._src = new URL(value, baseURI).href; }
        addEventListener(event, callback) {
            if (!this.handlers.has(event)) this.handlers.set(event, new Set());
            this.handlers.get(event).add(callback);
        }
        removeEventListener(event, callback) { this.handlers.get(event)?.delete(callback); }
        fire(event) {
            for (const callback of [...(this.handlers.get(event) || [])]) callback();
        }
        load() { this.loads++; this.readyState = 0; this.ended = false; this.error = null; this.currentTime = 0; }
        play() { this.paused = false; return Promise.resolve(); }
        pause() { this.paused = true; }
    }
    const audio = new Audio();
    const document = {
        baseURI,
        body: { classList: { add() {} } },
        getElementById(id) {
            if (id === 'audio-elem') return audio;
            if (!nodes.has(id)) nodes.set(id, {
                textContent: '', hidden: true, style: {}, classList: { add() {} },
                replaceChildren() {}
            });
            return nodes.get(id);
        },
        createElement() { return { textContent: '' }; },
        createTextNode(text) { return text; }
    };
    const context = vm.createContext({
        URL, URLSearchParams, Intl, Math, Date: { now: () => now },
        document, Audio, AbortController,
        window: { __radioNewsCache: { items: cachedNews }, location: { search: emitter ? '?emit' + (optionalAuth ? '&auth=optional' : '') : '', pathname: new URL(baseURI).pathname }, addEventListener() {} },
        console: { error() {} },
        initializeApp: () => ({}), getDatabase: () => ({}), getAuth: () => auth,
        onAuthStateChanged: (_, callback) => { authCallback = callback; },
        ref: (_, key) => key,
        onValue: (key, callback) => subscriptions.set(key, callback),
        set: async (key, value) => {
            writes.push({ key, value });
            if (writeError) throw writeError;
        },
        fetch: () => new Promise(() => {}),
        setInterval: () => ++nextTimer,
        setTimeout: (callback, delay) => {
            const id = ++nextTimer;
            timers.set(id, { callback, delay });
            return id;
        },
        clearTimeout: id => timers.delete(id)
    });
    // Keep the real module logic, substituting only external services and browser primitives.
    const source = moduleSource.replace(/^\s*import .*;$/gm, '');
    context.Date = class extends Date { static now() { return now; } };
    vm.runInContext(source + '\nglobalThis.radio = {syncTrack, resolveLiveTrack, findTrackIndex, publishRadioState, radioTracks, acceptNews, cycleNews, isNewsFresh};', context);
    return {
        ...context.radio, audio, auth, writes, nodes,
        setNow(value) { now = value; },
        rejectWrites(error) { writeError = error; },
        authenticate() { auth.currentUser = { uid: 'admin' }; authCallback(); },
        async settle() { for (let i = 0; i < 8; i++) await Promise.resolve(); },
        metadata() { audio.readyState = 1; audio.fire('loadedmetadata'); },
        runTimer(delay) {
            const entry = [...timers.entries()].find(([, timer]) => timer.delay === delay);
            assert.ok(entry, 'expected timer ' + delay);
            timers.delete(entry[0]);
            entry[1].callback();
        },
        state(idx = 0, extra = {}) {
            return { ...context.radio.radioTracks[idx], trackIdx: idx, startTime: now, isPlaying: true, source: 'auto', ...extra };
        }
    };
}
test('every playlist file exists and legacy/encoded URLs resolve to the same track', () => {
    const radio = createRadio();
    for (const track of radio.radioTracks) {
        assert.ok(fs.existsSync(path.join(root, track.src)), track.src);
        const legacy = 'radio/' + path.basename(track.src);
        const idx = radio.findTrackIndex(legacy);
        assert.equal(path.basename(radio.radioTracks[idx].src), path.basename(track.src));
        assert.equal(radio.findTrackIndex('https://example.org/' + encodeURI(legacy)), idx);
    }
});
test('a file error immediately after advancing also advances again', () => {
    const radio = createRadio(true);
    radio.syncTrack(radio.state());
    radio.metadata();
    radio.audio.fire('ended');
    radio.runTimer(200);
    const secondSrc = radio.audio.src;
    radio.audio.error = { code: 4 };
    radio.audio.fire('error');
    radio.runTimer(1000);
    assert.notEqual(radio.audio.src, secondSrc);
});
test('listeners accept automatic track changes while playing', () => {
    const radio = createRadio();
    radio.syncTrack(radio.state());
    radio.metadata();
    assert.equal(radio.audio.paused, false);
    radio.syncTrack(radio.state(1));
    assert.ok(radio.audio.src.endsWith(encodeURI(radio.radioTracks[1].src)));
    radio.metadata();
    assert.equal(radio.audio.paused, false);
});
test('pause during loading stays paused and resume seeks to the live position', () => {
    const radio = createRadio();
    const state = radio.state();
    radio.syncTrack(state);
    radio.syncTrack({ ...state, isPlaying: false });
    radio.metadata();
    assert.equal(radio.audio.paused, true);
    radio.setNow(state.startTime + 30000);
    radio.syncTrack({ ...state, isPlaying: true });
    assert.equal(radio.audio.currentTime, 30);
    assert.equal(radio.audio.paused, false);
});
test('repeated same-track broadcasts seek and emitter echoes do not restart playback', () => {
    const radio = createRadio(true);
    const state = radio.state();
    radio.syncTrack(state);
    radio.metadata();
    const loads = radio.audio.loads;
    radio.audio.currentTime = 12;
    radio.syncTrack(state);
    assert.equal(radio.audio.loads, loads);
    assert.equal(radio.audio.currentTime, 12);
    radio.syncTrack({ ...state, source: 'dj', startTime: state.startTime - 3500 });
    assert.equal(radio.audio.currentTime, 3.5);
});
test('emitter waits for the saved admin session and then publishes the latest state', async () => {
    const radio = createRadio(true);
    radio.syncTrack(radio.state());
    radio.audio.fire('ended');
    radio.runTimer(200);
    await radio.settle();
    assert.equal(radio.writes.length, 0);
    assert.equal(radio.nodes.get('radio-status').hidden, false);
    radio.authenticate();
    await radio.settle();
    assert.equal(radio.writes.length, 1);
    assert.equal(radio.writes[0].value.trackIdx, 1);
    assert.doesNotMatch(radio.nodes.get('radio-status').textContent, /Emisor sin sesión|No se pudo sincronizar/);
});
test('very old timestamps wrap efficiently within the complete playlist', () => {
    const radio = createRadio();
    const result = radio.resolveLiveTrack(radio.radioTracks[0].src, 0, 100 * 365 * 86400000, 0);
    assert.ok(result.seekTime >= 0 && result.seekTime < result.track.duration);
});

test('permission failures are visible and retry after the session is restored', async () => {
    const radio = createRadio(true);
    radio.authenticate();
    radio.rejectWrites(new Error('PERMISSION_DENIED'));
    await radio.publishRadioState(radio.state(1));
    assert.equal(radio.nodes.get('radio-status').hidden, false);
    assert.match(radio.nodes.get('radio-status').textContent, /permisos de Firebase/);
    radio.rejectWrites(null);
    await radio.publishRadioState(radio.state(2));
    assert.equal(radio.writes.at(-1).value.trackIdx, 2);
    assert.doesNotMatch(radio.nodes.get('radio-status').textContent, /Emisor sin sesión|No se pudo sincronizar/);
});
test('an explicit pause cancels a pending skip after a failed file', () => {
    const radio = createRadio();
    const state = radio.state();
    radio.syncTrack(state);
    radio.audio.error = { code: 4 };
    radio.audio.fire('error');
    radio.syncTrack({ ...state, isPlaying: false });
    assert.throws(() => radio.runTimer(1000), /expected timer/);
    assert.equal(radio.audio.paused, true);
});

test('ticker alternates TuneIn and Alexa promotions between blocks of six news items', () => {
    const radio = createRadio();
    const items = Array.from({ length: 8 }, (_, i) => ({
        category: 'TECNOLOGÍA', title: 'Noticia ' + i,
        publishedAt: new Date(1000000).toISOString(),
        expiresAt: new Date(2000000).toISOString()
    }));
    assert.match(radio.nodes.get('news-title').textContent, /Twenty Eight Experience Radio/);
    radio.acceptNews(items);
    for (let i = 1; i < 6; i++) radio.cycleNews(false);
    assert.equal(radio.nodes.get('news-title').textContent, 'Noticia 5');
    radio.cycleNews(false);
    assert.match(radio.nodes.get('news-title').textContent, /Alexa, reproduce radio veintiocho/);
    for (let i = 0; i < 7; i++) radio.cycleNews(false);
    assert.match(radio.nodes.get('news-title').textContent, /Twenty Eight Experience Radio/);
});
test('expired news is removed during an outage and promotions keep the ticker running', () => {
    const radio = createRadio();
    radio.acceptNews([{
        category: 'TECNOLOGÍA', title: 'Titular reciente',
        publishedAt: new Date(1000000).toISOString(),
        expiresAt: new Date(1001000).toISOString()
    }]);
    assert.equal(radio.nodes.get('news-title').textContent, 'Titular reciente');
    radio.setNow(1002000);
    radio.cycleNews(false);
    assert.match(radio.nodes.get('news-title').textContent, /Alexa/);
    radio.cycleNews(false);
    assert.match(radio.nodes.get('news-title').textContent, /TuneIn/);
    assert.equal(radio.isNewsFresh({ category: 'TECNOLOGÍA', title: 'Sin fecha' }), false);
});
test('a legacy news item uses its original publication date for expiry', () => {
    const radio = createRadio();
    const item = { category: 'INTERNACIONAL', title: 'Titular legado', publishedAt: new Date(1000000).toISOString() };
    assert.equal(radio.isNewsFresh(item), true);
    radio.setNow(1000000 + 28 * 3600000);
    assert.equal(radio.isNewsFresh(item), false);
    radio.acceptNews([]);
    assert.match(radio.nodes.get('news-title').textContent, /Alexa/);
});

test('a legacy Firebase batch without dates keeps the fresh local news cache', () => {
    const item = {
        category: 'TECNOLOGÍA', title: 'Titular reciente en la caché',
        publishedAt: new Date(1000000).toISOString(),
        expiresAt: new Date(2000000).toISOString()
    };
    const radio = createRadio(false, [item]);
    assert.equal(radio.nodes.get('news-title').textContent, item.title);
    radio.acceptNews([{ category: 'VENEZUELA', title: 'Titular antiguo sin fecha' }]);
    assert.equal(radio.nodes.get('news-title').textContent, item.title);
    radio.acceptNews({ key: { ...item, title: 'Titular nuevo de Firebase' } });
    assert.equal(radio.nodes.get('news-title').textContent, 'Titular nuevo de Firebase');
    radio.setNow(2000001);
    radio.acceptNews([]);
    assert.match(radio.nodes.get('news-title').textContent, /TuneIn|Alexa/);
});

test('the generated local cache displays real headlines when Firebase supplies an undated batch', () => {
    const sandbox = { window: {} };
    vm.runInNewContext(fs.readFileSync(path.join(root, 'stream-study/embarcadero/news-cache.js'), 'utf8'), sandbox);
    const cache = sandbox.window.__radioNewsCache;
    assert.ok(cache.items.length > 0);
    const radio = createRadio(false, cache.items, cache.updatedAt);
    radio.acceptNews([{ category: 'VENEZUELA', title: 'Lote antiguo sin fechas' }]);
    assert.equal(radio.nodes.get('news-title').textContent, cache.items[0].title);
    for (let i = 1; i < 6; i++) radio.cycleNews(false);
    assert.equal(radio.nodes.get('news-title').textContent, cache.items[5].title);
    radio.cycleNews(false);
    assert.match(radio.nodes.get('news-title').textContent, /TuneIn/);
});

test('legacy culture labels for Halo and PUBG are displayed as GAMING', () => {
    const radio = createRadio();
    const base = {
        category: 'CULTURA & MÚSICA',
        publishedAt: new Date(1000000).toISOString(),
        expiresAt: new Date(2000000).toISOString()
    };
    radio.acceptNews([{ ...base, title: 'Halo: Campaign Evolved añade el modo Firefight gratuito' }]);
    assert.equal(radio.nodes.get('news-cat').textContent, 'GAMING');
    radio.acceptNews([{ ...base, title: 'PUBG UNITED anuncia sus próximas finales' }]);
    assert.equal(radio.nodes.get('news-cat').textContent, 'GAMING');
    radio.acceptNews([{ ...base, title: 'Beyoncé interpreta Halo en su concierto', source: 'Jenesaispop' }]);
    assert.equal(radio.nodes.get('news-cat').textContent, 'CULTURA & MÚSICA');
});

test('the deployment can publish using existing database permissions when auth is optional', async () => {
    const radio = createRadio(true, [], 1000000, true);
    await radio.publishRadioState(radio.state(1));
    assert.equal(radio.writes.length, 1);
    assert.equal(radio.writes[0].value.trackIdx, 1);
});
