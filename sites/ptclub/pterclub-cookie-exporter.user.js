// ==UserScript==
// @name         PTerClub Cookie Exporter
// @namespace    https://pterclub.net
// @version      1.0
// @description  One-click export pterclub cookies for CLI tool
// @author       Claude
// @match        https://pterclub.net/*
// @grant        GM_setClipboard
// @grant        GM_notification
// ==/UserScript==

(function() {
  'use strict';

  // 添加导出按钮到导航栏
  function addButton() {
    const nav = document.querySelector('#nav_block, .navbar, .head');
    if (!nav) return setTimeout(addButton, 500);

    const btn = document.createElement('button');
    btn.textContent = '🍪 Export';
    btn.title = '导出 Cookie 供 CLI 工具使用';
    btn.style.cssText = `
      position: fixed; bottom: 20px; right: 20px; z-index: 9999;
      padding: 8px 16px; background: #16213e; color: #7ecb76;
      border: 1px solid #7ecb76; border-radius: 6px; cursor: pointer;
      font-size: 13px; font-family: monospace;
    `;

    btn.onclick = exportCookies;
    document.body.appendChild(btn);
  }

  function exportCookies() {
    const pairs = document.cookie.split('; ').filter(Boolean);
    const cookies = pairs.map(p => {
      const idx = p.indexOf('=');
      return {
        name: p.substring(0, idx),
        value: p.substring(idx + 1),
        domain: 'pterclub.net',
        path: '/',
        secure: true,
      };
    });

    if (cookies.length === 0) {
      alert('No cookies found. Please login first.');
      return;
    }

    // 检查是否已登录
    const loggedIn = document.querySelector('a[href*="usercp.php"]')
                  || document.body.innerText.includes('控制面板');
    if (!loggedIn) {
      alert('Not logged in. Please login to pterclub.net first.');
      return;
    }

    const json = JSON.stringify({
      saved_at: new Date().toISOString(),
      cookies: cookies,
    }, null, 2);

    GM_setClipboard(json, 'text');
    GM_notification({
      text: `Exported ${cookies.length} cookies to clipboard!`,
      title: 'PTerClub Cookie Exporter',
      timeout: 3000,
    });

    // 视觉反馈
    const btn = document.querySelector('button');
    if (btn) {
      const orig = btn.textContent;
      btn.textContent = '✅ Copied!';
      btn.style.color = '#fff';
      setTimeout(() => {
        btn.textContent = orig;
        btn.style.color = '#7ecb76';
      }, 2000);
    }
  }

  // 页面加载完成后添加按钮
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', addButton);
  } else {
    addButton();
  }
})();
