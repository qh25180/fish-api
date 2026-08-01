/**
 * QHAPI 前端通用工具
 * - token 管理：URL ?token= → sessionStorage + Cookie；页面间跳转走 Cookie，URL 干净
 * - authFetch：统一带 Authorization: Bearer 头
 */
(function (global) {
  'use strict';

  var COOKIE_NAME = 'qhapi_token';

  // 读取 token（优先后端注入的 QHAPI_CONFIG，其次 sessionStorage）
  function getToken() {
    if (global.QHAPI_CONFIG && global.QHAPI_CONFIG.token) {
      return global.QHAPI_CONFIG.token;
    }
    try {
      return sessionStorage.getItem('qhapi_token') || '';
    } catch (e) {
      return '';
    }
  }

  // 保存 token 到 sessionStorage
  function saveToken(token) {
    if (!token) return;
    try {
      sessionStorage.setItem('qhapi_token', token);
    } catch (e) { /* ignore */ }
  }

  // 写 Cookie（页面间共享，替代 URL ?token=）
  function saveTokenCookie(token) {
    if (!token) return;
    try {
      document.cookie = COOKIE_NAME + '=' + encodeURIComponent(token) +
        '; path=/; SameSite=Lax';
    } catch (e) { /* ignore */ }
  }

  // 读 Cookie
  function getTokenFromCookie() {
    try {
      var m = document.cookie.match(new RegExp('(?:^|;\\\\s*)' + COOKIE_NAME + '=([^;]*)'));
      return m ? decodeURIComponent(m[1]) : '';
    } catch (e) {
      return '';
    }
  }

  /**
   * 初始化 token：
   * 1. 从 URL ?token= 提取 → 存 sessionStorage + Cookie，并清理 URL
   * 2. 从 Cookie 恢复（页面间跳转后）
   */
  function initToken() {
    try {
      var params = new URLSearchParams(location.search);
      var t = params.get('token');
      if (t) {
        saveToken(t);
        saveTokenCookie(t);
        // 清理 URL：去掉 ?token= 参数，保持地址栏干净
        params.delete('token');
        var qs = params.toString();
        var newUrl = location.pathname + (qs ? '?' + qs : '') + location.hash;
        history.replaceState(null, '', newUrl);
      } else {
        var c = getTokenFromCookie();
        if (c) saveToken(c);
      }
    } catch (e) { /* ignore */ }
  }

  /**
   * 带 Bearer 认证的 fetch。
   * @param {string|URL} url
   * @param {object} options fetch 选项（method/headers/body 等）
   * @param {object} cfg { json: true 自动解析 JSON }
   */
  async function authFetch(url, options, cfg) {
    var opts = options || {};
    var headers = Object.assign({}, opts.headers || {});
    var token = getToken();
    if (token) {
      headers['Authorization'] = 'Bearer ' + token;
    }
    var resp = await fetch(url, Object.assign({}, opts, { headers }));
    if (cfg && cfg.json) {
      return resp.json();
    }
    return resp;
  }

  // 导出
  global.QHAPI = {
    getToken: getToken,
    saveToken: saveToken,
    saveTokenCookie: saveTokenCookie,
    getTokenFromCookie: getTokenFromCookie,
    initToken: initToken,
    authFetch: authFetch,
  };
})(window);
