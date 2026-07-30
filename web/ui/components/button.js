(function (global) {
  "use strict";

  /**
   * Unified Photoreal button. Always create buttons through this factory.
   * @param {object} opts
   * @param {string} opts.label
   * @param {string} [opts.type=button]
   * @param {function} [opts.onClick]
   * @param {boolean} [opts.disabled]
   * @param {string} [opts.id]
   * @returns {HTMLButtonElement}
   */
  function createButton(opts) {
    const o = opts || {};
    const btn = document.createElement("button");
    btn.type = o.type || "button";
    btn.className = "pr-btn";
    btn.textContent = o.label || "Button";
    if (o.id) btn.id = o.id;
    if (o.disabled) btn.disabled = true;
    if (typeof o.onClick === "function") {
      btn.addEventListener("click", o.onClick);
    }
    return btn;
  }

  function setButtonBusy(btn, busy, busyLabel) {
    if (!btn) return;
    if (busy) {
      btn.dataset.label = btn.textContent;
      if (busyLabel) btn.textContent = busyLabel;
      btn.disabled = true;
    } else {
      if (btn.dataset.label) btn.textContent = btn.dataset.label;
      btn.disabled = false;
    }
  }

  global.PhotorealUI = global.PhotorealUI || {};
  global.PhotorealUI.createButton = createButton;
  global.PhotorealUI.setButtonBusy = setButtonBusy;
})(window);
