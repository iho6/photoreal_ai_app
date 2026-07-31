(function (global) {
  "use strict";

  var STORAGE_KEY = "photoreal.character.gallery.v1";

  function uid(prefix) {
    return (prefix || "g") + "_" + Math.random().toString(36).slice(2, 9);
  }

  function loadLayout() {
    try {
      var raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return { items: [] };
      var data = JSON.parse(raw);
      if (!data || !Array.isArray(data.items)) return { items: [] };
      return data;
    } catch (_) {
      return { items: [] };
    }
  }

  function saveLayout(layout) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(layout));
    } catch (_) {}
  }

  /**
   * Merge server gallery images into local layout (order + groups).
   * layout.items: [{type:'image', id, url} | {type:'group', id, members:[{id,url}]}]
   */
  function mergeServerItems(layout, serverItems) {
    var byId = {};
    (serverItems || []).forEach(function (it) {
      byId[it.id] = it;
    });

    var seen = {};
    var next = [];

    function keepImage(img) {
      var srv = byId[img.id];
      if (!srv) return null;
      seen[img.id] = true;
      return { type: "image", id: srv.id, url: srv.url };
    }

    (layout.items || []).forEach(function (entry) {
      if (entry.type === "image") {
        var img = keepImage(entry);
        if (img) next.push(img);
      } else if (entry.type === "group") {
        var members = [];
        (entry.members || []).forEach(function (m) {
          var kept = keepImage(m);
          if (kept) members.push(kept);
        });
        if (members.length === 1) next.push(members[0]);
        else if (members.length > 1) {
          next.push({
            type: "group",
            id: entry.id || uid("grp"),
            members: members,
            expanded: !!entry.expanded,
          });
        }
      }
    });

    (serverItems || []).forEach(function (it) {
      if (!seen[it.id]) {
        next.unshift({ type: "image", id: it.id, url: it.url });
      }
    });

    return { items: next };
  }

  function findImageUrl(layout, imageId) {
    for (var i = 0; i < layout.items.length; i++) {
      var e = layout.items[i];
      if (e.type === "image" && e.id === imageId) return e.url;
      if (e.type === "group") {
        for (var j = 0; j < e.members.length; j++) {
          if (e.members[j].id === imageId) return e.members[j].url;
        }
      }
    }
    return null;
  }

  function mountGallery(opts) {
    var root = opts.root;
    var onSelect = opts.onSelect || function () {};
    var layout = opts.layout || { items: [] };
    var selectedId = opts.selectedId || null;

    function setLayout(next) {
      layout = next;
      saveLayout(layout);
      render();
    }

    function render() {
      root.innerHTML = "";
      var grid = document.createElement("div");
      grid.className = "ch-gallery-grid";

      layout.items.forEach(function (entry, index) {
        if (entry.type === "image") {
          grid.appendChild(makeImageThumb(entry, index, null));
        } else if (entry.type === "group") {
          grid.appendChild(makeGroupThumb(entry, index));
          if (entry.expanded) {
            var expand = document.createElement("div");
            expand.className = "ch-group-expand";
            entry.members.forEach(function (m, mi) {
              expand.appendChild(makeImageThumb(m, index, mi));
            });
            grid.appendChild(expand);
          }
        }
      });

      root.appendChild(grid);
      bindDrag(grid);
    }

    function makeImageThumb(entry, index, memberIndex) {
      var el = document.createElement("div");
      el.className = "ch-thumb";
      el.dataset.kind = "image";
      el.dataset.id = entry.id;
      el.dataset.index = String(index);
      if (memberIndex != null) el.dataset.memberIndex = String(memberIndex);
      if (selectedId === entry.id) el.dataset.selected = "true";
      var img = document.createElement("img");
      img.src = entry.url;
      img.alt = "";
      el.appendChild(img);
      el.addEventListener("click", function (ev) {
        if (el.dataset.didDrag === "true") {
          el.dataset.didDrag = "false";
          return;
        }
        selectedId = entry.id;
        onSelect(entry);
        render();
      });
      return el;
    }

    function makeGroupThumb(entry, index) {
      var el = document.createElement("div");
      el.className = "ch-thumb ch-thumb--group";
      el.dataset.kind = "group";
      el.dataset.id = entry.id;
      el.dataset.index = String(index);
      var cover = entry.members[0];
      if (cover) {
        var s1 = document.createElement("div");
        s1.className = "ch-thumb__stack";
        var i1 = document.createElement("img");
        i1.src = cover.url;
        i1.alt = "";
        s1.appendChild(i1);
        el.appendChild(s1);
      }
      if (entry.members[1]) {
        var s2 = document.createElement("div");
        s2.className = "ch-thumb__stack";
        var i2 = document.createElement("img");
        i2.src = entry.members[1].url;
        i2.alt = "";
        s2.appendChild(i2);
        el.appendChild(s2);
      }
      var count = document.createElement("span");
      count.className = "ch-thumb__count";
      count.textContent = String(entry.members.length);
      el.appendChild(count);
      el.addEventListener("click", function () {
        if (el.dataset.didDrag === "true") {
          el.dataset.didDrag = "false";
          return;
        }
        entry.expanded = !entry.expanded;
        setLayout({ items: layout.items.slice() });
      });
      return el;
    }

    function indexFromPoint(clientX, clientY) {
      var thumbs = root.querySelectorAll(".ch-gallery-grid > .ch-thumb");
      for (var i = 0; i < thumbs.length; i++) {
        var r = thumbs[i].getBoundingClientRect();
        if (
          clientX >= r.left &&
          clientX <= r.right &&
          clientY >= r.top &&
          clientY <= r.bottom
        ) {
          return {
            el: thumbs[i],
            index: parseInt(thumbs[i].dataset.index, 10),
            kind: thumbs[i].dataset.kind,
            id: thumbs[i].dataset.id,
            rect: r,
          };
        }
      }
      return null;
    }

    function overlapRatio(a, b) {
      var x1 = Math.max(a.left, b.left);
      var y1 = Math.max(a.top, b.top);
      var x2 = Math.min(a.right, b.right);
      var y2 = Math.min(a.bottom, b.bottom);
      var w = Math.max(0, x2 - x1);
      var h = Math.max(0, y2 - y1);
      var inter = w * h;
      var area = Math.min(
        (a.right - a.left) * (a.bottom - a.top),
        (b.right - b.left) * (b.bottom - b.top)
      );
      return area ? inter / area : 0;
    }

    function bindDrag(grid) {
      var drag = null;

      grid.addEventListener("pointerdown", function (ev) {
        if (ev.button != null && ev.button !== 0) return;
        var thumb = ev.target.closest && ev.target.closest(".ch-thumb");
        if (!thumb || !grid.contains(thumb)) return;
        if (thumb.closest(".ch-group-expand")) {
          // member drag: ungroup later on drop outside
        }
        drag = {
          el: thumb,
          startX: ev.clientX,
          startY: ev.clientY,
          moved: false,
          fromIndex: parseInt(thumb.dataset.index, 10),
          kind: thumb.dataset.kind,
          id: thumb.dataset.id,
          memberIndex:
            thumb.dataset.memberIndex != null
              ? parseInt(thumb.dataset.memberIndex, 10)
              : null,
          pointerId: ev.pointerId,
        };
        thumb.setPointerCapture(ev.pointerId);
        ev.preventDefault();
      });

      grid.addEventListener("pointermove", function (ev) {
        if (!drag) return;
        var dx = ev.clientX - drag.startX;
        var dy = ev.clientY - drag.startY;
        if (!drag.moved && dx * dx + dy * dy < 36) return;
        drag.moved = true;
        drag.el.dataset.dragging = "true";
        drag.el.dataset.didDrag = "true";

        root.querySelectorAll(".ch-thumb[data-merge]").forEach(function (el) {
          el.removeAttribute("data-merge");
        });

        var hit = indexFromPoint(ev.clientX, ev.clientY);
        if (hit && hit.id !== drag.id) {
          var r = drag.el.getBoundingClientRect();
          if (overlapRatio(r, hit.rect) > 0.35 || hit.kind === "group") {
            hit.el.dataset.merge = "true";
            drag.mergeTarget = hit;
          } else {
            drag.mergeTarget = null;
            drag.insertIndex = hit.index;
          }
        } else {
          drag.mergeTarget = null;
        }
      });

      function endDrag(ev) {
        if (!drag) return;
        try {
          drag.el.releasePointerCapture(drag.pointerId);
        } catch (_) {}
        drag.el.removeAttribute("data-dragging");
        root.querySelectorAll(".ch-thumb[data-merge]").forEach(function (el) {
          el.removeAttribute("data-merge");
        });

        if (!drag.moved) {
          drag = null;
          return;
        }

        var items = layout.items.slice();
        var from = drag.fromIndex;
        var memberIndex = drag.memberIndex;

        // Dragging a member out of an expanded group
        if (memberIndex != null && items[from] && items[from].type === "group") {
          var grp = items[from];
          var member = grp.members.splice(memberIndex, 1)[0];
          if (!member) {
            drag = null;
            render();
            return;
          }
          if (grp.members.length === 1) {
            items[from] = grp.members[0];
          } else if (grp.members.length === 0) {
            items.splice(from, 1);
          }
          if (drag.mergeTarget && drag.mergeTarget.id !== member.id) {
            items = mergeOnto(items, member, drag.mergeTarget.index);
          } else {
            var insertAt =
              drag.insertIndex != null ? drag.insertIndex : items.length;
            items.splice(insertAt, 0, member);
          }
          setLayout({ items: items });
          drag = null;
          return;
        }

        var moving = items[from];
        if (!moving) {
          drag = null;
          render();
          return;
        }

        if (drag.mergeTarget && drag.mergeTarget.index !== from) {
          items.splice(from, 1);
          var targetIdx = drag.mergeTarget.index;
          if (targetIdx > from) targetIdx -= 1;
          items = mergeOnto(items, moving, targetIdx);
          setLayout({ items: items });
        } else if (drag.insertIndex != null && drag.insertIndex !== from) {
          items.splice(from, 1);
          var to = drag.insertIndex;
          if (to > from) to -= 1;
          items.splice(to, 0, moving);
          setLayout({ items: items });
        } else {
          render();
        }
        drag = null;
      }

      grid.addEventListener("pointerup", endDrag);
      grid.addEventListener("pointercancel", endDrag);
    }

    function mergeOnto(items, moving, targetIndex) {
      var target = items[targetIndex];
      if (!target) {
        items.push(normalizeEntry(moving));
        return items;
      }
      var members = [];
      function pushEntry(e) {
        if (e.type === "image") members.push({ id: e.id, url: e.url });
        else if (e.type === "group") {
          e.members.forEach(function (m) {
            members.push({ id: m.id, url: m.url });
          });
        }
      }
      pushEntry(target);
      pushEntry(moving);
      // dedupe
      var seen = {};
      members = members.filter(function (m) {
        if (seen[m.id]) return false;
        seen[m.id] = true;
        return true;
      });
      items[targetIndex] = {
        type: "group",
        id: target.type === "group" ? target.id : uid("grp"),
        members: members,
        expanded: false,
      };
      return items;
    }

    function normalizeEntry(e) {
      if (e.type === "group") return e;
      return { type: "image", id: e.id, url: e.url };
    }

    function addImages(images) {
      var items = layout.items.slice();
      (images || []).forEach(function (img) {
        var exists = items.some(function (e) {
          if (e.type === "image") return e.id === img.id;
          return e.members && e.members.some(function (m) {
            return m.id === img.id;
          });
        });
        if (!exists) {
          items.unshift({ type: "image", id: img.id, url: img.url });
        }
      });
      setLayout({ items: items });
      if (images && images[0]) {
        selectedId = images[0].id;
        onSelect(images[0]);
      }
    }

    function syncFromServer(serverItems) {
      layout = mergeServerItems(layout, serverItems);
      saveLayout(layout);
      render();
    }

    render();

    return {
      addImages: addImages,
      syncFromServer: syncFromServer,
      getLayout: function () {
        return layout;
      },
      setSelected: function (id) {
        selectedId = id;
        render();
      },
    };
  }

  global.CharacterGallery = {
    loadLayout: loadLayout,
    saveLayout: saveLayout,
    mergeServerItems: mergeServerItems,
    findImageUrl: findImageUrl,
    mountGallery: mountGallery,
  };
})(window);
