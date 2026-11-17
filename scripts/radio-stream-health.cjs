'use strict';
const fs = require('node:fs');
const WebSocket = globalThis.WebSocket || require('undici').WebSocket;
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

async function connect(url) {
    const socket = new WebSocket(url);
    await new Promise((resolve, reject) => {
        socket.addEventListener('open', resolve, { once: true });
        socket.addEventListener('error', reject, { once: true });
    });
    let sequence = 0;
    const pending = new Map();
    socket.addEventListener('message', event => {
        const message = JSON.parse(event.data);
        const request = pending.get(message.id);
        if (!request) return;
        clearTimeout(request.timer);
        pending.delete(message.id);
        if (message.error) request.reject(Error(JSON.stringify(message.error)));
        else request.resolve(message.result);
    });
    return {
        call(method, params) {
            return new Promise((resolve, reject) => {
                const id = ++sequence;
                const timer = setTimeout(() => {
                    pending.delete(id);
                    reject(Error('Tiempo de espera agotado: ' + method));
                }, 10000);
                pending.set(id, { resolve, reject, timer });
                socket.send(JSON.stringify({ id, method, params }));
            });
        },
        close() { socket.close(); }
    };
}

async function snapshot(connection) {
    const response = await connection.call('Runtime.evaluate', {
        returnByValue: true,
        expression: `(() => {
            const video = document.querySelector('video');
            const audio = document.querySelector('audio');
            const quality = video?.getVideoPlaybackQuality();
            return {
                at: Date.now(), width: innerWidth, height: innerHeight,
                videoWidth: video?.videoWidth, videoHeight: video?.videoHeight,
                videoTime: video?.currentTime, videoReady: video?.readyState,
                videoPaused: video?.paused, total: quality?.totalVideoFrames,
                dropped: quality?.droppedVideoFrames,
                audioTime: audio?.currentTime, audioPaused: audio?.paused,
                audioError: audio?.error?.code || null,
                song: document.getElementById('music-title')?.textContent,
                artist: document.getElementById('music-artist')?.textContent,
                news: document.getElementById('news-title')?.textContent,
                category: document.getElementById('news-cat')?.textContent,
                clock: document.getElementById('live-clock')?.textContent,
                weather: document.getElementById('live-weather')?.textContent,
                status: document.getElementById('radio-status')?.textContent
            };
        })()`
    });
    if (response.exceptionDetails) throw Error('No se pudo consultar el HUD');
    return response.result.value;
}

function ready(state) {
    return state.width === 1920 && state.height === 1080 && state.videoReady >= 3 &&
        state.videoPaused === false && state.audioPaused === false && !state.audioError &&
        Boolean(state.song && state.song !== 'Radio 28E') && Boolean(state.news);
}

async function run() {
    let connection;
    try {
        for (let attempt = 0; attempt < 90; attempt++) {
            try {
                if (!connection) {
                    const response = await fetch('http://127.0.0.1:19222/json', { signal: AbortSignal.timeout(2000) });
                    const tabs = await response.json();
                    const page = tabs.find(tab => tab.type === 'page' && tab.url.includes('/embarcadero/hud.html'));
                    if (page) connection = await connect(page.webSocketDebuggerUrl);
                }
                if (connection) {
                    const state = await snapshot(connection);
                    if (ready(state)) break;
                }
            } catch (error) {
                if (attempt === 89) throw error;
            }
            await wait(1000);
        }
        if (!connection) throw Error('Chrome no está disponible');
        const start = await snapshot(connection);
        if (!ready(start)) throw Error('El HUD no está listo: ' + JSON.stringify(start));
        if (!process.argv.includes('--monitor')) {
            console.log(JSON.stringify(start));
            return;
        }
        const seconds = Number(process.env.MONITOR_SECONDS || 180);
        const samples = [start];
        for (let elapsed = 0; elapsed < seconds; elapsed += 10) {
            await wait(10000);
            const state = await snapshot(connection);
            samples.push(state);
            console.log(JSON.stringify(state));
        }
        const end = samples.at(-1);
        const duration = (end.at - start.at) / 1000;
        const frames = end.total - start.total;
        const dropped = end.dropped - start.dropped;
        const report = {
            duration, frames, dropped,
            presentedFps: (frames - dropped) / duration,
            samples,
            pass: dropped === 0 && (frames - dropped) / duration >= 29.8 &&
                samples.every(state => ready(state) && !state.status)
        };
        const output = process.env.MONITOR_REPORT;
        if (output) fs.writeFileSync(output, JSON.stringify(report, null, 2));
        console.log('RESULT ' + JSON.stringify({ ...report, samples: undefined }));
        if (!report.pass) process.exitCode = 1;
    } finally {
        connection?.close();
    }
}
run().catch(error => { console.error(error.message); process.exitCode = 1; });
