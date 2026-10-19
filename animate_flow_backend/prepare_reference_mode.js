// Configure images without submitting any request.
const puppeteer = require('puppeteer');
const GR = require('./generate_refs');
const RI = require('./reference_image_step');
(async () => {
  const browser = await puppeteer.connect({browserURL:'http://127.0.0.1:'+(process.argv[3]||'9232'),defaultViewport:null});
  try {
    const url = process.argv[2];
    const pages = await browser.pages();
    const page = pages.find(p => p.url().split('?')[0] === url.split('?')[0]);
    if (!page) throw Error('Animate Flow project is not open.');
    await page.bringToFront();
    const state = await GR.setAgent(page, false);
    if (!state.ok) throw Error(state.why);
    await RI.configureReferenceImages(page, console.log);
  } finally { await browser.disconnect(); }
})().catch(error => { console.error(error.message);process.exitCode=1; });
