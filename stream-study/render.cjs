// Offline deterministic capture. DCLF WebGL renders here, never on the live VPS.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '/home/rodezel/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
(async()=>{
 const width=Number(process.env.WIDTH||1280),height=width*9/16,fps=30;
 const browser=await chromium.launch({executablePath:process.env.CHROME_BIN||'/usr/bin/google-chrome',headless:true,args:['--no-sandbox','--disable-dev-shm-usage','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 try{
 const page=await browser.newPage({viewport:{width,height},deviceScaleFactor:1});
 page.on('pageerror',e=>{throw e});
 await page.goto(pathToFileURL(path.join(__dirname,'scene.html')).href+'?capture=1');
 await page.waitForFunction(()=>window.__studyCinema);
 await page.evaluate(()=>window.__studyCinema.seek(0));
 await page.screenshot({path:path.join(__dirname,'preview.png')});
 console.log(JSON.stringify(await page.evaluate(()=>window.__studyCinema.state())));
 if(process.argv.includes('--still'))return;
 const duration=Number(process.env.DURATION||120),frames=duration*fps;
 const output=path.join(__dirname,process.env.OUTPUT||'yaire-study-1080p.mp4');
 const enc=spawn('ffmpeg',['-y','-hide_banner','-loglevel','error','-f','image2pipe','-framerate',String(fps),'-vcodec','mjpeg','-i','pipe:0','-an','-vf','scale=1920:1080:flags=lanczos','-c:v','libx264','-preset','fast','-crf','19','-pix_fmt','yuv420p','-r',String(fps),'-g','60','-movflags','+faststart',output],{stdio:['pipe','inherit','inherit']});
 const done=new Promise((resolve,reject)=>{enc.on('error',reject);enc.on('close',c=>c===0?resolve():reject(Error('FFmpeg '+c)))});
 for(let i=0;i<frames;i++){
 const data=await page.evaluate(t=>{window.__studyCinema.seek(t);return document.querySelector('canvas').toDataURL('image/jpeg',.94).split(',')[1]},i/fps);
 const jpg=Buffer.from(data,'base64');
 if(!enc.stdin.write(jpg))await new Promise(r=>enc.stdin.once('drain',r));
 if(i%150===0)console.log(`${i}/${frames}`);
 }
 enc.stdin.end();await done;
 fs.writeFileSync(path.join(__dirname,'render.json'),JSON.stringify({renderWidth:width,renderHeight:height,width:1920,height:1080,fps,duration,frames,output,source:'DCLF WebGL procedural scene'},null,2));
 console.log('COMPLETE '+output);
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
