(function (global) {
  "use strict";

  function bindInteractions(dom, state, preview) {
    var M = global.TimelineModel;
    var R = global.TimelineRender;
    var importTrackId = null;

    function patchClipEl(clip) {
      var el = dom.lanes.querySelector('.nle-clip[data-clip-id="' + clip.id + '"]');
      if (!el) return;
      var lane = dom.lanes.querySelector('.nle-lane[data-track-id="' + clip.trackId + '"]');
      if (lane && el.parentElement !== lane) {
        lane.appendChild(el);
      }
      el.style.left = clip.start * state.pxPerSec + "px";
      el.style.width = Math.max(4, clip.duration * state.pxPerSec) + "px";
      el.dataset.trackId = clip.trackId;
    }

    function refresh() {
      R.renderAll(dom, state);
      preview.sync(state);
      R.followPlayhead(dom, state);
    }

    M.onChange(state, function (s) {
      if (s._emitKind === "playhead") {
        R.renderPlayhead(dom, s);
        preview.sync(s);
        R.followPlayhead(dom, s);
        return;
      }
      if (s._emitKind === "drag" && s.selection) {
        var clip = M.findClip(s, s.selection.clipId);
        if (clip) patchClipEl(clip);
        R.renderPlayhead(dom, s);
        preview.sync(s);
        return;
      }
      R.renderAll(dom, s);
      preview.sync(s);
      R.followPlayhead(dom, s);
    });

    dom.addTrackBtn.addEventListener("click", function () {
      M.addTrack(state);
    });

    dom.importBtn.addEventListener("click", function () {
      if (!state.tracks.length) {
        M.addTrack(state);
      }
      importTrackId = state.tracks[0].id;
      dom.fileInput.value = "";
      dom.fileInput.click();
    });

    dom.fileInput.addEventListener("change", function () {
      var trackId = importTrackId || (state.tracks[0] && state.tracks[0].id);
      if (!trackId || !dom.fileInput.files || !dom.fileInput.files.length) return;
      M.addClipsFromFiles(state, trackId, dom.fileInput.files, state.playhead);
      importTrackId = null;
    });

    dom.headersCol.addEventListener("click", function (ev) {
      var btn = ev.target && ev.target.closest && ev.target.closest("[data-action]");
      if (!btn || !btn.dataset) return;
      if (btn.dataset.action === "toggle-hidden") {
        M.toggleHidden(state, btn.dataset.trackId);
      }
    });

    var menuEl = null;
    var flyoutEl = null;

    function dismissFlyout() {
      if (flyoutEl && flyoutEl.parentNode) flyoutEl.parentNode.removeChild(flyoutEl);
      flyoutEl = null;
    }

    function dismissMenu() {
      dismissFlyout();
      if (menuEl && menuEl.parentNode) menuEl.parentNode.removeChild(menuEl);
      menuEl = null;
    }

    function placeMenu(clientX, clientY) {
      document.body.appendChild(menuEl);
      var pad = 4;
      var rect = menuEl.getBoundingClientRect();
      var left = Math.min(clientX, window.innerWidth - rect.width - pad);
      var top = Math.min(clientY, window.innerHeight - rect.height - pad);
      menuEl.style.left = Math.max(pad, left) + "px";
      menuEl.style.top = Math.max(pad, top) + "px";
    }

    function menuItem(label, onClick) {
      var item = document.createElement("button");
      item.type = "button";
      item.className = "nle-menu__item";
      item.setAttribute("role", "menuitem");
      item.textContent = label;
      item.addEventListener("click", function () {
        dismissMenu();
        onClick();
      });
      return item;
    }

    function menuItemDisabled(label) {
      var item = document.createElement("button");
      item.type = "button";
      item.className = "nle-menu__item nle-menu__item--disabled";
      item.setAttribute("role", "menuitem");
      item.disabled = true;
      item.textContent = label;
      return item;
    }

    function menuCheckboxItem(label, checked, onToggle) {
      var item = document.createElement("button");
      item.type = "button";
      item.className = "nle-menu__item nle-menu__item--check";
      item.setAttribute("role", "menuitemcheckbox");
      item.setAttribute("aria-checked", checked ? "true" : "false");
      item.textContent = (checked ? "✓ " : "○ ") + label;
      item.addEventListener("click", function () {
        dismissMenu();
        onToggle(!checked);
      });
      return item;
    }

    function clearDownstreamFromSegment(clip) {
      clip.depthUrl = null;
      clip.showDepth = false;
      clip.inpaintUrl = null;
      clip.showInpaint = false;
      clip.backdropClipId = null;
      clip.poseLockUrl = null;
      clip.showPoseLock = false;
    }

    function segmentTimelineTime(clip) {
      var local =
        clip.segmentLocalTime == null || !isFinite(clip.segmentLocalTime)
          ? 0
          : Number(clip.segmentLocalTime);
      return clip.start + local;
    }

    function hasBackdropForClip(clip) {
      if (
        !clip ||
        !clip.segmentMaskUrl ||
        !clip.segmentFrameUrl ||
        !clip.segmentCutoutUrl
      ) {
        return false;
      }
      var t = segmentTimelineTime(clip);
      return !!M.findBackdropClip(state, clip, t);
    }

    function exclusiveShow(clip, flag) {
      clip.showSegment = flag === "segment";
      clip.showDepth = flag === "depth";
      clip.showInpaint = flag === "inpaint";
      clip.showPoseLock = flag === "poseLock";
    }

    function appendReplaceCharacterMenuItems(menu, clip) {
      menu.appendChild(
        menuItem("Segment", function () {
          runSegmentFromClip(clip);
        })
      );
      if (clip.segmentCutoutUrl) {
        menu.appendChild(
          menuCheckboxItem("Show Segment", !!clip.showSegment, function (on) {
            if (on) exclusiveShow(clip, "segment");
            else clip.showSegment = false;
            M.emit(state);
          })
        );
      }

      if (clip.depthUrl) {
        menu.appendChild(
          menuCheckboxItem("Show Depth", !!clip.showDepth, function (on) {
            if (on) exclusiveShow(clip, "depth");
            else clip.showDepth = false;
            M.emit(state);
          })
        );
        menu.appendChild(
          menuItem("Depth", function () {
            runConvertDepth(clip);
          })
        );
      } else if (clip.segmentMaskUrl && clip.segmentFrameUrl) {
        menu.appendChild(
          menuItem("Depth", function () {
            runConvertDepth(clip);
          })
        );
      } else {
        menu.appendChild(menuItemDisabled("Depth"));
      }

      if (
        clip.segmentMaskUrl &&
        clip.segmentFrameUrl &&
        clip.segmentCutoutUrl &&
        hasBackdropForClip(clip)
      ) {
        menu.appendChild(buildCharacterReferenceItem(clip));
      } else {
        menu.appendChild(menuItemDisabled("Character Reference"));
      }
      if (clip.inpaintUrl) {
        menu.appendChild(
          menuCheckboxItem(
            "Show Character Reference",
            !!clip.showInpaint,
            function (on) {
              if (on) exclusiveShow(clip, "inpaint");
              else clip.showInpaint = false;
              M.emit(state);
            }
          )
        );
      }

      if (clip.poseLockUrl) {
        menu.appendChild(
          menuCheckboxItem("Show Pose Lock", !!clip.showPoseLock, function (on) {
            if (on) exclusiveShow(clip, "poseLock");
            else clip.showPoseLock = false;
            M.emit(state);
          })
        );
      }
      if (clip.depthUrl && clip.inpaintUrl) {
        menu.appendChild(
          menuItem("Pose Lock", function () {
            runPoseLock(clip);
          })
        );
      } else {
        menu.appendChild(menuItemDisabled("Pose Lock"));
      }

      if (clip.poseLockUrl && clip.src && clip.mediaType === "video") {
        menu.appendChild(
          menuItem("Wan Animate", function () {
            runWanAnimate(clip);
          })
        );
      } else {
        menu.appendChild(menuItemDisabled("Wan Animate"));
      }
    }

    function appendAnimateMenuItems(menu, clip) {
      var offset = (clip.videoFrameOffset || 0) + (clip.wanLength || 0);
      var total = clip.drivingFrameCount;
      var remaining =
        total != null && isFinite(Number(total))
          ? Math.max(0, Math.floor(Number(total)) - offset)
          : null;
      var canExtend =
        clip.drivingVideoSrc &&
        clip.characterStillUrl &&
        clip.src &&
        (remaining == null || remaining > 0);
      if (canExtend) {
        menu.appendChild(
          menuItem("Extend Animate", function () {
            runExtendAnimate(clip);
          })
        );
      } else {
        menu.appendChild(menuItemDisabled("Extend Animate"));
      }
    }

    function buildCharacterReferenceItem(clip) {
      var item = document.createElement("button");
      item.type = "button";
      item.className = "nle-menu__item";
      item.setAttribute("role", "menuitem");
      item.textContent = "Character Reference";
      item.addEventListener("mouseenter", function () {
        openCharacterGalleryFlyout(item, clip);
      });
      item.addEventListener("click", function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        openCharacterGalleryFlyout(item, clip);
      });
      return item;
    }

    function openCharacterGalleryFlyout(anchor, clip) {
      dismissFlyout();
      flyoutEl = document.createElement("div");
      flyoutEl.className = "nle-menu nle-menu--flyout";
      flyoutEl.setAttribute("role", "menu");
      flyoutEl.style.position = "fixed";
      flyoutEl.style.zIndex = "2600";
      flyoutEl.style.maxWidth = "280px";
      flyoutEl.style.maxHeight = "320px";
      flyoutEl.style.overflow = "auto";
      flyoutEl.style.padding = "0.5rem";
      var loading = document.createElement("div");
      loading.className = "nle-menu__item nle-menu__item--disabled";
      loading.textContent = "Loading…";
      flyoutEl.appendChild(loading);
      document.body.appendChild(flyoutEl);

      var aRect = anchor.getBoundingClientRect();
      var mRect = menuEl ? menuEl.getBoundingClientRect() : aRect;
      var left = mRect.right + 4;
      if (left + 280 > window.innerWidth - 4) left = Math.max(4, mRect.left - 284);
      flyoutEl.style.left = left + "px";
      flyoutEl.style.top = Math.max(4, aRect.top) + "px";

      fetch("/api/character/gallery")
        .then(function (r) {
          return r.json().then(function (j) {
            if (!r.ok) throw new Error(j.detail || r.statusText);
            return j;
          });
        })
        .then(function (data) {
          if (!flyoutEl) return;
          flyoutEl.innerHTML = "";
          var items = (data && data.items) || [];
          if (!items.length) {
            var empty = document.createElement("div");
            empty.className = "nle-menu__item nle-menu__item--disabled";
            empty.textContent = "Generate characters in Create Character first";
            flyoutEl.appendChild(empty);
            return;
          }
          var grid = document.createElement("div");
          grid.style.display = "grid";
          grid.style.gridTemplateColumns = "repeat(3, 1fr)";
          grid.style.gap = "0.35rem";
          items.forEach(function (it) {
            if (!it || !it.url) return;
            var btn = document.createElement("button");
            btn.type = "button";
            btn.style.padding = "0";
            btn.style.border = "var(--pr-line-width) solid var(--pr-line)";
            btn.style.background = "transparent";
            btn.style.cursor = "pointer";
            btn.style.aspectRatio = "1";
            btn.style.overflow = "hidden";
            var thumb = document.createElement("img");
            thumb.src = it.url;
            thumb.alt = it.id || "character";
            thumb.style.width = "100%";
            thumb.style.height = "100%";
            thumb.style.objectFit = "cover";
            thumb.style.display = "block";
            btn.appendChild(thumb);
            btn.addEventListener("click", function () {
              dismissMenu();
              runCharacterInpaint(clip, it.url);
            });
            grid.appendChild(btn);
          });
          flyoutEl.appendChild(grid);
        })
        .catch(function (e) {
          if (!flyoutEl) return;
          flyoutEl.innerHTML = "";
          var err = document.createElement("div");
          err.className = "nle-menu__item nle-menu__item--disabled";
          err.textContent = "Gallery failed: " + (e.message || e);
          flyoutEl.appendChild(err);
        });
    }

    function showTrackMenu(clientX, clientY, trackId) {
      dismissMenu();
      menuEl = document.createElement("div");
      menuEl.className = "nle-menu";
      menuEl.setAttribute("role", "menu");
      menuEl.appendChild(
        menuItem("Delete", function () {
          M.deleteTrack(state, trackId);
        })
      );
      placeMenu(clientX, clientY);
    }

    function extractFrameBlob(clip, localTime) {
      if (!clip || !clip.src) {
        return Promise.reject(new Error("No media on clip"));
      }
      if (clip.mediaType === "image") {
        return fetch(clip.src).then(function (r) {
          if (!r.ok) throw new Error("Could not load image");
          return r.blob();
        });
      }
      if (clip.mediaType !== "video") {
        return Promise.reject(new Error("Segment needs a video or image clip"));
      }
      return new Promise(function (resolve, reject) {
        var v = document.createElement("video");
        v.muted = true;
        v.playsInline = true;
        v.preload = "auto";
        var done = false;
        function fail(msg) {
          if (done) return;
          done = true;
          try {
            v.removeAttribute("src");
            v.load();
          } catch (_) {}
          reject(new Error(msg || "Frame extract failed"));
        }
        function grab() {
          if (done) return;
          try {
            var w = v.videoWidth || 0;
            var h = v.videoHeight || 0;
            if (!w || !h) {
              fail("Video has no dimensions");
              return;
            }
            var canvas = document.createElement("canvas");
            canvas.width = w;
            canvas.height = h;
            var ctx = canvas.getContext("2d");
            ctx.drawImage(v, 0, 0, w, h);
            canvas.toBlob(
              function (blob) {
                done = true;
                try {
                  v.removeAttribute("src");
                  v.load();
                } catch (_) {}
                if (!blob) reject(new Error("Could not encode frame"));
                else resolve(blob);
              },
              "image/png"
            );
          } catch (e) {
            fail(e.message || String(e));
          }
        }
        v.onerror = function () {
          fail("Could not load video");
        };
        v.onloadeddata = function () {
          var t = Math.max(0, localTime || 0);
          var dur = v.duration;
          if (isFinite(dur) && dur > 0) t = Math.min(t, Math.max(0, dur - 0.05));
          try {
            v.currentTime = t;
          } catch (_) {
            grab();
          }
        };
        v.onseeked = grab;
        v.src = clip.src;
      });
    }

    function showImageResultModal(url, alt) {
      var backdrop = document.createElement("div");
      backdrop.className = "nle-menu";
      backdrop.style.position = "fixed";
      backdrop.style.inset = "0";
      backdrop.style.left = "0";
      backdrop.style.top = "0";
      backdrop.style.width = "100%";
      backdrop.style.height = "100%";
      backdrop.style.background = "rgba(10,10,10,0.45)";
      backdrop.style.display = "flex";
      backdrop.style.alignItems = "center";
      backdrop.style.justifyContent = "center";
      backdrop.style.zIndex = "2500";
      backdrop.style.padding = "1rem";
      var box = document.createElement("div");
      box.style.background = "var(--pr-bg)";
      box.style.border = "var(--pr-line-width) solid var(--pr-line)";
      box.style.padding = "0.75rem";
      box.style.maxWidth = "min(90vw, 720px)";
      box.style.maxHeight = "90vh";
      box.style.overflow = "auto";
      var img = document.createElement("img");
      img.src = url;
      img.alt = alt || "Result";
      img.style.display = "block";
      img.style.maxWidth = "100%";
      img.style.height = "auto";
      img.style.background =
        "repeating-conic-gradient(#ccc 0% 25%, #eee 0% 50%) 50% / 16px 16px";
      var link = document.createElement("a");
      link.href = url;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = "Open full size";
      link.style.display = "inline-block";
      link.style.marginTop = "0.5rem";
      var close = document.createElement("button");
      close.type = "button";
      close.className = "nle-menu__item";
      close.textContent = "Close";
      close.style.marginTop = "0.5rem";
      close.addEventListener("click", function () {
        backdrop.remove();
      });
      box.appendChild(img);
      box.appendChild(link);
      box.appendChild(close);
      backdrop.appendChild(box);
      backdrop.addEventListener("click", function (ev) {
        if (ev.target === backdrop) backdrop.remove();
      });
      document.body.appendChild(backdrop);
    }

    function showSegmentResult(job, clip, localT) {
      var urls = (job && job.images) || [];
      if (!urls.length) {
        window.alert("Segment finished but returned no images.");
        return;
      }
      if (clip) {
        clip.segmentMaskUrl = urls[0];
        clip.segmentFrameUrl = job.frame_url || null;
        clip.segmentCutoutUrl = job.cutout_url || null;
        clip.segmentLocalTime =
          localT == null || !isFinite(localT) ? 0 : Number(localT);
        clearDownstreamFromSegment(clip);
        if (clip.segmentCutoutUrl) exclusiveShow(clip, "segment");
        else clip.showSegment = false;
        if (!clip.segmentFrameUrl) {
          window.alert(
            "Segment saved mask but no frame URL — Depth will stay disabled. Re-segment after updating the portal."
          );
        }
        M.emit(state);
      }
      var previewUrl = (job && job.cutout_url) || urls[0];
      showImageResultModal(previewUrl, "Segment cutout");
    }

    function pollJob(url, label, maxTicks) {
      return new Promise(function (resolve, reject) {
        var n = 0;
        function tick() {
          fetch(url)
            .then(function (r) {
              return r.json().then(function (j) {
                if (!r.ok) throw new Error(j.detail || r.statusText);
                return j;
              });
            })
            .then(function (j) {
              if (j.status === "done" || j.status === "completed") {
                resolve(j);
                return;
              }
              if (j.status === "error" || j.status === "failed") {
                reject(new Error(j.error || label + " failed"));
                return;
              }
              n += 1;
              if (n > (maxTicks || 240)) {
                reject(new Error(label + " timed out"));
                return;
              }
              setTimeout(tick, 1000);
            })
            .catch(reject);
        }
        tick();
      });
    }

    function pollSam3Job(jobId) {
      return pollJob(
        "/api/sam3/jobs/" + encodeURIComponent(jobId),
        "SAM3",
        180
      );
    }

    function pollDepthJob(jobId) {
      return pollJob(
        "/api/depth/jobs/" + encodeURIComponent(jobId),
        "Depth convert",
        240
      );
    }

    function pollInpaintJob(jobId) {
      return pollJob(
        "/api/character/inpaint/jobs/" + encodeURIComponent(jobId),
        "Character inpaint",
        360
      );
    }

    function pollPoseLockJob(jobId) {
      return pollJob(
        "/api/character/pose-lock/jobs/" + encodeURIComponent(jobId),
        "Pose lock",
        360
      );
    }

    function fetchUrlBlob(url) {
      return fetch(url).then(function (r) {
        if (!r.ok) throw new Error("Could not load " + url);
        return r.blob();
      });
    }

    function loadImageElement(src) {
      return new Promise(function (resolve, reject) {
        var img = new Image();
        img.onload = function () {
          resolve(img);
        };
        img.onerror = function () {
          reject(new Error("Could not decode image"));
        };
        img.src = src;
      });
    }

    /** Cover-scale backdrop into WxH, then alpha-paste cutout on top. */
    function composeBackdropScene(backdropBlob, cutoutUrl, frameW, frameH) {
      var w = Math.max(1, Math.round(frameW));
      var h = Math.max(1, Math.round(frameH));
      var backdropUrl = URL.createObjectURL(backdropBlob);
      return Promise.all([
        loadImageElement(backdropUrl),
        loadImageElement(cutoutUrl),
      ])
        .then(function (pair) {
          var backdropImg = pair[0];
          var cutoutImg = pair[1];
          var canvas = document.createElement("canvas");
          canvas.width = w;
          canvas.height = h;
          var ctx = canvas.getContext("2d");
          var bw = backdropImg.naturalWidth || backdropImg.width;
          var bh = backdropImg.naturalHeight || backdropImg.height;
          var scale = Math.max(w / bw, h / bh);
          var dw = bw * scale;
          var dh = bh * scale;
          var dx = (w - dw) / 2;
          var dy = (h - dh) / 2;
          ctx.drawImage(backdropImg, dx, dy, dw, dh);
          ctx.drawImage(cutoutImg, 0, 0, w, h);
          return new Promise(function (resolve, reject) {
            canvas.toBlob(function (blob) {
              if (!blob) reject(new Error("Could not encode composite scene"));
              else resolve(blob);
            }, "image/png");
          });
        })
        .finally(function () {
          try {
            URL.revokeObjectURL(backdropUrl);
          } catch (_) {}
        });
    }

    function imageNaturalSize(url) {
      return loadImageElement(url).then(function (img) {
        return {
          width: img.naturalWidth || img.width,
          height: img.naturalHeight || img.height,
        };
      });
    }

    function runSegmentFromClip(clip) {
      if (!clip) {
        window.alert("No clip to segment.");
        return;
      }
      var concept = window.prompt(
        "Segment concept (text prompt for SAM3)",
        "person"
      );
      if (concept == null) return;
      concept = String(concept).trim();
      if (!concept) {
        window.alert("A text concept is required.");
        return;
      }
      // Reference clips: prefer first source frame (inPoint) for Replace Character.
      var localT =
        clip.mediaType === "video"
          ? clip.role === "reference"
            ? Math.max(0, clip.inPoint || 0)
            : Math.max(0, state.playhead - clip.start + (clip.inPoint || 0))
          : 0;
      extractFrameBlob(clip, localT)
        .then(function (blob) {
          var fd = new FormData();
          fd.append("image", blob, "frame.png");
          fd.append("job", "image_mask");
          fd.append("text_prompt", concept);
          return fetch("/api/sam3/segment", { method: "POST", body: fd }).then(
            function (r) {
              return r.json().then(function (j) {
                if (!r.ok) throw new Error(j.detail || r.statusText);
                return j;
              });
            }
          );
        })
        .then(function (started) {
          if (!started.job_id) throw new Error("No job_id from SAM3");
          return pollSam3Job(started.job_id);
        })
        .then(function (job) {
          showSegmentResult(job, clip, localT);
        })
        .catch(function (e) {
          window.alert("Segment failed: " + (e.message || e));
        });
    }

    function runConvertDepth(clip) {
      if (!clip || !clip.segmentMaskUrl || !clip.segmentFrameUrl) {
        window.alert("Segment the clip first (mask + frame required).");
        return;
      }
      Promise.all([
        fetchUrlBlob(clip.segmentFrameUrl),
        fetchUrlBlob(clip.segmentMaskUrl),
      ])
        .then(function (pair) {
          var fd = new FormData();
          fd.append("image", pair[0], "frame.png");
          fd.append("mask", pair[1], "mask.png");
          fd.append("feather_px", "7");
          return fetch("/api/depth/convert", { method: "POST", body: fd }).then(
            function (r) {
              return r.json().then(function (j) {
                if (!r.ok) throw new Error(j.detail || r.statusText);
                return j;
              });
            }
          );
        })
        .then(function (started) {
          if (!started.job_id) throw new Error("No job_id from depth convert");
          return pollDepthJob(started.job_id);
        })
        .then(function (job) {
          var urls = (job && job.images) || [];
          if (!urls.length) throw new Error("Depth finished with no images");
          clip.depthUrl = urls[0];
          clip.poseLockUrl = null;
          exclusiveShow(clip, "depth");
          M.emit(state);
          showImageResultModal(urls[0], "Person depth");
        })
        .catch(function (e) {
          window.alert("Depth failed: " + (e.message || e));
        });
    }

    function runCharacterInpaint(clip, referenceUrl) {
      if (
        !clip ||
        !clip.segmentMaskUrl ||
        !clip.segmentFrameUrl ||
        !clip.segmentCutoutUrl
      ) {
        window.alert("Segment the clip first (mask + cutout required).");
        return;
      }
      if (!referenceUrl) {
        window.alert("Pick a character from the gallery.");
        return;
      }
      var t = segmentTimelineTime(clip);
      var backdrop = M.findBackdropClip(state, clip, t);
      if (!backdrop) {
        window.alert(
          "Place a Location plate under this reference so it overlaps (Create Location). Untagged images/videos are ignored for backdrop lighting."
        );
        return;
      }
      var backdropLocal =
        Math.max(0, t - backdrop.start) + (backdrop.inPoint || 0);

      Promise.all([
        extractFrameBlob(backdrop, backdropLocal),
        imageNaturalSize(clip.segmentFrameUrl),
        fetchUrlBlob(clip.segmentMaskUrl),
        fetchUrlBlob(referenceUrl),
      ])
        .then(function (parts) {
          var backdropBlob = parts[0];
          var size = parts[1];
          var maskBlob = parts[2];
          var refBlob = parts[3];
          return composeBackdropScene(
            backdropBlob,
            clip.segmentCutoutUrl,
            size.width,
            size.height
          ).then(function (sceneBlob) {
            var fd = new FormData();
            fd.append("scene", sceneBlob, "scene.png");
            fd.append("mask", maskBlob, "mask.png");
            fd.append("reference", refBlob, "reference.png");
            return fetch("/api/character/inpaint", {
              method: "POST",
              body: fd,
            }).then(function (r) {
              return r.json().then(function (j) {
                if (!r.ok) throw new Error(j.detail || r.statusText);
                return j;
              });
            });
          });
        })
        .then(function (started) {
          if (!started.job_id) throw new Error("No job_id from inpaint");
          return pollInpaintJob(started.job_id);
        })
        .then(function (job) {
          var urls = (job && job.images) || [];
          if (!urls.length) throw new Error("Inpaint finished with no images");
          clip.inpaintUrl = urls[0];
          clip.backdropClipId = backdrop.id;
          clip.poseLockUrl = null;
          clip.showPoseLock = false;
          exclusiveShow(clip, "inpaint");
          M.emit(state);
          showImageResultModal(
            urls[0],
            "Character on backdrop (composited scene)"
          );
        })
        .catch(function (e) {
          window.alert("Character Reference failed: " + (e.message || e));
        });
    }

    function runPoseLock(clip) {
      if (!clip || !clip.depthUrl || !clip.inpaintUrl) {
        window.alert("Need Depth and Character Reference bake first.");
        return;
      }
      Promise.all([
        fetchUrlBlob(clip.depthUrl),
        fetchUrlBlob(clip.inpaintUrl),
      ])
        .then(function (pair) {
          var fd = new FormData();
          fd.append("depth", pair[0], "depth.png");
          fd.append("reference", pair[1], "bake.png");
          fd.append("prompt", "refcontrol");
          return fetch("/api/character/pose-lock", {
            method: "POST",
            body: fd,
          }).then(function (r) {
            return r.json().then(function (j) {
              if (!r.ok) throw new Error(j.detail || r.statusText);
              return j;
            });
          });
        })
        .then(function (started) {
          if (!started.job_id) throw new Error("No job_id from pose lock");
          return pollPoseLockJob(started.job_id);
        })
        .then(function (job) {
          var urls = (job && job.images) || [];
          if (!urls.length) throw new Error("Pose lock finished with no images");
          clip.poseLockUrl = urls[0];
          exclusiveShow(clip, "poseLock");
          M.emit(state);
          showImageResultModal(urls[0], "Pose lock");
        })
        .catch(function (e) {
          window.alert("Pose Lock failed: " + (e.message || e));
        });
    }

    function clampWanLength(requested, remaining) {
      var n = Math.min(Math.max(1, Math.floor(Number(requested) || 77)), 77);
      if (remaining != null && isFinite(Number(remaining))) {
        n = Math.min(n, Math.max(0, Math.floor(Number(remaining))));
      }
      if (n <= 0) return 0;
      return Math.max(1, Math.floor((n - 1) / 4) * 4 + 1);
    }

    function probeVideoMeta(src) {
      return new Promise(function (resolve) {
        var el = document.createElement("video");
        el.preload = "metadata";
        var done = false;
        function finish(fps, frames) {
          if (done) return;
          done = true;
          resolve({ fps: fps, frames: frames });
        }
        el.onloadedmetadata = function () {
          var dur = el.duration;
          var fps = state.fps > 0 ? state.fps : 24;
          if (isFinite(dur) && dur > 0) {
            finish(fps, Math.max(1, Math.round(dur * fps)));
            return;
          }
          finish(24, null);
        };
        el.onerror = function () {
          finish(24, null);
        };
        el.src = src;
      });
    }

    function pollWanAnimateJob(jobId) {
      return pollJob(
        "/api/wan-animate/jobs/" + encodeURIComponent(jobId),
        "Wan Animate",
        720
      );
    }

    function postWanAnimate(opts) {
      var fd = new FormData();
      fd.append("character", opts.characterBlob, "character.png");
      fd.append("video", opts.drivingBlob, opts.drivingName || "driving.mp4");
      if (opts.continueBlob) {
        fd.append(
          "continue_motion",
          opts.continueBlob,
          opts.continueName || "continue.mp4"
        );
      }
      fd.append(
        "prompt",
        opts.prompt || "a person moving naturally, photorealistic"
      );
      fd.append("length", String(opts.length || 77));
      fd.append("offset", String(opts.offset || 0));
      if (opts.fps != null && isFinite(opts.fps)) {
        fd.append("fps", String(opts.fps));
      }
      if (opts.drivingFrameCount != null && isFinite(opts.drivingFrameCount)) {
        fd.append("driving_frame_count", String(opts.drivingFrameCount));
      }
      fd.append(
        "continue_motion_max_frames",
        String(opts.continueMotionMaxFrames || 5)
      );
      return fetch("/api/wan-animate", { method: "POST", body: fd }).then(
        function (r) {
          return r.json().then(function (j) {
            if (!r.ok) throw new Error(j.detail || r.statusText);
            return j;
          });
        }
      );
    }

    function placeAnimateFromJob(job, placeMeta) {
      var urls = (job && job.videos) || [];
      if (!urls.length) throw new Error("Wan Animate finished with no video");
      var fps = job.fps || job.wanFps || placeMeta.wanFps || 24;
      var length = job.length != null ? job.length : placeMeta.wanLength;
      var trim =
        job.meta && job.meta.trim_image != null
          ? Number(job.meta.trim_image)
          : 0;
      var outFrames =
        length != null ? Math.max(1, Number(length) - (trim || 0)) : null;
      var duration =
        outFrames != null && fps > 0 ? outFrames / Number(fps) : null;
      return M.addAnimateClip(state, {
        src: urls[0],
        name: placeMeta.name || "Animate",
        start: placeMeta.start,
        duration: duration,
        sourceClipId: placeMeta.sourceClipId,
        drivingVideoSrc: placeMeta.drivingVideoSrc,
        characterStillUrl: placeMeta.characterStillUrl,
        videoFrameOffset:
          job.video_frame_offset != null
            ? job.video_frame_offset
            : placeMeta.videoFrameOffset,
        wanLength: length,
        wanFps: fps,
        drivingFrameCount:
          job.driving_frame_count != null
            ? job.driving_frame_count
            : placeMeta.drivingFrameCount,
        continueMotionMaxFrames: placeMeta.continueMotionMaxFrames || 5,
        wanPrompt: placeMeta.wanPrompt,
      });
    }

    function runWanAnimate(clip) {
      if (!clip || !clip.poseLockUrl || !clip.src) {
        window.alert("Need Pose Lock and a video clip.");
        return;
      }
      var prompt =
        window.prompt(
          "Wan Animate prompt",
          "a person moving naturally, photorealistic"
        ) || "";
      prompt =
        String(prompt).trim() || "a person moving naturally, photorealistic";

      Promise.all([
        fetchUrlBlob(clip.poseLockUrl),
        fetchUrlBlob(clip.src),
        probeVideoMeta(clip.src),
      ])
        .then(function (triple) {
          var charBlob = triple[0];
          var driveBlob = triple[1];
          var meta = triple[2] || {};
          var frames = meta.frames;
          var fps = meta.fps || state.fps || 24;
          var length = clampWanLength(77, frames);
          if (length <= 0) {
            throw new Error("Driving video has no frames");
          }
          return postWanAnimate({
            characterBlob: charBlob,
            drivingBlob: driveBlob,
            drivingName: "driving.mp4",
            prompt: prompt,
            length: length,
            offset: 0,
            fps: fps,
            drivingFrameCount: frames,
            continueMotionMaxFrames: 5,
          }).then(function (started) {
            if (!started.job_id) throw new Error("No job_id from wan-animate");
            return pollWanAnimateJob(started.job_id).then(function (job) {
              return placeAnimateFromJob(job, {
                name: "Animate",
                start: clip.start,
                sourceClipId: clip.id,
                drivingVideoSrc: clip.src,
                characterStillUrl: clip.poseLockUrl,
                videoFrameOffset: 0,
                wanLength: length,
                wanFps: fps,
                drivingFrameCount: frames,
                continueMotionMaxFrames: 5,
                wanPrompt: prompt,
              });
            });
          });
        })
        .catch(function (e) {
          window.alert("Wan Animate failed: " + (e.message || e));
        });
    }

    function runExtendAnimate(clip) {
      if (
        !clip ||
        clip.role !== "animate" ||
        !clip.drivingVideoSrc ||
        !clip.characterStillUrl ||
        !clip.src
      ) {
        window.alert(
          "Extend requires an Animate clip with stored driving/still refs."
        );
        return;
      }
      var nextOffset = (clip.videoFrameOffset || 0) + (clip.wanLength || 0);
      var prompt =
        clip.wanPrompt || "a person moving naturally, photorealistic";

      var metaPromise =
        clip.drivingFrameCount != null && clip.wanFps != null
          ? Promise.resolve({
              frames: clip.drivingFrameCount,
              fps: clip.wanFps,
            })
          : probeVideoMeta(clip.drivingVideoSrc);

      metaPromise
        .then(function (meta) {
          var frames =
            clip.drivingFrameCount != null
              ? clip.drivingFrameCount
              : meta.frames;
          var fps = clip.wanFps || meta.fps || state.fps || 24;
          var remaining =
            frames != null ? Math.max(0, frames - nextOffset) : 77;
          var length = clampWanLength(77, remaining);
          if (length <= 0) {
            throw new Error("No remaining driving frames to extend");
          }
          return Promise.all([
            fetchUrlBlob(clip.characterStillUrl),
            fetchUrlBlob(clip.drivingVideoSrc),
            fetchUrlBlob(clip.src),
          ]).then(function (triple) {
            return postWanAnimate({
              characterBlob: triple[0],
              drivingBlob: triple[1],
              drivingName: "driving.mp4",
              continueBlob: triple[2],
              continueName: "continue.mp4",
              prompt: prompt,
              length: length,
              offset: nextOffset,
              fps: fps,
              drivingFrameCount: frames,
              continueMotionMaxFrames: clip.continueMotionMaxFrames || 5,
            }).then(function (started) {
              if (!started.job_id) throw new Error("No job_id from wan-animate");
              return pollWanAnimateJob(started.job_id).then(function (job) {
                return placeAnimateFromJob(job, {
                  name: "Animate extend",
                  start: clip.start + clip.duration,
                  sourceClipId: clip.sourceClipId,
                  drivingVideoSrc: clip.drivingVideoSrc,
                  characterStillUrl: clip.characterStillUrl,
                  videoFrameOffset: nextOffset,
                  wanLength: length,
                  wanFps: fps,
                  drivingFrameCount: frames,
                  continueMotionMaxFrames: clip.continueMotionMaxFrames || 5,
                  wanPrompt: prompt,
                });
              });
            });
          });
        })
        .catch(function (e) {
          window.alert("Extend Animate failed: " + (e.message || e));
        });
    }

    function showClipMenu(clientX, clientY, clipId) {
      dismissMenu();
      var clip = M.findClip(state, clipId);
      if (!clip) return;
      menuEl = document.createElement("div");
      menuEl.className = "nle-menu";
      menuEl.setAttribute("role", "menu");
      if (clip.role === "animate") {
        appendAnimateMenuItems(menuEl, clip);
      } else {
        appendReplaceCharacterMenuItems(menuEl, clip);
      }
      placeMenu(clientX, clientY);
    }

    function showPreviewMenu(clientX, clientY) {
      dismissMenu();
      var clip = M.pictureClipAt(state, state.playhead);
      if (!clip) return;
      menuEl = document.createElement("div");
      menuEl.className = "nle-menu";
      menuEl.setAttribute("role", "menu");
      if (clip.role === "animate") {
        appendAnimateMenuItems(menuEl, clip);
      } else {
        appendReplaceCharacterMenuItems(menuEl, clip);
      }
      placeMenu(clientX, clientY);
    }

    function onContextTrack(ev) {
      var header = ev.target.closest && ev.target.closest(".nle-header");
      var lane = ev.target.closest && ev.target.closest(".nle-lane");
      var el = header || lane;
      if (!el || !el.dataset.trackId) return;
      if (ev.target.closest && ev.target.closest(".nle-clip")) return;
      ev.preventDefault();
      showTrackMenu(ev.clientX, ev.clientY, el.dataset.trackId);
    }

    function onContextClip(ev) {
      var clipEl = ev.target.closest && ev.target.closest(".nle-clip");
      if (!clipEl || !clipEl.dataset.clipId) return;
      ev.preventDefault();
      ev.stopPropagation();
      showClipMenu(ev.clientX, ev.clientY, clipEl.dataset.clipId);
    }

    function onContextPreview(ev) {
      var clip = M.pictureClipAt(state, state.playhead);
      if (!clip) return;
      ev.preventDefault();
      showPreviewMenu(ev.clientX, ev.clientY);
    }

    dom.headersCol.addEventListener("contextmenu", onContextTrack);
    dom.lanes.addEventListener("contextmenu", onContextTrack);
    dom.lanes.addEventListener("contextmenu", onContextClip);
    if (preview && preview.video && preview.video.parentElement) {
      preview.video.parentElement.addEventListener(
        "contextmenu",
        onContextPreview
      );
    }

    document.addEventListener("pointerdown", function (ev) {
      if (menuEl && !menuEl.contains(ev.target)) dismissMenu();
    });
    window.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") dismissMenu();
    });
    window.addEventListener("resize", function () {
      dismissMenu();
      R.renderAll(dom, state);
    });

    dom.playBtn.addEventListener("click", function () {
      state.playing = !state.playing;
      if (state.playing) {
        preview.startClock(state, function () {
          R.renderPlayhead(dom, state);
          R.followPlayhead(dom, state);
          preview.sync(state);
        });
      }
      M.emit(state);
    });

    dom.toStartBtn.addEventListener("click", function () {
      state.playing = false;
      M.setPlayhead(state, 0, { force: true });
    });

    dom.splitBtn.addEventListener("click", function () {
      M.splitAtPlayhead(state);
    });

    dom.zoomInBtn.addEventListener("click", function () {
      M.setPxPerSec(state, state.pxPerSec * 1.25);
    });

    dom.zoomOutBtn.addEventListener("click", function () {
      M.setPxPerSec(state, state.pxPerSec / 1.25);
    });

    dom.snapBtn.addEventListener("click", function () {
      M.setSnap(state, !state.snap);
    });

    dom.scroll.addEventListener(
      "wheel",
      function (ev) {
        if (ev.ctrlKey || ev.metaKey) {
          ev.preventDefault();
          var factor = ev.deltaY < 0 ? 1.1 : 1 / 1.1;
          M.setPxPerSec(state, state.pxPerSec * factor);
        }
      },
      { passive: false }
    );

    function scrubFromEvent(ev) {
      var t = R.xToTime(dom, state, ev.clientX);
      M.setPlayhead(state, t, { kind: "playhead" });
    }

    var scrubbingRuler = false;
    dom.ruler.addEventListener("pointerdown", function (ev) {
      if (ev.button != null && ev.button !== 0) return;
      scrubbingRuler = true;
      state.playing = false;
      preview.setScrubbing(true);
      dom.ruler.setPointerCapture(ev.pointerId);
      scrubFromEvent(ev);
      ev.preventDefault();
    });
    dom.ruler.addEventListener("pointermove", function (ev) {
      if (!scrubbingRuler) return;
      scrubFromEvent(ev);
    });
    function endRulerScrub(ev) {
      if (!scrubbingRuler) return;
      scrubbingRuler = false;
      preview.setScrubbing(false);
      try {
        dom.ruler.releasePointerCapture(ev.pointerId);
      } catch (_) {}
    }
    dom.ruler.addEventListener("pointerup", endRulerScrub);
    dom.ruler.addEventListener("pointercancel", endRulerScrub);

    var playheadDrag = false;
    dom.playhead.addEventListener("pointerdown", function (ev) {
      if (ev.button != null && ev.button !== 0) return;
      playheadDrag = true;
      state.playing = false;
      preview.setScrubbing(true);
      dom.playhead.setPointerCapture(ev.pointerId);
      scrubFromEvent(ev);
      ev.preventDefault();
      ev.stopPropagation();
    });
    dom.playhead.addEventListener("pointermove", function (ev) {
      if (!playheadDrag) return;
      scrubFromEvent(ev);
    });
    function endPlayhead(ev) {
      if (!playheadDrag) return;
      playheadDrag = false;
      preview.setScrubbing(false);
      try {
        dom.playhead.releasePointerCapture(ev.pointerId);
      } catch (_) {}
    }
    dom.playhead.addEventListener("pointerup", endPlayhead);
    dom.playhead.addEventListener("pointercancel", endPlayhead);

    var drag = null;

    dom.lanes.addEventListener("pointerdown", function (ev) {
      if (ev.button != null && ev.button !== 0) return;
      var target = ev.target;
      if (!target) return;

      var handle = target.closest && target.closest(".nle-clip__handle");
      var clipEl = target.closest && target.closest(".nle-clip");
      var lane = target.closest && target.closest(".nle-lane");

      if (handle && clipEl) {
        var clip = M.findClip(state, clipEl.dataset.clipId);
        if (!clip) return;
        var track = M.findTrack(state, clip.trackId);
        if (track && track.locked) return;
        M.selectClip(state, clip.id);
        M.pushUndo(state);
        drag = {
          mode: "trim",
          edge: handle.dataset.edge,
          clipId: clip.id,
          pointerId: ev.pointerId,
        };
        preview.setScrubbing(true);
        state.playing = false;
        clipEl.setPointerCapture(ev.pointerId);
        ev.preventDefault();
        ev.stopPropagation();
        return;
      }

      if (clipEl) {
        var c = M.findClip(state, clipEl.dataset.clipId);
        if (!c) return;
        var tr = M.findTrack(state, c.trackId);
        if (tr && tr.locked) return;
        M.selectClip(state, c.id);
        M.pushUndo(state);
        drag = {
          mode: "move",
          clipId: c.id,
          offsetX: R.xToTime(dom, state, ev.clientX) - c.start,
          pointerId: ev.pointerId,
          startY: ev.clientY,
        };
        preview.setScrubbing(true);
        state.playing = false;
        clipEl.setPointerCapture(ev.pointerId);
        ev.preventDefault();
        ev.stopPropagation();
        return;
      }

      if (lane) {
        M.selectClip(state, null);
        state.playing = false;
        M.setPlayhead(state, R.xToTime(dom, state, ev.clientX));
      }
    });

    dom.lanes.addEventListener("pointermove", function (ev) {
      if (!drag) return;
      var clip = M.findClip(state, drag.clipId);
      if (!clip) return;

      if (drag.mode === "move") {
        var rawStart = R.xToTime(dom, state, ev.clientX) - drag.offsetX;
        var snapped = M.snapTime(state, rawStart, clip.id);
        if (state.snap) {
          var endSnap = M.snapTime(state, rawStart + clip.duration, clip.id) - clip.duration;
          if (Math.abs(endSnap - rawStart) < Math.abs(snapped - rawStart)) snapped = endSnap;
        }
        var trackId = clip.trackId;
        var laneEl = document.elementFromPoint(ev.clientX, ev.clientY);
        var lane = laneEl && laneEl.closest && laneEl.closest(".nle-lane");
        if (lane && lane.dataset.trackId) trackId = lane.dataset.trackId;
        var trackChanged = trackId !== clip.trackId;
        M.moveClip(state, clip.id, Math.max(0, snapped), trackId, false, {
          silent: true,
        });
        patchClipEl(clip);
        preview.sync(state);
      } else if (drag.mode === "trim") {
        var t = R.xToTime(dom, state, ev.clientX);
        t = M.snapTime(state, t, clip.id);
        M.trimClip(state, clip.id, drag.edge, t, false, { silent: true });
        patchClipEl(clip);
        preview.sync(state);
      }
    });

    function endDrag(ev) {
      if (!drag) return;
      var clipEl = dom.lanes.querySelector('[data-clip-id="' + drag.clipId + '"]');
      try {
        if (clipEl) clipEl.releasePointerCapture(drag.pointerId);
      } catch (_) {}
      var moved = M.findClip(state, drag.clipId);
      drag = null;
      preview.setScrubbing(false);
      // Full render after drag (track moves / width / undo snapshot already taken)
      M.emit(state, "full");
      if (moved) patchClipEl(moved);
    }
    dom.lanes.addEventListener("pointerup", endDrag);
    dom.lanes.addEventListener("pointercancel", endDrag);

    // Sync header column vertical scroll with lane scroll
    dom.scroll.addEventListener("scroll", function () {
      var rows = dom.headersCol.querySelectorAll(".nle-header");
      for (var i = 0; i < rows.length; i++) {
        rows[i].style.transform = "translateY(" + -dom.scroll.scrollTop + "px)";
      }
    });

    // Drag-drop files onto lanes
    dom.lanes.addEventListener("dragover", function (ev) {
      ev.preventDefault();
      ev.dataTransfer.dropEffect = "copy";
      var lane = ev.target.closest && ev.target.closest(".nle-lane");
      if (lane) lane.classList.add("is-drop");
    });
    dom.lanes.addEventListener("dragleave", function (ev) {
      var lane = ev.target.closest && ev.target.closest(".nle-lane");
      if (lane) lane.classList.remove("is-drop");
    });
    dom.lanes.addEventListener("drop", function (ev) {
      ev.preventDefault();
      var lane = ev.target.closest && ev.target.closest(".nle-lane");
      dom.lanes.querySelectorAll(".is-drop").forEach(function (el) {
        el.classList.remove("is-drop");
      });
      if (!lane) return;
      var trackId = lane.dataset.trackId;
      var at = R.xToTime(dom, state, ev.clientX);
      var files = ev.dataTransfer && ev.dataTransfer.files;
      if (files && files.length) {
        M.addClipsFromFiles(state, trackId, files, at);
      }
    });

    // Also allow drop on empty state / body to create track
    dom.root.addEventListener("dragover", function (ev) {
      if (ev.dataTransfer && ev.dataTransfer.types.indexOf("Files") >= 0) {
        ev.preventDefault();
      }
    });
    dom.root.addEventListener("drop", function (ev) {
      if (!ev.dataTransfer || !ev.dataTransfer.files || !ev.dataTransfer.files.length) return;
      if (ev.target.closest && ev.target.closest(".nle-lane")) return;
      ev.preventDefault();
      if (!state.tracks.length) M.addTrack(state);
      var trackId = state.tracks[state.tracks.length - 1].id;
      M.addClipsFromFiles(state, trackId, ev.dataTransfer.files, state.playhead);
    });

    window.addEventListener("keydown", function (ev) {
      var tag = (ev.target && ev.target.tagName) || "";
      if (tag === "INPUT" || tag === "TEXTAREA") return;

      if (ev.code === "Space") {
        ev.preventDefault();
        state.playing = !state.playing;
        if (state.playing) {
          preview.startClock(state, function () {
            R.renderPlayhead(dom, state);
            R.followPlayhead(dom, state);
            preview.sync(state);
          });
        }
        M.emit(state);
        return;
      }
      if (ev.key === "Delete" || ev.key === "Backspace") {
        if (M.deleteSelection(state)) ev.preventDefault();
        return;
      }
      if (ev.key === "s" || ev.key === "S") {
        if (!ev.ctrlKey && !ev.metaKey) {
          if (M.splitAtPlayhead(state)) ev.preventDefault();
        }
        return;
      }
      if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "z") {
        ev.preventDefault();
        if (ev.shiftKey) M.redo(state);
        else M.undo(state);
        return;
      }
      if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "y") {
        ev.preventDefault();
        M.redo(state);
      }
    });

    preview.startClock(state, function () {
      R.renderPlayhead(dom, state);
      R.followPlayhead(dom, state);
      preview.sync(state);
    });

    refresh();
  }

  global.TimelineInteract = {
    bindInteractions: bindInteractions,
  };
})(window);
