/**
 * QHAPI 书籍搜索页逻辑（从 search.py 内联抽取）
 * 依赖 /static/js/qhapi.js（QHAPI.getToken / QHAPI.authFetch）
 */
(function () {
  'use strict';

  function search() {
    var kw = document.getElementById('keyword').value.trim();
    if (!kw) return;
    var src = document.getElementById('sourceSelect').value;
    var status = document.getElementById('status');
    var results = document.getElementById('results');
    status.innerHTML = '<div class="msg info">🔍 搜索中...</div>';
    results.innerHTML = '';

    var url = '/api/v1/search?q=' + encodeURIComponent(kw) + '&source=' + src;
    QHAPI.authFetch(url, {}, { json: true }).then(function (d) {
      if (d.total === 0) {
        status.innerHTML = '<div class="msg error">❌ 未找到匹配结果</div>';
        return;
      }
      status.innerHTML = '<div class="msg success">✅ 共找到 ' + d.total + ' 个结果</div>';
      var html = '';
      d.results.forEach(function (item) {
        var size = item.size_hint ? ' (' + item.size_hint + ')' : '';
        var srcName = item.source_title || item.source;
        var author = item.author || '';
        var authorHtml = author ? ' · ' + author : '';
        html += '<div class="result">' +
          '<div><div class="result-title">' + item.title + '</div>' +
          '<div class="result-size">' + srcName + authorHtml + size + '</div></div>' +
          '<button class="btn" onclick="window.QHAPI_SEARCH.downloadBook(\'' + item.id + '\',\'' + item.source + '\',this)">下载</button>' +
          '</div>';
      });
      results.innerHTML = html;
    }).catch(function (err) {
      status.innerHTML = '<div class="msg error">❌ 请求失败: ' + err.message + '</div>';
    });
  }

  function downloadBook(bookId, source, btn) {
    btn.disabled = true;
    btn.textContent = '下载中...';
    var url = '/api/v1/books/download?book_id=' + encodeURIComponent(bookId) + '&source=' + encodeURIComponent(source);
    QHAPI.authFetch(url, {}, { json: true }).then(function (d) {
      if (d.success) {
        btn.textContent = '✅ 成功';
        btn.style.background = '#6c757d';
      } else {
        btn.textContent = '❌ ' + (d.error || '失败');
        btn.disabled = false;
      }
    }).catch(function () {
      btn.textContent = '❌ 网络错误';
      btn.disabled = false;
    });
  }

  window.QHAPI_SEARCH = { search: search, downloadBook: downloadBook };

  document.addEventListener('DOMContentLoaded', function () {
    QHAPI.initToken();
    var btn = document.getElementById('searchBtn');
    if (btn) btn.addEventListener('click', search);
    var input = document.getElementById('keyword');
    if (input) input.addEventListener('keydown', function (e) { if (e.key === 'Enter') search(); });
  });
})();
