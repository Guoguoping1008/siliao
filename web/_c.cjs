
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport:{width:1440,height:1000} });
  const errs=[]; p.on('pageerror',e=>errs.push(e.message.slice(0,150)));
  await p.goto('http://127.0.0.1:5173/#library',{waitUntil:'networkidle'});
  await p.waitForTimeout(1200);
  await p.locator('[role=tab]', { hasText: '目录' }).click();
  await p.waitForTimeout(800);
  // 展开「一、法规」
  await p.locator('button', { hasText: '一、法规' }).first().click();
  await p.waitForTimeout(400);
  // 展开「（本类无子类）」
  await p.locator('button', { hasText: '本类无子类' }).first().click();
  await p.waitForTimeout(600);
  const info = await p.evaluate(()=>({
    links: document.querySelectorAll('a[href^="/doc/"]').length,
    first: document.querySelector('a[href^="/doc/"]')?.getAttribute('href'),
    notCollected: document.body.innerText.includes('未收录'),
  }));
  console.log('展开后:', JSON.stringify(info));
  await p.screenshot({path:'E:/workspace/siliao/_cat2.png'});
  // 点一个链接看能不能跳转
  if (info.links > 0) {
    await p.locator('a[href^="/doc/"]').first().click();
    await p.waitForTimeout(1500);
    console.log('跳转后 URL:', p.url());
    console.log('标题:', await p.locator('h1').first().innerText());
  }
  console.log('errors:', errs.length?errs:'none');
  await b.close();
})();
