(function (global) {
  "use strict";
  // Aggregate entry — pages load this after component scripts, or load components directly.
  // Factories live on window.PhotorealUI from button.js / field.js.
  if (!global.PhotorealUI || !global.PhotorealUI.createButton || !global.PhotorealUI.createField) {
    console.error("PhotorealUI: load components/button.js and components/field.js before photoreal-ui.js");
  }
})(window);
