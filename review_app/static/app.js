/* aqfilter listening-review front-end.
 * Vanilla JS, no build step. State is mirrored to localStorage and autosaved
 * to the server via POST /api/answers.
 */
(function () {
  "use strict";

  var CONFIG = null;
  var answers = null;
  var currentReciter = null;
  var currentGroup = "above";
  var activeIndex = 0;
  var saveTimer = null;
  var STORE_KEY = null;

  var player = document.getElementById("player");
  var playingClipId = null;

  // ---------------------------------------------------------------- utilities
  function el(tag, props, children) {
    var node = document.createElement(tag);
    if (props) {
      Object.keys(props).forEach(function (k) {
        if (k === "class") node.className = props[k];
        else if (k === "text") node.textContent = props[k];
        else if (k === "html") node.innerHTML = props[k];
        else if (k === "dataset") Object.assign(node.dataset, props[k]);
        else if (k.startsWith("on")) node.addEventListener(k.slice(2), props[k]);
        else if (props[k] !== null && props[k] !== undefined && props[k] !== false) {
          node.setAttribute(k, props[k]);
        }
      });
    }
    (children || []).forEach(function (c) {
      if (c === null || c === undefined) return;
      node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return node;
  }

  function fmtMetric(key, val) {
    if (val === null || val === undefined || isNaN(val)) return "—";
    if (key === "bandwidth_hz") {
      return val >= 1000 ? (val / 1000).toFixed(1) + " kHz" : Math.round(val) + " Hz";
    }
    if (key === "duration_s") return val.toFixed(1) + "s";
    if (key === "ovrl_mos" || key === "sig_mos" || key === "bak_mos" || key === "p808_mos") {
      return val.toFixed(2);
    }
    return val.toFixed(2);
  }

  function failedMetrics(clip) {
    return (clip.fail_reason || []).map(function (s) {
      return String(s).split(/[<>]/)[0].trim();
    });
  }

  function findReciter(name) {
    for (var i = 0; i < CONFIG.reciters.length; i++) {
      if (CONFIG.reciters[i].name === name) return CONFIG.reciters[i];
    }
    return null;
  }

  function flatClips(rec, group) {
    return (rec && rec.groups[group]) || [];
  }

  // ------------------------------------------------------------------- state
  function ensureReciter(name) {
    if (!answers.reciters[name]) {
      answers.reciters[name] = { verdict: "", metrics_suspect: [], notes: "", clips: {} };
    }
    return answers.reciters[name];
  }

  function clipAnswer(clipId) {
    var r = ensureReciter(currentReciter);
    if (!r.clips[clipId]) r.clips[clipId] = { verdict: "", note: "" };
    return r.clips[clipId];
  }

  function countAnswered() {
    var total = 0, rated = 0;
    CONFIG.reciters.forEach(function (rec) {
      CONFIG.groups.forEach(function (g) {
        flatClips(rec, g).forEach(function (c) {
          total++;
          var r = answers.reciters[rec.name];
          if (r && r.clips[c.id] && r.clips[c.id].verdict) rated++;
        });
      });
    });
    return { total: total, rated: rated };
  }

  function answersWeight(a) {
    if (!a || !a.reciters) return 0;
    var w = 0;
    Object.keys(a.reciters).forEach(function (name) {
      var r = a.reciters[name];
      if (!r) return;
      if (r.verdict) w += 5;
      Object.keys(r.clips || {}).forEach(function (id) {
        if (r.clips[id].verdict) w += 1;
        if (r.clips[id].note) w += 1;
      });
    });
    return w;
  }

  function setSaveStatus(text, cls) {
    var s = document.getElementById("save-status");
    s.textContent = text;
    s.className = "save-status" + (cls ? " " + cls : "");
  }

  function save(immediate) {
    if (STORE_KEY) {
      try { localStorage.setItem(STORE_KEY, JSON.stringify(answers)); } catch (e) {}
    }
    setSaveStatus("saving…", "saving");
    clearTimeout(saveTimer);
    saveTimer = setTimeout(function () {
      fetch("/api/answers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(answers),
      })
        .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
        .then(function () { setSaveStatus("saved"); })
        .catch(function () { setSaveStatus("save failed (kept locally)", "error"); });
    }, immediate ? 0 : 700);
  }

  // ------------------------------------------------------------------ player
  function togglePlay(clip) {
    if (playingClipId === clip.id) {
      if (player.paused) player.play();
      else player.pause();
      return;
    }
    playingClipId = clip.id;
    player.src = clip.audio_url;
    player.play().catch(function () {});
    refreshPlayingUI();
  }

  function refreshPlayingUI() {
    var cards = document.querySelectorAll(".clip");
    Array.prototype.forEach.call(cards, function (card) {
      var isCurrent = card.dataset.id === playingClipId;
      var playing = isCurrent && !player.paused && !player.ended;
      card.classList.toggle("playing", playing);
      var btn = card.querySelector(".play-btn");
      if (btn) btn.textContent = playing ? "❚❚" : "▶";
    });
  }

  player.addEventListener("play", refreshPlayingUI);
  player.addEventListener("pause", refreshPlayingUI);
  player.addEventListener("ended", function () { playingClipId = null; refreshPlayingUI(); });

  // ------------------------------------------------------------- rendering
  function renderNav() {
    var nav = document.getElementById("reciter-nav");
    nav.innerHTML = "";
    CONFIG.reciters.forEach(function (rec) {
      var r = answers.reciters[rec.name] || {};
      var n = flatClips(rec, "above").length +
        flatClips(rec, "below").length +
        flatClips(rec, "random_rejects").length;
      var dot = el("span", { class: "verdict-dot " + (r.verdict || "") });
      var item = el("div", {
        class: "nav-item" + (rec.name === currentReciter ? " active" : ""),
        onclick: function () {
          currentReciter = rec.name;
          currentGroup = "above";
          activeIndex = 0;
          renderNav();
          renderMain();
        },
      }, [
        el("span", { text: rec.name, style: "flex:1" }),
        el("span", { class: "muted small", text: (r.verdict ? "✓ " : "") + n }),
        dot,
      ]);
      nav.appendChild(item);
    });
  }

  function renderProgress() {
    var c = countAnswered();
    document.getElementById("progress-bar").style.width =
      (c.total ? (c.rated / c.total) * 100 : 0) + "%";
    document.getElementById("progress-text").textContent = c.rated + " / " + c.total + " clips";
  }

  function metricRow(clip) {
    var failed = failedMetrics(clip);
    var row = el("div", { class: "metrics" });
    CONFIG.metric_order.forEach(function (key) {
      if (!(key in (clip.metrics || {}))) return;
      var isFail = failed.indexOf(key) !== -1;
      row.appendChild(el("span", { class: "metric" + (isFail ? " failed" : "") }, [
        CONFIG.metric_label[key] || key, ": ", el("b", { text: fmtMetric(key, clip.metrics[key]) }),
      ]));
    });
    return row;
  }

  function clipCard(clip, idx) {
    var ans = clipAnswer(clip.id);
    var card = el("div", { class: "clip", dataset: { id: clip.id, idx: String(idx) } });

    var playBtn = el("button", {
      class: "play-btn", title: "Play (space)", text: "▶",
      onclick: function () { togglePlay(clip); },
    });
    var header = el("div", { class: "clip-header" }, [
      playBtn,
      el("span", { class: "clip-rank", text: "#" + (clip.rank || idx + 1) }),
      el("span", { class: "clip-name", text: clip.copied_name || clip.filename }),
    ]);
    card.appendChild(header);

    if (CONFIG.has_metrics) card.appendChild(metricRow(clip));

    var badges = el("div", { class: "badges" });
    if ((clip.fail_reason || []).length) {
      clip.fail_reason.forEach(function (reason) {
        badges.appendChild(el("span", { class: "badge", text: "failed: " + reason }));
      });
    } else {
      badges.appendChild(el("span", { class: "badge neutral", text: "passes all checks" }));
    }
    card.appendChild(badges);

    var rateRow = el("div", { class: "rate-row" });
    CONFIG.questions.clip_verdict.options.forEach(function (opt) {
      var b = el("button", {
        class: "rate-btn" + (ans.verdict === opt.value ? " selected" : ""),
        dataset: { rate: opt.value },
        text: opt.label,
        onclick: function () {
          ans.verdict = ans.verdict === opt.value ? "" : opt.value;
          updateCardButtons(card, ans);
          updateReciterAnswered();
          renderProgress();
          save();
        },
      });
      rateRow.appendChild(b);
    });
    card.appendChild(rateRow);

    var noteInput = el("input", {
      type: "text", placeholder: CONFIG.questions.free_text.clip,
      value: ans.note || "",
      oninput: function () { ans.note = this.value; save(); },
    });
    card.appendChild(el("div", { class: "clip-note" }, [noteInput]));
    return card;
  }

  function updateCardButtons(card, ans) {
    var btns = card.querySelectorAll(".rate-btn");
    Array.prototype.forEach.call(btns, function (b) {
      b.classList.toggle("selected", b.dataset.rate === ans.verdict);
    });
  }

  function verdictPanel(rec) {
    var r = ensureReciter(rec.name);
    var panel = el("div", { class: "verdict-panel" });
    panel.appendChild(el("h2", { text: CONFIG.questions.reciter_verdict.prompt }));

    var buttons = el("div", { class: "verdict-buttons" });
    CONFIG.verdicts.forEach(function (v) {
      var btn = el("button", {
        class: "verdict-btn" + (r.verdict === v.value ? " selected" : ""),
        dataset: { verdict: v.value },
        onclick: function () {
          r.verdict = r.verdict === v.value ? "" : v.value;
          var all = panel.querySelectorAll(".verdict-btn");
          Array.prototype.forEach.call(all, function (b) {
            b.classList.toggle("selected", b.dataset.verdict === r.verdict);
          });
          renderNav();
          save();
        },
      }, [
        el("span", { text: v.label }),
        el("small", { text: v.hint }),
      ]);
      buttons.appendChild(btn);
    });
    panel.appendChild(buttons);

    panel.appendChild(el("div", { class: "suspect-row" }, [
      el("span", { class: "muted small", text: CONFIG.questions.metrics_suspect.prompt + " " }),
      (function () {
        var wrap = document.createDocumentFragment();
        CONFIG.questions.metrics_suspect.options.forEach(function (opt) {
          var chip = el("span", {
            class: "chip" + (r.metrics_suspect.indexOf(opt) !== -1 ? " selected" : ""),
            text: opt,
            onclick: function () {
              var i = r.metrics_suspect.indexOf(opt);
              if (i !== -1) {
                r.metrics_suspect.splice(i, 1);
              } else {
                if (opt === "none" || opt === "unsure") {
                  r.metrics_suspect = [opt];
                } else {
                  r.metrics_suspect = r.metrics_suspect.filter(function (x) {
                    return x !== "none" && x !== "unsure";
                  });
                  r.metrics_suspect.push(opt);
                }
              }
              var chips = panel.querySelectorAll(".chip");
              Array.prototype.forEach.call(chips, function (c) {
                c.classList.toggle("selected", r.metrics_suspect.indexOf(c.textContent) !== -1);
              });
              save();
            },
          });
          wrap.appendChild(chip);
        });
        return wrap;
      })(),
    ]));

    var notes = el("textarea", {
      rows: 2, placeholder: CONFIG.questions.free_text.reciter,
      oninput: function () { r.notes = this.value; save(); },
    });
    notes.value = r.notes || "";
    panel.appendChild(notes);
    return panel;
  }

  function updateReciterAnswered() {
    // no-op hook kept for clarity; nav is re-rendered on demand
  }

  function renderMain() {
    var main = document.getElementById("main");
    main.innerHTML = "";
    var rec = findReciter(currentReciter);
    if (!rec) return;

    main.appendChild(el("div", { class: "reciter-header" }, [
      el("h1", { text: rec.name }),
      el("span", { class: "muted small", text: "listen, then answer below" }),
    ]));

    main.appendChild(verdictPanel(rec));

    var tabs = el("div", { class: "group-tabs" });
    CONFIG.groups.forEach(function (g) {
      var clips = flatClips(rec, g);
      var rated = clips.filter(function (c) {
        var r = answers.reciters[rec.name];
        return r && r.clips[c.id] && r.clips[c.id].verdict;
      }).length;
      tabs.appendChild(el("button", {
        class: "group-tab" + (g === currentGroup ? " active" : ""),
        html: g + " <span class='count'>(" + rated + "/" + clips.length + ")</span>",
        onclick: function () {
          currentGroup = g;
          activeIndex = 0;
          renderMain();
        },
      }));
    });
    main.appendChild(tabs);

    var blurb = CONFIG.group_blurb[currentGroup] || {};
    main.appendChild(el("div", {
      class: "group-blurb",
      html: "<b>" + blurb.title + "</b> — " + blurb.hint,
    }));

    var list = el("div", { class: "clip-list" });
    flatClips(rec, currentGroup).forEach(function (clip, idx) {
      list.appendChild(clipCard(clip, idx));
    });
    main.appendChild(list);
    setActiveCard();
  }

  function setActiveCard() {
    var cards = document.querySelectorAll(".clip");
    Array.prototype.forEach.call(cards, function (c, i) {
      c.classList.toggle("active", i === activeIndex);
    });
  }

  // --------------------------------------------------------------- keyboard
  function bindKeyboard() {
    document.addEventListener("keydown", function (e) {
      var tag = (e.target.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea") return;
      var rec = findReciter(currentReciter);
      if (!rec) return;
      var clips = flatClips(rec, currentGroup);
      var clip = clips[activeIndex];
      if (e.key === " " && clip) {
        e.preventDefault();
        togglePlay(clip);
      } else if ((e.key === "ArrowDown" || e.key === "ArrowRight") && clips.length) {
        e.preventDefault();
        activeIndex = Math.min(activeIndex + 1, clips.length - 1);
        setActiveCard();
        scrollActive();
      } else if ((e.key === "ArrowUp" || e.key === "ArrowLeft") && clips.length) {
        e.preventDefault();
        activeIndex = Math.max(activeIndex - 1, 0);
        setActiveCard();
        scrollActive();
      } else if (clip && (e.key === "g" || e.key === "b" || e.key === "u")) {
        var map = { g: "good", b: "bad", u: "unsure" };
        var ans = clipAnswer(clip.id);
        ans.verdict = ans.verdict === map[e.key] ? "" : map[e.key];
        var card = document.querySelector('.clip[data-id="' + CSS.escape(clip.id) + '"]');
        if (card) updateCardButtons(card, ans);
        renderProgress();
        save();
      }
    });
  }

  function scrollActive() {
    var card = document.querySelector(".clip.active");
    if (card) card.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  // ----------------------------------------------------------------- export
  function doExport() {
    setSaveStatus("exporting…", "saving");
    fetch("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answers: answers }),
    })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (data) {
        setSaveStatus("saved");
        var modal = document.getElementById("export-modal");
        document.getElementById("export-summary").innerHTML =
          "<p><b>" + data.totals.clips_rated + " / " + data.totals.clips +
          "</b> clips rated · <b>" + data.totals.reciters_answered + " / " +
          data.totals.reciters + "</b> reciters answered · complete: <b>" +
          (data.complete ? "yes" : "no") + "</b></p>" +
          "<p class='muted small'>Saved to <code>" + data.saved_to.json +
          "</code> and <code>" + data.saved_to.markdown + "</code>.</p>";
        document.getElementById("export-preview").textContent = data.markdown;
        modal.classList.remove("hidden");
        // auto-download the markdown
        var a = document.createElement("a");
        a.href = "/download/review_report.md";
        a.download = "review_report.md";
        document.body.appendChild(a);
        a.click();
        a.remove();
      })
      .catch(function (err) {
        setSaveStatus("export failed", "error");
        alert("Export failed: " + err.message);
      });
  }

  // ------------------------------------------------------------------- init
  function mergeAnswers(server, local) {
    // pick the richer of the two; server wins ties
    var sw = answersWeight(server), lw = answersWeight(local);
    return lw > sw ? local : server;
  }

  function init() {
    fetch("/api/config")
      .then(function (r) { return r.json(); })
      .then(function (cfg) {
        CONFIG = cfg;
        STORE_KEY = "aqfilter_review_v1::" + cfg.root;
        var local = null;
        try { local = JSON.parse(localStorage.getItem(STORE_KEY) || "null"); } catch (e) {}
        answers = mergeAnswers(cfg.answers || { reciters: {} }, local);
        if (!answers.reciters) answers.reciters = {};
        if (!answers.global_notes) answers.global_notes = "";
        if (!answers.reviewer) answers.reviewer = "";

        if (!CONFIG.has_metrics) {
          var b = document.getElementById("banner");
          b.textContent = "No review.csv metrics found — the app will still collect your verdicts.";
          b.classList.remove("hidden");
        }
        currentReciter = CONFIG.reciters[0] ? CONFIG.reciters[0].name : null;
        renderNav();
        renderMain();
        renderProgress();
        bindKeyboard();
        document.getElementById("export-btn").addEventListener("click", doExport);
        document.getElementById("close-modal").addEventListener("click", function () {
          document.getElementById("export-modal").classList.add("hidden");
        });
      })
      .catch(function (err) {
        document.getElementById("main").innerHTML =
          "<div class='loading'>Failed to load /api/config: " + err.message + "</div>";
      });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
