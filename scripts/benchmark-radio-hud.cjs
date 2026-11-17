'use strict';
// Run in a temporary copy on the VPS. Uses its own display, browser profile and HTTP port.
const { spawn, spawnSync } = require('node:child_process');
const { WebSocket } = require('undici');
const fs = require('node:fs');
const path = require('node:path');
const root = process.cwd();
const audioDirectory = path.join(root, 'radio', 'stream in youtube');
const audioFixture = path.join(audioDirectory, fs.readdirSync(audioDirectory).find(file => file.endsWith('.mp3')));
const seconds = Number(process.env.BENCH_SECONDS || 120);
const children = [];
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
function launch(command, args, options = {}) {
    const child = spawn(command, args, { stdio: 'ignore', ...options });
    children.push(child);
    return child;
}
async function connect(url) {
    const ws = new WebSocket(url);
    await new Promise((resolve, reject) => {
        ws.addEventListener('open', resolve, { once: true });
        ws.addEventListener('error', reject, { once: true });
    });
    let sequence = 0;
    const pending = new Map();
    ws.addEventListener('message', event => {
        const message = JSON.parse(event.data);
        const request = pending.get(message.id);
        if (!request) return;
        pending.delete(message.id);
        clearTimeout(request.timer);
        if (message.error) request.reject(Error(JSON.stringify(message.error)));
        else request.resolve(message.result);
    });
    return {
        call(method, params = {}) {
            return new Promise((resolve, reject) => {
                const id = ++sequence;
                const timer = setTimeout(() => { pending.delete(id); reject(Error('CDP timeout: ' + method)); }, 15000);
                pending.set(id, { resolve, reject, timer });
                ws.send(JSON.stringify({ id, method, params }));
            });
        },
        close() { ws.close(); }
    };
}
async function run() {
    let page;
    let browser;
    let encoder;
    let encoderText = '';
    const errors = [];
    const samples = [];
    try {
        launch('python3', ['-m', 'http.server', '18768', '--bind', '127.0.0.1', '--directory', root]);
        launch('Xvfb', [':98', '-screen', '0', '1920x1080x24', '-nolisten', 'tcp', '+extension', 'GLX', '+render', '-noreset']);
        await wait(750);
        launch('openbox', [], {env: {...process.env, DISPLAY: ':98'}});
        await wait(2000);
        launch('google-chrome', [
            '--no-sandbox', '--disable-dev-shm-usage', '--no-first-run', '--no-default-browser-check',
            '--kiosk', '--window-size=1920,1080', '--window-position=0,0', '--force-device-scale-factor=1',
            '--autoplay-policy=no-user-gesture-required', '--mute-audio', '--disable-background-timer-throttling',
            '--disable-renderer-backgrounding', '--disable-backgrounding-occluded-windows',
            '--disable-gpu', '--disable-software-rasterizer',
            '--user-data-dir=' + path.join(root, 'chrome-profile-' + Date.now()),
            '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=19227',
            'http://127.0.0.1:18768/stream-study/embarcadero/hud.html?stream'
        ], { env: { ...process.env, DISPLAY: ':98', LP_NUM_THREADS: '2', OMP_NUM_THREADS: '2' } });
        let tabs;
        for (let attempt = 0; attempt < 60; attempt++) {
            try {
                tabs = await (await fetch('http://127.0.0.1:19227/json')).json();
                if (tabs.some(tab => tab.type === 'page')) break;
            } catch (_) {}
            await wait(250);
        }
        if (!tabs) throw Error('Test Chrome did not start');
        page = await connect(tabs.find(tab => tab.type === 'page').webSocketDebuggerUrl);
        const version = await (await fetch('http://127.0.0.1:19227/json/version')).json();
        browser = await connect(version.webSocketDebuggerUrl);
        await page.call('Runtime.enable');
        const evaluate = async expression => {
            const result = await page.call('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
            if (result.exceptionDetails) throw Error(JSON.stringify(result.exceptionDetails));
            return result.result.value;
        };
        for (let attempt = 0; attempt < 60; attempt++) {
            if (await evaluate('document.querySelector("video")?.readyState>=3')) break;
            await wait(500);
        }
        await evaluate('document.querySelector("video").play().then(()=>true)');
        await wait(10000);
        const measure = () => evaluate(`(()=>{
            const video=document.querySelector("video"),q=video.getVideoPlaybackQuality(),audio=document.querySelector("audio");
            return {wallMs:Date.now(),width:innerWidth,height:innerHeight,videoWidth:video.videoWidth,videoHeight:video.videoHeight,
                time:video.currentTime,paused:video.paused,total:q.totalVideoFrames,dropped:q.droppedVideoFrames,
                song:document.getElementById("music-title").textContent,audioPaused:audio.paused,audioTime:audio.currentTime,
                audioError:audio.error?.code||null,news:document.getElementById("news-title").textContent,
                font:document.fonts.check('16px "Plus Jakarta Sans"')};
        })()`);
        encoder = launch('ffmpeg', [
            '-hide_banner', '-nostdin', '-f', 'x11grab', '-draw_mouse', '0', '-video_size', '1920x1080',
            '-framerate', '30', '-thread_queue_size', '1024', '-i', ':98.0',
            '-stream_loop', '-1', '-re', '-i', audioFixture, '-t', String(seconds + 30),
            '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency', '-threads', '2',
            '-pix_fmt', 'yuv420p', '-profile:v', 'high', '-level', '4.1', '-r', '30',
            '-g', '60', '-keyint_min', '60', '-sc_threshold', '0',
            '-b:v', '4500k', '-minrate', '4500k', '-maxrate', '4500k', '-bufsize', '4500k',
            '-c:a', 'aac', '-b:a', '192k', '-ar', '44100', '-f', 'null', '-',
            '-progress', 'pipe:1', '-nostats'
        ], { stdio: ['ignore', 'pipe', 'pipe'] });
        encoder.stdout.on('data', chunk => { encoderText += chunk.toString(); });
        encoder.stderr.on('data', chunk => { if (errors.length < 20) errors.push(chunk.toString().slice(-800)); });
        const encoderExit = new Promise(resolve => encoder.once('exit', resolve));
        let exitCode;
        const completion = encoderExit.then(code => { exitCode = code; });
        await wait(30000);
        const cpuStart = await browser.call('SystemInfo.getProcessInfo');
        const start = await measure();
        const progressAtStart = encoderText;
        await evaluate(`window.__frameTiming={last:0,maxGap:0,over100:0,count:0};
            function recordFrame(now){const f=window.__frameTiming;if(f.last){const gap=now-f.last;f.maxGap=Math.max(f.maxGap,gap);if(gap>100)f.over100++;}f.last=now;f.count++;document.querySelector('video').requestVideoFrameCallback(recordFrame);}
            document.querySelector('video').requestVideoFrameCallback(recordFrame);true`);
        console.log('START ' + JSON.stringify(start));
        for (let elapsed = 0; elapsed < seconds; elapsed += 10) {
            await wait(10000);
            const sample = await measure();
            samples.push(sample);
            console.log('SAMPLE ' + JSON.stringify(sample));
        }
        await Promise.race([completion, wait(15000)]);
        if (exitCode === undefined) { encoder.kill('SIGTERM'); await completion; }
        const end = await measure();
        const cpuEnd = await browser.call('SystemInfo.getProcessInfo');
        const sumCpu = data => data.processInfo.reduce((total, process) => total + process.cpuTime, 0);
        const deltaSeconds = (end.wallMs - start.wallMs) / 1000;
        const frames = end.total - start.total;
        const dropped = end.dropped - start.dropped;
        const encodedFrames = Number([...encoderText.matchAll(/^frame=(\d+)/gm)].at(-1)?.[1]);
        const frameTiming = await evaluate('window.__frameTiming');
        const lastCount = (text, key) => Number([...text.matchAll(new RegExp('^' + key + '=(\\d+)', 'gm'))].at(-1)?.[1] || 0);
        const report = {
            frameTiming,
            captureDuplicates: lastCount(encoderText, 'dup_frames') - lastCount(progressAtStart, 'dup_frames'),
            captureDrops: lastCount(encoderText, 'drop_frames') - lastCount(progressAtStart, 'drop_frames'),
            encoderPreset: 'ultrafast', gpu: false,
            seconds: deltaSeconds, start, end, samples, encodedFrames, encoderExit: exitCode,
            presentedFps: (frames - dropped) / deltaSeconds, droppedFrames: dropped,
            decodedFrames: frames, browserCpuPercentOneCore: (sumCpu(cpuEnd) - sumCpu(cpuStart)) / deltaSeconds * 100,
            encoderProgress: encoderText, encoderLog: errors,
            liveService: spawnSync('systemctl', ['is-active', 'radio28e'], { encoding: 'utf8' }).stdout.trim()
        };
        // Callbacks run on the main thread and may lag already presented video frames.
        // https://wicg.github.io/video-rvfc/ — use playback and capture counters for acceptance.
        report.pass = exitCode === 0 && start.width === 1920 && start.height === 1080 &&
            !end.paused && dropped === 0 && report.presentedFps >= 29.8 &&
            report.captureDuplicates === 0 && report.captureDrops === 0 && encodedFrames >= (seconds + 30) * 30 - 2 &&
            samples.every(sample => !sample.audioPaused && !sample.audioError);
        fs.writeFileSync(path.join(root, 'benchmark.json'), JSON.stringify(report, null, 2));
        console.log('RESULT ' + JSON.stringify({ ...report, samples: undefined, encoderProgress: undefined, encoderLog: undefined }));
    } finally {
        page?.close();
        browser?.close();
        for (const child of children.reverse()) child.kill('SIGTERM');
    }
}
run().catch(error => { console.error(error); process.exitCode = 1; });
