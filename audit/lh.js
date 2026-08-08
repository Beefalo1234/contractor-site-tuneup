#!/usr/bin/env node
// Contractor Site Tune-Up — local Lighthouse speed check (free, no API).
// Runs a mobile-emulated Lighthouse audit against `url` using Edge headless
// and prints a compact JSON with the metrics the audit pipeline needs.
//
// Usage: node lh.js https://example.com
'use strict';

const lighthouse = require('lighthouse').default || require('lighthouse');
const chromeLauncher = require('chrome-launcher');

async function main() {
  const url = process.argv[2];
  const isDesktop = process.argv[3] === 'desktop';
  if (!url) {
    console.error('usage: node lh.js <url> [desktop]');
    process.exit(2);
  }
  let chrome;
  const candidates = [
    { chromePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' },
    { chromePath: 'C:/Program Files/Microsoft/Edge/Application/msedge.exe' },
    { chromePath: 'C:/Users/Gray/AppData/Local/Microsoft/Edge/Application/msedge.exe' },
    { channel: 'msedge' },
    { channel: 'chrome' },
  ];
  let lastErr = null;
  for (const opts of candidates) {
    try {
      chrome = await chromeLauncher.launch(Object.assign({
        headless: true,
        logLevel: 'silent',
      }, opts));
      break;
    } catch (e) {
      lastErr = e;
      chrome = null;
    }
  }
  if (!chrome) {
    console.error('LH_ERROR: no usable browser: ' + (lastErr && lastErr.message));
    process.exit(1);
  }

  try {
    const lhOpts = {
      port: chrome.port,
      output: 'json',
      onlyCategories: ['performance', 'accessibility'],
      logLevel: 'silent',
      maxWaitForLoad: 60000,
    };
    if (isDesktop) {
      lhOpts.config = require('lighthouse').desktopConfig;
    }
    const { lhr } = await lighthouse(url, lhOpts);
    const audits = (lhr && lhr.audits) || {};
    const cat = (name) => lhr && lhr.categories[name] ? lhr.categories[name].score : null;
    const auditVal = (name) => audits[name] ? audits[name].displayValue || null : null;
    const auditScore = (name) => audits[name] && typeof audits[name].score === 'number'
      ? audits[name].score : null;

    const perf = cat('performance');
    const imgAlt = audits['image-alt'] || {};
    const tap = audits['tap-targets'] || {};

    console.log(JSON.stringify({
      ok: true,
      perf_score: perf === null ? null : Math.round(perf * 100),
      lcp: auditVal('largest-contentful-paint'),
      cls: auditVal('cumulative-layout-shift'),
      tbt: auditVal('total-blocking-time'),
      page_weight: auditVal('total-byte-weight'),
      tap_score: auditScore('tap-targets'),
      tap_failing: tap.details && tap.details.items ? tap.details.items.length : null,
      img_total: imgAlt.details && imgAlt.details.items ? imgAlt.details.items.length : null,
      img_missing_alt: imgAlt.score !== null && imgAlt.score < 1
        ? ((imgAlt.details && imgAlt.details.items) || []).filter((i) => i.node && i.node.selector).length
        : 0,
    }));
  } catch (err) {
    console.error('LH_ERROR: ' + (err && err.message ? err.message : String(err)));
    process.exit(1);
  } finally {
    if (chrome) { try { await chrome.kill(); } catch (_) {} }
  }
}

main();
