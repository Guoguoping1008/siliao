
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1280, height: 900 } });
  const errs = [];
  p.on('console', m => { if (m.type() === 'error') errs.push(m.text().slice(0,120)); });
  // 线上首页
  await p.goto('https://siliao-web.pages.dev/', { waitUntil: 'networkidle' });
  await p.waitForTimeout(1500);
  const info = await p.evaluate(() => {
    const styled = [...document.querySelectorAll('*')].filter(e => {
      const s = getComputedStyle(e);
      return s.backgroundColor !== 'rgba(0, 0, 0, 0)' || s.borderRadius !== '0px';
    }).length;
    return { styled, total: document.querySelectorAll('*').length,
             rules: [...document.styleSheets].map(s=>{try{return s.cssRules.length}catch(e){return 0}}).reduce((a,b)=>a+b,0) };
  });
  console.log('线上首页:', JSON.stringify(info));
  await p.screenshot({ path: 'E:/workspace/siliao/_live_home.png' });

  // 线上搜索(走真 Worker)
  await p.goto('https://siliao-web.pages.dev/search?q=' + encodeURIComponent('新兽药注册办法'), { waitUntil: 'networkidle' });
  await p.waitForTimeout(2500);
  const s2 = await p.evaluate(() => {
    const txt = document.body.innerText;
    const hits = [...document.querySelectorAll('[class*="line-clamp"], p')].map(e=>e.innerText).filter(t=>t && t.length>20);
    return { hasMarkdownHash: /###|####/.test(txt), sample: hits[0] ? hits[0].slice(0,120) : null,
             text: txt.slice(0,300) };
  });
  console.log('线上搜索:', JSON.stringify(s2));
  await p.screenshot({ path: 'E:/workspace/siliao/_live_search.png' });
  console.log('console errors:', errs.length ? errs.slice(0,3) : 'none');
  await b.close();
})();
