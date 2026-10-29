// 前端冒烟测试：推送前本地一跑，防「页面能开但功能静默坏」类回归
// 运行（playwright 走 npx 缓存，chromium 用本机已装版本）：
//   NODE_PATH="$(npm root -g 之外的 playwright 位置，见 README)" node smoke_test.mjs
// 依赖：npx playwright（浏览器已装于 %LOCALAPPDATA%/ms-playwright）；服务已在 8124 启动
import { createRequire } from 'module';
import fs from 'fs';
import os from 'os';
import path from 'path';

// playwright 不在全局 node_modules：从 npx 缓存解析
const npxCache = path.join(os.tmpdir(), '..');
let chromium;
for (const base of [
  path.join(process.env.LOCALAPPDATA || '', 'npm-cache/_npx'),
  '/tmp',
]) {
  try {
    for (const dir of fs.readdirSync(base)) {
      const p = path.join(base, dir, 'node_modules');
      if (fs.existsSync(path.join(p, 'playwright'))) {
        chromium = createRequire(path.join(p, 'playwright/'))('playwright').chromium;
        break;
      }
    }
    if (chromium) break;
  } catch (_) { /* 目录不存在跳过 */ }
}
if (!chromium) { console.error('未找到 playwright，先 npx playwright --version 安装'); process.exit(1); }

// 找本机已安装的 chromium（跳过 headless-shell 版本匹配问题）
const msPW = path.join(process.env.LOCALAPPDATA || '', 'ms-playwright');
let exe = null;
for (const dir of fs.readdirSync(msPW)) {
  const cand = path.join(msPW, dir, 'chrome-win64', 'chrome.exe');
  if (fs.existsSync(cand)) exe = cand;
}
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8124/';
const browser = await chromium.launch(exe ? { executablePath: exe } : {});
const page = await browser.newPage({ viewport: { width: 430, height: 900 } });
// 注入访问码（从 code/config.json 读，不打印到输出）
const cfgPath = path.join(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(\w:)/, '$1')), '..', 'config.json');
if (fs.existsSync(cfgPath)) {
  const cfg = JSON.parse(fs.readFileSync(cfgPath, 'utf8'));
  if (cfg.access_code) await page.addInitScript(c => localStorage.setItem('fg_token', c), cfg.access_code);
}
const errs = [];
page.on('pageerror', e => errs.push(e.message));
page.on('console', m => { if (/页面错误|error/i.test(m.text())) errs.push(m.text()); });

let failed = 0;
const check = (name, ok, detail = '') => {
  console.log((ok ? 'PASS' : 'FAIL') + ' ' + name + (detail ? '  ' + detail : ''));
  if (!ok) failed++;
};

await page.goto(BASE);
await page.waitForTimeout(2500);

// 1. 页面核心元素渲染
check('周条渲染7天', await page.locator('#strip .sday').count() === 7);
check('日期标签存在', await page.locator('#dLabel').textContent() !== '');

// 2. 月度聚合进缓存（防 ensureMonth 类静默失败）
const md = await page.evaluate(() => Object.keys(monthDays).length);
check('月度聚合缓存非空', md > 0, md + ' 天');

// 3. 静态资源 ETag/304
const r304 = await page.evaluate(async () => {
  const r = await fetch('/app.js', { headers: { 'If-None-Match': (await fetch('/app.js')).headers.get('ETag') } });
  return r.status;
});
check('静态资源ETag命中304', r304 === 304, 'status=' + r304);

// 4. API 健康与月度接口
const api = await page.evaluate(async () => {
  const h = await (await fetch('/api/health')).json();
  const m = await api('/api/month?user=beifeng&ym=' + todayStr().slice(0, 7));
  return { mock: h.mock, monthDays: (m.days || []).length };
});
check('/api/health', api.mock !== undefined);
check('/api/month 返回数据', api.monthDays >= 0, api.monthDays + ' 天');

// 5. 无 JS 运行时错误
check('无页面错误', errs.length === 0, errs.join(' | '));

await browser.close();
console.log(failed ? ('\n' + failed + ' 项失败') : '\n全部通过');
process.exit(failed ? 1 : 0);
