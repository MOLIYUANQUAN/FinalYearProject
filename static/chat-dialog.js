/**
 * Friday 对话框视图层（零依赖）。
 * 交互模式参考开源方案，避免重复造轮子：
 * - deftio/quikchat（气泡对齐、打字指示、流式追加、自动滚底）
 * - anantrp/chat-widget（轻量消息列表 + 底部输入区）
 */
(function (global) {
  "use strict";

  /** @type {HTMLElement | null} */
  let logEl = null;

  function escapeHtml(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /** 模型偶尔仍会输出 Markdown：只做最小渲染，其余按纯文本显示 */
  function render(text) {
    return escapeHtml(text || "")
      .replace(/^#{1,6}\s+/gm, "")
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/^(\s*)[-*•]\s+/gm, "$1· ")
      .replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>');
  }

  function scrollDown() {
    if (!logEl) return;
    const gap = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight;
    const stick = gap < 120;
    if (stick) {
      try {
        logEl.scrollTo({ top: logEl.scrollHeight, behavior: "smooth" });
      } catch (e) {
        logEl.scrollTop = logEl.scrollHeight;
      }
    }
  }

  function bindLog(el) {
    logEl = el;
  }

  /**
   * @param {"user"|"bot"|"error"} role
   * @param {string | null | undefined} text
   */
  function addMessage(role, text) {
    if (!logEl) throw new Error("对话框尚未绑定消息区。");
    const div = document.createElement("div");
    div.className = "msg " + role;
    div.setAttribute("role", role === "user" ? "article" : "article");
    if (text != null) div.innerHTML = render(text);
    logEl.appendChild(div);
    scrollDown();
    return div;
  }

  function showTyping(div, hint) {
    div.innerHTML =
      '<span class="typing" aria-label="正在输入"><i></i><i></i><i></i></span>' +
      (hint ? '<span class="hint">' + escapeHtml(hint) + "</span>" : "");
  }

  function appendFresh(target, chunk) {
    if (target.querySelector(".typing")) target.textContent = "";
    const span = document.createElement("span");
    span.className = "fresh";
    span.textContent = chunk;
    target.appendChild(span);
  }

  global.FridayChat = {
    bindLog,
    escapeHtml,
    render,
    scrollDown,
    addMessage,
    showTyping,
    appendFresh,
  };
})(window);
