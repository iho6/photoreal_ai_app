(function () {
  "use strict";

  var UI = window.PhotorealUI;
  var M = window.TimelineModel;
  var R = window.TimelineRender;
  var P = window.TimelinePreview;
  var I = window.TimelineInteract;

  var app = document.getElementById("app");

  var PREVIEW_MIN = 120;
  var PREVIEW_MAX_VH = 0.7;
  var PREVIEW_DEFAULT = Math.min(
    280,
    Math.max(PREVIEW_MIN, Math.round(window.innerHeight * 0.32))
  );

  var previewWrap = document.createElement("div");
  previewWrap.className = "tl-preview-wrap";
  previewWrap.style.height = PREVIEW_DEFAULT + "px";

  var preview = document.createElement("div");
  preview.className = "tl-preview";
  preview.setAttribute("role", "img");
  preview.setAttribute("aria-label", "Preview");

  var resizeHandle = document.createElement("div");
  resizeHandle.className = "tl-preview-resize";
  resizeHandle.setAttribute("role", "separator");
  resizeHandle.setAttribute("aria-orientation", "horizontal");
  resizeHandle.setAttribute("aria-label", "Resize preview");
  resizeHandle.tabIndex = 0;

  previewWrap.appendChild(preview);
  previewWrap.appendChild(resizeHandle);

  function maxPreviewHeight() {
    return Math.max(PREVIEW_MIN, Math.round(window.innerHeight * PREVIEW_MAX_VH));
  }

  function setPreviewHeight(px) {
    var clamped = Math.max(PREVIEW_MIN, Math.min(maxPreviewHeight(), px));
    previewWrap.style.height = clamped + "px";
    return clamped;
  }

  var dragStartY = 0;
  var dragStartH = 0;

  function onPointerMove(ev) {
    var dy = ev.clientY - dragStartY;
    setPreviewHeight(dragStartH + dy);
  }

  function onPointerUp(ev) {
    previewWrap.dataset.resizing = "false";
    try {
      resizeHandle.releasePointerCapture(ev.pointerId);
    } catch (_) {}
    window.removeEventListener("pointermove", onPointerMove);
    window.removeEventListener("pointerup", onPointerUp);
  }

  resizeHandle.addEventListener("pointerdown", function (ev) {
    if (ev.button != null && ev.button !== 0) return;
    dragStartY = ev.clientY;
    dragStartH = previewWrap.getBoundingClientRect().height;
    previewWrap.dataset.resizing = "true";
    resizeHandle.setPointerCapture(ev.pointerId);
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
    ev.preventDefault();
  });

  resizeHandle.addEventListener("keydown", function (ev) {
    var step = ev.shiftKey ? 24 : 12;
    var h = previewWrap.getBoundingClientRect().height;
    if (ev.key === "ArrowUp") {
      setPreviewHeight(h - step);
      ev.preventDefault();
    } else if (ev.key === "ArrowDown") {
      setPreviewHeight(h + step);
      ev.preventDefault();
    }
  });

  window.addEventListener("resize", function () {
    setPreviewHeight(previewWrap.getBoundingClientRect().height);
  });

  var actions = document.createElement("div");
  actions.className = "tl-actions";

  function ensureCharacterScripts(cb) {
    if (window.PhotorealCharacter && typeof window.PhotorealCharacter.openModal === "function") {
      cb();
      return;
    }
    var n = 0;
    var failed = false;
    function done(ok) {
      if (!ok) failed = true;
      n += 1;
      if (n < 2) return;
      if (failed || !window.PhotorealCharacter) {
        window.alert(
          "Character studio failed to load. Restart the portal (python -m photoreal.portal) and hard-refresh."
        );
        return;
      }
      cb();
    }
    function load(src) {
      var existing = document.querySelector('script[src="' + src + '"]');
      if (existing) {
        done(!!window.PhotorealCharacter || src.indexOf("gallery") >= 0);
        return;
      }
      var s = document.createElement("script");
      s.src = src;
      s.onload = function () {
        done(true);
      };
      s.onerror = function () {
        done(false);
      };
      document.body.appendChild(s);
    }
    if (!document.querySelector('link[data-ch-css="1"]')) {
      var link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = "/character-assets/character.css?v=ch3";
      link.dataset.chCss = "1";
      document.head.appendChild(link);
    }
    load("/character-assets/gallery.js?v=ch3");
    load("/character-assets/character.js?v=log-select");
  }

  function ensureReferenceScripts(cb) {
    var src = "/reference-assets/record_reference.js?v=rr9";
    if (
      window.PhotorealRecordReference &&
      typeof window.PhotorealRecordReference.openModal === "function" &&
      window.PhotorealRecordReference.version === "rr9"
    ) {
      cb();
      return;
    }
    // Drop stale script so Stop→preview fixes actually load.
    var stale = document.querySelectorAll(
      'script[src^="/reference-assets/record_reference.js"]'
    );
    for (var i = 0; i < stale.length; i++) {
      stale[i].parentNode.removeChild(stale[i]);
    }
    window.PhotorealRecordReference = null;
    var s = document.createElement("script");
    s.src = src;
    s.onload = function () {
      cb();
    };
    s.onerror = function () {
      window.alert(
        "Record Reference failed to load. Restart the portal and hard-refresh."
      );
    };
    document.body.appendChild(s);
  }

  var state = M.createState();
  var editor = R.createEditorDom(UI);
  var previewCtl = P.createPreview(preview);

  var locationFileInput = document.createElement("input");
  locationFileInput.type = "file";
  locationFileInput.accept = "image/*";
  locationFileInput.multiple = true;
  locationFileInput.hidden = true;
  locationFileInput.addEventListener("change", function () {
    var files = locationFileInput.files;
    if (!files || !files.length) return;
    M.addLocationClipsFromFiles(state, files, state.playhead)
      .then(function (created) {
        if (!created || !created.length) {
          window.alert(
            "Could not add location clip (Locations track may be locked)."
          );
        }
      })
      .catch(function (e) {
        window.alert("Could not add location: " + (e.message || e));
      });
    locationFileInput.value = "";
  });
  app.appendChild(locationFileInput);

  [
    {
      label: "Create Location",
      onClick: function () {
        locationFileInput.click();
      },
    },
    {
      label: "Create Character",
      onClick: function () {
        ensureCharacterScripts(function () {
          try {
            window.PhotorealCharacter.openModal();
          } catch (e) {
            window.alert("Could not open Create Character: " + (e.message || e));
          }
        });
      },
    },
    {
      label: "Record Reference",
      onClick: function () {
        ensureReferenceScripts(function () {
          try {
            window.PhotorealRecordReference.openModal({
              onSave: function (blob, meta) {
                M.addReferenceClip(state, blob, meta)
                  .then(function (clip) {
                    if (!clip) {
                      window.alert(
                        "Could not add reference clip (References track may be locked)."
                      );
                    }
                  })
                  .catch(function (e) {
                    window.alert(
                      "Could not add reference clip: " + (e.message || e)
                    );
                  });
              },
            });
          } catch (e) {
            window.alert("Could not open Record Reference: " + (e.message || e));
          }
        });
      },
    },
  ].forEach(function (spec) {
    actions.appendChild(
      UI.createButton({
        label: spec.label,
        onClick: spec.onClick,
      })
    );
  });

  app.appendChild(previewWrap);
  app.appendChild(actions);
  app.appendChild(editor.root);

  I.bindInteractions(editor, state, previewCtl);
})();
