// ==UserScript==
// @name         PT Cookie Sender (四站 → 服务器)
// @namespace    https://github.com/kun/pt
// @version      1.0
// @description  进入 azusa/tjupt/u2.dmhy/pterclub 任意 PT 站, 一键把该站 cookie 发送到服务器保存(供自动签到使用)
// @author       kun
// @match        https://azusa.wiki/*
// @match        https://tjupt.org/*
// @match        https://u2.dmhy.org/*
// @match        https://pterclub.net/*
// @grant        GM_xmlhttpRequest
// @grant        GM_notification
// @run-at       document-idle
// ==/UserScript==

// ============================================================
// 配置区: 安装后必改
// ============================================================
const SERVER_URL = 'http://39.101.137.195:8766/api/cookie';  // 公网 frp 入口
const TOKEN = 'PASTE_COOKIE_SERVER_TOKEN_HERE';              // 服务器 deploy/install.sh 输出的值

// 站点域名 → site key(与服务端 common/sites.py 注册表一致)
const SITE_MAP = {
  'azusa.wiki': 'azusa',
  'tjupt.org': 'tjupt',
  'u2.dmhy.org': 'dmhy',
  'pterclub.net': 'ptclub',
};

// 每站关键认证 cookie(发送前检查缺失, 通常是 HttpOnly 读不到)
const CRITICAL_COOKIES = {
  azusa: ['c_secure_uid', 'c_session_token'],
  tjupt: ['access_token'],
  dmhy: ['nexusphp_u2'],
  ptclub: ['c_secure_uid', 'c_secure_pass'],
};

// ============================================================
(function () {
  'use strict';

  const site = SITE_MAP[location.hostname];
  if (!site) return;  // 防御: 不在四站内

  function isLoggedIn() {
    return document.querySelector('a[href*="usercp.php"]')
        || document.querySelector('a[href*="userdetails"]')
        || document.body.innerText.includes('控制面板')
        || document.body.innerText.includes('退出');
  }

  function collectCookies() {
    return document.cookie.split('; ').filter(Boolean).map(p => {
      const idx = p.indexOf('=');
      return {
        name: p.substring(0, idx),
        value: p.substring(idx + 1),
        domain: location.hostname,
        path: '/',
        secure: location.protocol === 'https:',
      };
    });
  }

  function sendCookies(btn) {
    if (!isLoggedIn()) {
      alert('未检测到登录状态, 请先登录 ' + location.hostname);
      return;
    }
    const cookies = collectCookies();
    if (cookies.length === 0) {
      alert('未获取到 cookie, 请确认已登录');
      return;
    }

    // 关键 cookie 缺失检查(HttpOnly 读不到, 警告但允许发送)
    const missing = CRITICAL_COOKIES[site].filter(
      n => !cookies.some(c => c.name === n));
    if (missing.length > 0) {
      GM_notification({
        text: '关键 cookie 缺失: ' + missing.join(', ') + ' (可能是 HttpOnly)',
        title: site + ' cookie 发送警告',
        timeout: 5000,
      });
    }

    setBtn(btn, '📤 发送中...', '#ffd166');
    GM_xmlhttpRequest({
      method: 'POST',
      url: SERVER_URL,
      timeout: 15000,
      headers: { 'Content-Type': 'application/json', 'X-Auth-Token': TOKEN },
      data: JSON.stringify({
        site: site,
        saved_at: new Date().toISOString(),
        cookies: cookies,
      }),
      onload: (resp) => {
        let data = {};
        try { data = JSON.parse(resp.responseText); } catch (e) {}
        if (resp.status === 200 && data.ok) {
          let msg = `✅ 已保存 ${data.saved} 条 cookie`;
          if (data.warning) msg += '\n⚠ ' + data.warning;
          GM_notification({ text: msg, title: `${site} cookie 发送成功`, timeout: 4000 });
          setBtn(btn, '✅ 已发送', '#7ecb76');
        } else if (resp.status === 403) {
          GM_notification({ text: 'token 错误, 请检查脚本头部 TOKEN 常量', title: '发送失败', timeout: 5000 });
          setBtn(btn, '❌ token 错误', '#ff6b6b');
        } else if (resp.status === 400) {
          GM_notification({ text: '服务器拒绝: ' + (data.error || resp.responseText), title: '发送失败', timeout: 5000 });
          setBtn(btn, '❌ 请求被拒', '#ff6b6b');
        } else {
          GM_notification({ text: `服务器异常 (HTTP ${resp.status})`, title: '发送失败', timeout: 5000 });
          setBtn(btn, '❌ 发送失败', '#ff6b6b');
        }
      },
      onerror: () => {
        GM_notification({ text: '无法连接服务器 (frp 未生效或服务未启动?)', title: '发送失败', timeout: 5000 });
        setBtn(btn, '❌ 无法连接', '#ff6b6b');
      },
      ontimeout: () => {
        GM_notification({ text: '连接服务器超时', title: '发送失败', timeout: 5000 });
        setBtn(btn, '❌ 超时', '#ff6b6b');
      },
    });
  }

  function setBtn(btn, text, color) {
    btn.textContent = text;
    btn.style.color = color || '#7ecb76';
    setTimeout(() => { btn.textContent = '🍪 发送 Cookie'; btn.style.color = '#7ecb76'; }, 3000);
  }

  function addButton() {
    if (document.querySelector('#pt-cookie-sender-btn')) return;
    const btn = document.createElement('button');
    btn.id = 'pt-cookie-sender-btn';
    btn.textContent = '🍪 发送 Cookie';
    btn.title = `把 ${location.hostname} 的 cookie 发送到服务器保存`;
    btn.style.cssText = `
      position: fixed; bottom: 20px; right: 20px; z-index: 9999;
      padding: 8px 16px; background: #16213e; color: #7ecb76;
      border: 1px solid #7ecb76; border-radius: 6px; cursor: pointer;
      font-size: 13px; font-family: monospace;
    `;
    btn.onclick = () => sendCookies(btn);
    document.body.appendChild(btn);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', addButton);
  } else {
    addButton();
  }
})();
