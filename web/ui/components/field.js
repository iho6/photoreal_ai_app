(function (global) {
  "use strict";

  /**
   * Unified Photoreal text field. Always create fields through this factory.
   * @param {object} opts
   * @param {string} opts.label
   * @param {string} [opts.name]
   * @param {string} [opts.type=text]
   * @param {string} [opts.value]
   * @param {string} [opts.placeholder]
   * @param {string} [opts.hint]
   * @param {boolean} [opts.password]
   * @param {string} [opts.id]
   * @returns {{ root: HTMLElement, input: HTMLInputElement }}
   */
  function createField(opts) {
    const o = opts || {};
    const root = document.createElement("div");
    root.className = "pr-field";

    const id = o.id || (o.name ? "pr-field-" + o.name : "pr-field-" + Math.random().toString(36).slice(2, 8));
    const label = document.createElement("label");
    label.htmlFor = id;
    label.textContent = o.label || "Field";

    const input = document.createElement("input");
    input.id = id;
    input.name = o.name || id;
    input.type = o.password ? "password" : o.type || "text";
    input.autocomplete = o.password ? "off" : "on";
    if (o.value != null) input.value = o.value;
    if (o.placeholder) input.placeholder = o.placeholder;
    if (o.required) input.required = true;

    root.appendChild(label);
    root.appendChild(input);

    if (o.hint) {
      const hint = document.createElement("div");
      hint.className = "pr-hint";
      hint.textContent = o.hint;
      root.appendChild(hint);
    }

    return { root: root, input: input };
  }

  global.PhotorealUI = global.PhotorealUI || {};
  global.PhotorealUI.createField = createField;
})(window);
