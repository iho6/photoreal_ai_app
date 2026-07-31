(function (global) {
  "use strict";

  var EYE_OPEN =
    '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></svg>';
  var EYE_OFF =
    '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 3l18 18"/><path d="M10.6 10.6a2 2 0 0 0 2.8 2.8"/><path d="M9.9 5.1A10.5 10.5 0 0 1 12 5c6.5 0 10 7 10 7a17.6 17.6 0 0 1-3.2 4.1"/><path d="M6.1 6.1C3.9 7.7 2 12 2 12s3.5 7 10 7c1.4 0 2.7-.3 3.9-.8"/></svg>';

  /**
   * Unified Photoreal text field. Always create fields through this factory.
   * @param {object} opts
   * @param {string} [opts.label]
   * @param {boolean} [opts.hideLabel] — label as aria-label only (use placeholder for visible cue)
   * @param {string} [opts.name]
   * @param {string} [opts.type=text]
   * @param {string} [opts.value]
   * @param {string} [opts.placeholder]
   * @param {string} [opts.hint]
   * @param {boolean} [opts.password]
   * @param {string} [opts.id]
   * @returns {{ root: HTMLElement, input: HTMLInputElement, reveal?: HTMLButtonElement }}
   */
  function createField(opts) {
    const o = opts || {};
    const root = document.createElement("div");
    root.className = "pr-field";

    const id = o.id || (o.name ? "pr-field-" + o.name : "pr-field-" + Math.random().toString(36).slice(2, 8));
    const labelText = o.label || o.placeholder || "Field";

    const input = document.createElement("input");
    input.id = id;
    input.name = o.name || id;
    input.type = o.password ? "password" : o.type || "text";
    input.autocomplete = o.password ? "off" : "on";
    if (o.value != null) input.value = o.value;
    if (o.placeholder) input.placeholder = o.placeholder;
    if (o.required) input.required = true;

    if (o.hideLabel) {
      input.setAttribute("aria-label", labelText);
    } else {
      const label = document.createElement("label");
      label.htmlFor = id;
      label.textContent = labelText;
      root.appendChild(label);
    }

    const result = { root: root, input: input };

    if (o.password) {
      const control = document.createElement("div");
      control.className = "pr-field__control";

      const reveal = document.createElement("button");
      reveal.type = "button";
      reveal.className = "pr-field__reveal";
      reveal.setAttribute("aria-label", "Show " + labelText);
      reveal.setAttribute("aria-pressed", "false");
      reveal.innerHTML = EYE_OPEN;

      reveal.addEventListener("click", function () {
        const showing = input.type === "text";
        input.type = showing ? "password" : "text";
        reveal.setAttribute("aria-pressed", showing ? "false" : "true");
        reveal.setAttribute("aria-label", (showing ? "Show " : "Hide ") + labelText);
        reveal.innerHTML = showing ? EYE_OPEN : EYE_OFF;
      });

      control.appendChild(input);
      control.appendChild(reveal);
      root.appendChild(control);
      result.reveal = reveal;
    } else {
      root.appendChild(input);
    }

    if (o.hint) {
      const hint = document.createElement("div");
      hint.className = "pr-hint";
      hint.textContent = o.hint;
      root.appendChild(hint);
    }

    return result;
  }

  global.PhotorealUI = global.PhotorealUI || {};
  global.PhotorealUI.createField = createField;
})(window);
