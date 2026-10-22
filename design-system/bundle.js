/* @ds-bundle: {"format":4,"namespace":"Heng","components":[{"name":"Button"},{"name":"Badge"},{"name":"Tabs"},{"name":"CountUp"},{"name":"Sparkline"},{"name":"MetricCard"},{"name":"ScoreRing"},{"name":"Leaderboard"},{"name":"Radar"},{"name":"RunProgress"},{"name":"ArenaCompare"},{"name":"Dashboard"}]} */
(function () {
  var React = window.React, h = React.createElement;
  var useState = React.useState, useEffect = React.useEffect, useRef = React.useRef;
  var RM = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  var TONES = ['signal', 'coral', 'teal', 'amber'];

  function cx() { return Array.prototype.filter.call(arguments, Boolean).join(' '); }
  function easeOut(t) { return 1 - Math.pow(1 - t, 3); }
  function fmt(v, d) { return Number(v).toLocaleString('en-US', { minimumFractionDigits: d || 0, maximumFractionDigits: d || 0 }); }
  function omit(o, keys) { var r = {}; for (var k in o) if (keys.indexOf(k) < 0) r[k] = o[k]; return r; }

  /* ---------- motion hooks ---------- */
  function useTween(target, duration, delay) {
    var s = useState(RM ? target : 0), v = s[0], set = s[1];
    var cur = useRef(RM ? target : 0);
    useEffect(function () {
      if (RM) { cur.current = target; set(target); return; }
      var f = cur.current, start = null, raf, d = duration || 1200;
      function step(ts) {
        if (start === null) start = ts;
        var t = Math.min(1, (ts - start) / d), n = f + (target - f) * easeOut(t);
        cur.current = n; set(n);
        if (t < 1) raf = requestAnimationFrame(step);
      }
      var timer = setTimeout(function () { raf = requestAnimationFrame(step); }, delay || 0);
      return function () { clearTimeout(timer); cancelAnimationFrame(raf); };
    }, [target]);
    return v;
  }
  function useTweenArr(target, duration) {
    var key = target.join(',');
    var s = useState(function () { return RM ? target.slice() : target.map(function () { return 0; }); }), v = s[0], set = s[1];
    var cur = useRef(v);
    useEffect(function () {
      if (RM) { cur.current = target.slice(); set(target.slice()); return; }
      var f = cur.current.slice(), start = null, raf, d = duration || 900;
      function step(ts) {
        if (start === null) start = ts;
        var t = Math.min(1, (ts - start) / d), e = easeOut(t);
        var n = target.map(function (x, i) { var a = f[i] || 0; return a + (x - a) * e; });
        cur.current = n; set(n);
        if (t < 1) raf = requestAnimationFrame(step);
      }
      raf = requestAnimationFrame(step);
      return function () { cancelAnimationFrame(raf); };
    }, [key]);
    return v;
  }

  /* ---------- icons (internal) ---------- */
  var ICONS = {
    grid: 'M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z',
    trophy: 'M7 4h10v4a5 5 0 0 1-10 0zM7 6H4v1a3 3 0 0 0 3 3M17 6h3v1a3 3 0 0 1-3 3M12 13v4M8 20h8',
    play: 'M7 5l12 7-12 7z',
    arena: 'M5 5l14 14M19 5L5 19M4 16l4 4M16 20l4-4',
    db: 'M5 6c0-1.7 3.1-3 7-3s7 1.3 7 3-3.1 3-7 3-7-1.3-7-3zM5 6v12c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3',
    cube: 'M12 3l8 4.5v9L12 21l-8-4.5v-9zM12 12l8-4.5M12 12v9M12 12L4 7.5',
    gear: 'M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1',
    plus: 'M12 5v14M5 12h14',
    search: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-4-4',
    sun: 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5L19 19M5 19l1.5-1.5M17.5 6.5L19 5',
    moon: 'M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z',
    replay: 'M4 12a8 8 0 1 0 2.3-5.7M4 4v4h4'
  };
  function Icon(p) {
    return h('svg', { className: cx('hg-icon', p.className), width: p.size || 16, height: p.size || 16, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true },
      h('path', { d: ICONS[p.name] || '' }));
  }

  /* ---------- Button ---------- */
  function Button(p) {
    var r = useState([]), rip = r[0], setRip = r[1];
    var rest = omit(p, ['variant', 'size', 'loading', 'icon', 'className', 'children', 'onPointerDown']);
    function down(e) {
      if (!RM) {
        var b = e.currentTarget.getBoundingClientRect(), id = Date.now() + Math.random();
        setRip(function (a) { return a.concat([{ id: id, x: e.clientX - b.left, y: e.clientY - b.top }]); });
        setTimeout(function () { setRip(function (a) { return a.filter(function (q) { return q.id !== id; }); }); }, 650);
      }
      if (p.onPointerDown) p.onPointerDown(e);
    }
    return h('button', Object.assign({ type: 'button' }, rest, {
      className: cx('hg-btn', 'hg-btn-' + (p.variant || 'quiet'), 'hg-btn-' + (p.size || 'md'), p.loading && 'is-loading', p.className),
      disabled: p.disabled || p.loading, onPointerDown: down, 'aria-busy': p.loading ? true : undefined
    }),
      rip.map(function (q) { return h('span', { key: q.id, className: 'hg-ripple', style: { left: q.x, top: q.y } }); }),
      p.loading ? h('span', { className: 'hg-spin', 'aria-hidden': true }) : p.icon ? h(Icon, { name: p.icon }) : null,
      h('span', { className: 'hg-btn-t' }, p.children));
  }

  /* ---------- Badge ---------- */
  function Badge(p) {
    return h('span', { className: cx('hg-badge', 'hg-tone-' + (p.tone || 'neutral'), p.pulse && 'is-pulse', p.className) },
      p.dot !== false && h('i', { className: 'hg-badge-dot' }), p.children);
  }

  /* ---------- Tabs (sliding indicator) ---------- */
  function Tabs(p) {
    var refs = useRef([]), box = useRef(null);
    var s = useState({ l: 0, w: 0 }), ind = s[0], setInd = s[1];
    var idx = Math.max(0, p.items.findIndex(function (it) { return it.key === p.value; }));
    var idxRef = useRef(idx); idxRef.current = idx;
    function measure() { var el = refs.current[idxRef.current]; if (el) setInd({ l: el.offsetLeft, w: el.offsetWidth }); }
    useEffect(measure, [idx, p.items.length]);
    useEffect(function () {
      if (document.fonts && document.fonts.ready) document.fonts.ready.then(measure);
      var ro = window.ResizeObserver ? new ResizeObserver(measure) : null;
      if (ro && box.current) ro.observe(box.current);
      return function () { if (ro) ro.disconnect(); };
    }, []);
    return h('div', { className: cx('hg-tabs', p.className), role: 'tablist', ref: box },
      h('span', { className: 'hg-tabs-ind', style: { transform: 'translateX(' + ind.l + 'px)', width: ind.w } }),
      p.items.map(function (it, i) {
        return h('button', {
          key: it.key, type: 'button', role: 'tab', 'aria-selected': i === idx,
          ref: function (el) { refs.current[i] = el; }, className: cx('hg-tab', i === idx && 'is-on'),
          onClick: function () { if (p.onChange) p.onChange(it.key); }
        }, it.label);
      }));
  }

  /* ---------- CountUp ---------- */
  function CountUp(p) {
    var v = useTween(p.value, p.duration || 1200, p.delay || 0);
    return h('span', { className: cx('hg-num', p.className) }, (p.prefix || '') + fmt(v, p.decimals) + (p.suffix || ''));
  }

  function Delta(p) {
    var v = p.value || 0, tone = v > 0 ? 'up' : v < 0 ? 'down' : 'flat';
    return h('span', { className: 'hg-delta hg-delta-' + tone },
      v === 0 ? '—' : (v > 0 ? '▲ ' : '▼ ') + fmt(Math.abs(v), p.decimals || 0) + (p.suffix || ''));
  }

  /* ---------- Sparkline ---------- */
  function Sparkline(p) {
    var data = p.data || [0, 0], w = 200, ht = p.height || 40, tone = p.tone || 'signal';
    var min = Math.min.apply(null, data), max = Math.max.apply(null, data), rng = max - min || 1;
    var pts = data.map(function (d, i) { return [i * (w - 6) / (data.length - 1) + 3, ht - 4 - (d - min) / rng * (ht - 8)]; });
    var line = pts.map(function (q, i) { return (i ? 'L' : 'M') + q[0].toFixed(1) + ' ' + q[1].toFixed(1); }).join(' ');
    var area = line + ' L' + pts[pts.length - 1][0].toFixed(1) + ' ' + ht + ' L' + pts[0][0].toFixed(1) + ' ' + ht + ' Z';
    var last = pts[pts.length - 1];
    return h('svg', { className: cx('hg-spark', 'hg-tone-' + tone), width: p.width || '100%', height: ht, viewBox: '0 0 ' + w + ' ' + ht, preserveAspectRatio: 'none', 'aria-hidden': true },
      h('path', { className: 'hg-spark-area', d: area }),
      h('path', { className: 'hg-spark-line', d: line, pathLength: 1, vectorEffect: 'non-scaling-stroke' }),
      h('line', { className: 'hg-spark-dot', x1: last[0], y1: last[1], x2: last[0], y2: last[1], vectorEffect: 'non-scaling-stroke' }));
  }

  /* ---------- MetricCard ---------- */
  function MetricCard(p) {
    var i = p.index || 0;
    return h('div', { className: cx('hg-card', 'hg-metric', 'hg-enter'), style: { '--d': i * 90 + 'ms' } },
      h('div', { className: 'hg-metric-top' },
        h('span', { className: 'hg-label' }, p.label),
        p.delta != null && h(Delta, { value: p.delta, decimals: p.deltaDecimals, suffix: p.deltaSuffix })),
      h('div', { className: 'hg-metric-val' }, h(CountUp, { value: p.value, decimals: p.decimals, prefix: p.prefix, suffix: p.suffix, delay: i * 90 })),
      p.data && h(Sparkline, { data: p.data, tone: p.tone }),
      p.hint && h('div', { className: 'hg-hint' }, p.hint));
  }

  /* ---------- ScoreRing ---------- */
  function ScoreRing(p) {
    var size = p.size || 120, sw = p.stroke || 10, r = (size - sw) / 2, C = 2 * Math.PI * r, c = size / 2;
    var v = useTween(p.value, 1500, p.delay || 0);
    return h('div', { className: cx('hg-ring', 'hg-tone-' + (p.tone || 'signal')), style: { width: size, height: size } },
      h('svg', { width: size, height: size, viewBox: '0 0 ' + size + ' ' + size, 'aria-hidden': true },
        h('circle', { className: 'hg-ring-track', cx: c, cy: c, r: r, strokeWidth: sw }),
        h('circle', { className: 'hg-ring-bar', cx: c, cy: c, r: r, strokeWidth: sw, strokeDasharray: C.toFixed(2), strokeDashoffset: (C * (1 - v / 100)).toFixed(2), transform: 'rotate(-90 ' + c + ' ' + c + ')' })),
      h('div', { className: 'hg-ring-c' },
        h('b', { style: { fontSize: Math.round(size * 0.24) } }, fmt(v, p.decimals == null ? 1 : p.decimals)),
        p.label && h('small', null, p.label)));
  }

  /* ---------- Leaderboard ---------- */
  function Leaderboard(p) {
    var metrics = p.metrics || [{ key: 'overall', label: '综合' }];
    var sm = useState(metrics[0].key), m = sm[0], setM = sm[1];
    var sr = useState(RM), ready = sr[0], setReady = sr[1];
    useEffect(function () { if (RM) return; var t = setTimeout(function () { setReady(true); }, 80); return function () { clearTimeout(t); }; }, []);
    var rowH = p.rowHeight || 52, max = p.max || 100;
    var sorted = p.rows.slice().sort(function (a, b) { return b.scores[m] - a.scores[m]; });
    return h('div', { className: 'hg-lb' },
      metrics.length > 1 && h(Tabs, { items: metrics, value: m, onChange: setM }),
      h('div', { className: 'hg-lb-head' }, h('span', null, '#'), h('span', null, '模型'), h('span', null, (metrics.filter(function (x) { return x.key === m; })[0] || {}).label + ' 得分'), h('span', { className: 'hg-r' }, '周变化')),
      h('div', { className: 'hg-lb-body', style: { height: sorted.length * rowH } },
        p.rows.map(function (r, n) {
          var idx = sorted.indexOf(r), s = r.scores[m];
          return h('div', { key: r.model, className: cx('hg-lb-row', idx === 0 && 'is-top'), style: { transform: 'translateY(' + idx * rowH + 'px)', height: rowH, '--i': n } },
            h('span', { className: 'hg-lb-rank' }, idx + 1),
            h('span', { className: 'hg-lb-model' },
              h('span', { className: 'hg-avatar' }, r.model.slice(0, 1)),
              h('span', { className: 'hg-lb-name' }, h('b', null, r.model), h('small', null, r.org))),
            h('span', { className: 'hg-lb-score' },
              h('span', { className: 'hg-lb-track' }, h('span', { className: 'hg-lb-fill', style: { transform: 'scaleX(' + (ready ? s / max : 0) + ')', transitionDelay: (ready ? idx * 50 : 0) + 'ms' } })),
              h(CountUp, { value: s, decimals: 1, duration: 900 })),
            h('span', { className: 'hg-r' }, h(Delta, { value: r.delta })));
        })));
  }

  /* ---------- Radar ---------- */
  function RadarSeries(p) {
    var vals = useTweenArr(p.values.map(function (v) { return p.hidden ? 0 : v; }), 1000);
    var n = vals.length;
    var pts = vals.map(function (v, i) { var a = -Math.PI / 2 + i * 2 * Math.PI / n, r = v / 100 * p.R; return [p.c + Math.cos(a) * r, p.c + Math.sin(a) * r]; });
    return h('g', { className: cx('hg-radar-s', 'hg-tone-' + p.tone, p.dim && 'is-dim', p.hidden && 'is-off') },
      h('polygon', { points: pts.map(function (q) { return q[0].toFixed(1) + ',' + q[1].toFixed(1); }).join(' ') }),
      pts.map(function (q, i) { return h('circle', { key: i, cx: q[0].toFixed(1), cy: q[1].toFixed(1), r: 3 }); }));
  }
  function Radar(p) {
    var axes = p.axes, series = p.series, size = p.size || 300, c = size / 2, R = c - 46, n = axes.length;
    var sh = useState({}), hidden = sh[0], setHidden = sh[1];
    var sf = useState(null), focus = sf[0], setFocus = sf[1];
    function pt(i, r) { var a = -Math.PI / 2 + i * 2 * Math.PI / n; return [c + Math.cos(a) * r, c + Math.sin(a) * r]; }
    var rings = [0.25, 0.5, 0.75, 1].map(function (k) { return axes.map(function (_, i) { var q = pt(i, R * k); return q[0].toFixed(1) + ',' + q[1].toFixed(1); }).join(' '); });
    return h('div', { className: 'hg-radar' },
      h('svg', { width: size, height: size, viewBox: '0 0 ' + size + ' ' + size, role: 'img', 'aria-label': p.label || '模型能力雷达图' },
        h('g', { className: 'hg-radar-grid' }, rings.map(function (r, i) { return h('polygon', { key: i, points: r, style: { '--i': i } }); })),
        axes.map(function (a, i) {
          var e = pt(i, R), l = pt(i, R + 16), dx = l[0] - c;
          return h('g', { key: 'a' + i },
            h('line', { className: 'hg-radar-axis', x1: c, y1: c, x2: e[0].toFixed(1), y2: e[1].toFixed(1) }),
            h('text', { className: 'hg-radar-label', x: l[0].toFixed(1), y: l[1].toFixed(1), textAnchor: Math.abs(dx) < 4 ? 'middle' : dx > 0 ? 'start' : 'end', dominantBaseline: 'middle' }, a));
        }),
        series.map(function (s, i) { return h(RadarSeries, { key: s.name, values: s.values, tone: s.tone || TONES[i], R: R, c: c, hidden: !!hidden[s.name], dim: focus && focus !== s.name }); })),
      h('div', { className: 'hg-legend' }, series.map(function (s, i) {
        var off = !!hidden[s.name];
        return h('button', {
          key: s.name, type: 'button', className: cx('hg-legend-i', 'hg-tone-' + (s.tone || TONES[i]), off && 'is-off'), 'aria-pressed': !off,
          onMouseEnter: function () { setFocus(s.name); }, onMouseLeave: function () { setFocus(null); },
          onClick: function () { setHidden(function (o) { var x = Object.assign({}, o); x[s.name] = !o[s.name]; return x; }); }
        }, h('i'), s.name);
      })));
  }

  /* ---------- RunProgress ---------- */
  var STATUS = { running: ['signal', '运行中'], queued: ['amber', '排队中'], done: ['teal', '已完成'], failed: ['danger', '失败'] };
  function RunProgress(p) {
    var sj = useState(p.jobs), jobs = sj[0], setJobs = sj[1];
    var sl = useState([]), log = sl[0], setLog = sl[1];
    var seq = useRef(1280);
    useEffect(function () {
      if (!p.simulate || RM) return;
      var id = setInterval(function () {
        setJobs(function (js) {
          var running = js.filter(function (j) { return j.status === 'running'; }).length;
          if (!running) return p.jobs;
          return js.map(function (j) {
            if (j.status === 'queued' && running < 2) { running++; return Object.assign({}, j, { status: 'running' }); }
            if (j.status !== 'running') return j;
            var d = Math.min(j.total, j.done + Math.ceil(Math.random() * j.total * 0.02));
            return Object.assign({}, j, { done: d, status: d >= j.total ? 'done' : 'running' });
          });
        });
        var tasks = p.tasks || ['gsm8k', 'mmlu-pro', 'humaneval', 'c-eval', 'arena-hard'];
        seq.current += Math.ceil(Math.random() * 7);
        var ok = Math.random() > 0.12;
        setLog(function (L) {
          return [{ id: seq.current, task: tasks[seq.current % tasks.length], ok: ok, s: (ok ? 0.7 + Math.random() * 0.3 : Math.random() * 0.4).toFixed(2), t: (0.4 + Math.random() * 2).toFixed(1) }].concat(L).slice(0, 4);
        });
      }, 650);
      return function () { clearInterval(id); };
    }, [p.simulate]);
    return h('div', { className: 'hg-runs' },
      h('div', { className: 'hg-runs-list' }, jobs.map(function (j) {
        var st = STATUS[j.status] || STATUS.queued, pct = j.done / j.total * 100;
        return h('div', { key: j.name, className: cx('hg-run', 'is-' + j.status) },
          h('div', { className: 'hg-run-top' },
            h('span', { className: 'hg-run-name' }, h('b', null, j.name), h('small', null, j.model + ' · ' + j.suite)),
            h(Badge, { key: j.status, tone: st[0], pulse: j.status === 'running', className: 'hg-pop' }, st[1])),
          h('div', { className: 'hg-bar' }, h('span', { className: cx('hg-bar-fill', 'hg-tone-' + st[0]), style: { width: pct.toFixed(2) + '%' } })),
          h('div', { className: 'hg-run-meta' }, h('span', null, fmt(j.done) + ' / ' + fmt(j.total) + ' 样本'), h('span', null, pct.toFixed(1) + '%')));
      })),
      p.simulate && h('ol', { className: 'hg-log', 'aria-live': 'off' }, log.map(function (e) {
        return h('li', { key: e.id, className: e.ok ? 'ok' : 'bad' },
          h('span', null, '#' + e.id), h('span', null, e.task), h('span', null, e.ok ? '✓' : '✗'), h('span', null, e.s), h('span', null, e.t + 's'));
      })));
  }

  /* ---------- ArenaCompare ---------- */
  function ArenaCompare(p) {
    var sr = useState(0), run = sr[0], setRun = sr[1];
    var st = useState(RM ? 1e9 : 0), t = st[0], setT = st[1];
    var la = p.a.text.length, lb = p.b.text.length;
    var na = Math.min(la, Math.floor(t * 1.9)), nb = Math.min(lb, Math.floor(t * 1.45));
    var done = na >= la && nb >= lb;
    var timer = useRef(null);
    useEffect(function () {
      if (RM) return;
      setT(0);
      timer.current = setInterval(function () { setT(function (x) { return x + 1; }); }, 32);
      return function () { clearInterval(timer.current); };
    }, [run]);
    useEffect(function () { if (done) clearInterval(timer.current); }, [done]);
    var v = p.verdict || { a: 50, b: 50 };
    var win = v.a >= v.b ? 'a' : 'b';
    function side(key, data, shown, tone) {
      var full = shown >= data.text.length;
      return h('div', { className: cx('hg-arena-side', 'hg-tone-' + tone, done && win === key && 'is-win') },
        h('div', { className: 'hg-arena-hd' },
          h('span', { className: 'hg-arena-tag' }, key.toUpperCase()),
          h('b', null, data.model),
          h('small', null, Math.round(shown / 1.6) + ' tok · ' + (data.latency || '—')),
          done && win === key && h(Badge, { tone: tone, dot: false, className: 'hg-pop' }, '胜出')),
        h('p', { className: 'hg-arena-txt' }, data.text.slice(0, shown), !full && h('span', { className: 'hg-caret' })));
    }
    return h('div', { className: 'hg-arena' },
      h('div', { className: 'hg-arena-prompt' }, h('span', { className: 'hg-label' }, '提示词'), h('p', null, p.prompt)),
      h('div', { className: 'hg-arena-cols' }, side('a', p.a, na, 'signal'), side('b', p.b, nb, 'coral')),
      h('div', { className: 'hg-arena-foot' },
        h('div', { className: 'hg-split' },
          h('span', { className: 'hg-split-a', style: { flexBasis: (done ? v.a : 50) + '%' } }, done ? v.a + '%' : ''),
          h('span', { className: 'hg-split-b', style: { flexBasis: (done ? v.b : 50) + '%' } }, done ? v.b + '%' : '')),
        h('div', { className: 'hg-arena-row' },
          h('span', { className: 'hg-hint' }, done ? (p.judge || '裁判模型') + '：' + (v.reason || '') : '两个模型正在流式作答…'),
          h(Button, { variant: 'ghost', size: 'sm', icon: 'replay', onClick: function () { setRun(run + 1); } }, '重播'))));
  }

  /* ---------- Dashboard (showcase page) ---------- */
  var NAV = [['grid', '评测总览'], ['trophy', '排行榜'], ['play', '评测任务'], ['arena', '对战竞技场'], ['db', '数据集'], ['cube', '模型库'], ['gear', '设置']];
  var DEMO_ROWS = [
    { model: 'Orion-Ultra', org: 'Northstar AI', delta: 1, scores: { overall: 86.4, reason: 89.1, code: 84.2, zh: 81.7, safe: 90.3 } },
    { model: 'Qilin-Max', org: '麒麟智算', delta: 2, scores: { overall: 84.9, reason: 83.6, code: 80.4, zh: 91.2, safe: 86.0 } },
    { model: 'Kestrel-70B', org: 'Kestrel Labs', delta: -1, scores: { overall: 82.7, reason: 85.0, code: 88.9, zh: 74.5, safe: 82.1 } },
    { model: 'Hanlin-2', org: '翰林研究院', delta: 0, scores: { overall: 79.3, reason: 76.8, code: 71.2, zh: 88.4, safe: 84.7 } },
    { model: 'Atlas-34B', org: 'Atlas Open', delta: -2, scores: { overall: 74.8, reason: 72.5, code: 79.6, zh: 68.3, safe: 77.9 } },
    { model: 'Mistlark-8B', org: 'Mistlark', delta: 3, scores: { overall: 68.1, reason: 64.0, code: 66.7, zh: 70.2, safe: 73.5 } }
  ];
  var DEMO_METRICS = [{ key: 'overall', label: '综合' }, { key: 'reason', label: '推理' }, { key: 'code', label: '代码' }, { key: 'zh', label: '中文' }, { key: 'safe', label: '安全' }];
  var DEMO_JOBS = [
    { name: 'MMLU-Pro 全量', model: 'Orion-Ultra', suite: '知识', done: 7420, total: 12032, status: 'running' },
    { name: 'HumanEval+ 代码', model: 'Kestrel-70B', suite: '代码', done: 98, total: 164, status: 'running' },
    { name: 'C-Eval 中文', model: 'Qilin-Max', suite: '中文', done: 0, total: 13948, status: 'queued' },
    { name: 'SafetyBench', model: 'Hanlin-2', suite: '安全', done: 11435, total: 11435, status: 'done' }
  ];
  var DEMO_ARENA = {
    prompt: '用一句话向产品经理解释：为什么评测集需要防止数据污染？',
    a: { model: 'Orion-Ultra', latency: '1.8s', text: '如果评测题在训练时被模型见过，高分只说明它背过答案，而不是真的会——就像提前拿到考卷的学生，成绩再好也无法反映上线后面对新问题的真实能力。' },
    b: { model: 'Qilin-Max', latency: '2.3s', text: '数据污染会让模型在测试集上“作弊”，分数虚高，导致我们高估模型能力并做出错误的选型决策。' },
    verdict: { a: 64, b: 36, reason: 'A 的类比更贴近产品视角，且点明了对上线效果的影响。' },
    judge: '裁判 · Orion-Judge'
  };

  function Dashboard(p) {
    var sn = useState(0), nav = sn[0], setNav = sn[1];
    var sd = useState(function () { return document.documentElement.getAttribute('data-theme') || 'dark'; }), theme = sd[0], setTheme = sd[1];
    function flip() { var t = theme === 'dark' ? 'light' : 'dark'; document.documentElement.setAttribute('data-theme', t); setTheme(t); }
    return h('div', { className: 'hg-app' },
      h('div', { className: 'hg-aura', 'aria-hidden': true }),
      h('aside', { className: 'hg-side' },
        h('div', { className: 'hg-brand' },
          h('svg', { width: 28, height: 28, viewBox: '0 0 28 28', 'aria-hidden': true, className: 'hg-mark' },
            h('rect', { className: 'hg-mark-bg', width: 28, height: 28, rx: 8 }),
            h('path', { className: 'hg-mark-beam', d: 'M6 10h16M14 10v11M10 21h8' }),
            h('circle', { className: 'hg-mark-dot', cx: 7, cy: 15, r: 2.4 }), h('circle', { className: 'hg-mark-dot2', cx: 21, cy: 15, r: 2.4 })),
          h('span', null, h('b', null, 'Heng 衡'), h('small', null, 'LLM 评测平台'))),
        h('nav', { className: 'hg-nav' },
          h('span', { className: 'hg-nav-ind', style: { transform: 'translateY(' + nav * 40 + 'px)' } }),
          NAV.map(function (n, i) {
            return h('button', { key: n[1], type: 'button', className: cx('hg-nav-i', i === nav && 'is-on'), onClick: function () { setNav(i); }, 'aria-current': i === nav ? 'page' : undefined },
              h(Icon, { name: n[0] }), n[1], i === 2 && h('span', { className: 'hg-nav-count' }, '2'));
          })),
        h('div', { className: 'hg-side-foot' },
          h(ScoreRing, { value: 72.4, size: 64, stroke: 6, label: '配额', tone: 'teal' }),
          h('div', null, h('b', null, 'GPU 配额'), h('small', null, '本月已用 72.4%')))),
      h('main', { className: 'hg-main' },
        h('header', { className: 'hg-top hg-enter' },
          h('div', null, h('h1', null, '评测总览'), h('p', null, '最近 7 天 · 6 个模型 · 38 个评测集')),
          h('div', { className: 'hg-top-actions' },
            h('label', { className: 'hg-search' }, h(Icon, { name: 'search' }), h('input', { placeholder: '搜索模型、评测集、任务…' }), h('kbd', null, '⌘K')),
            h('button', { type: 'button', className: 'hg-iconbtn', onClick: flip, 'aria-label': '切换主题' }, h(Icon, { name: theme === 'dark' ? 'sun' : 'moon', key: theme, className: 'hg-spin-in' })),
            h(Button, { variant: 'primary', icon: 'plus' }, '新建评测'))),
        h('section', { className: 'hg-metrics' },
          h(MetricCard, { index: 0, label: '已评测样本', value: 1284560, delta: 12.4, deltaDecimals: 1, deltaSuffix: '%', data: [32, 41, 38, 52, 49, 61, 58, 72, 70, 86], tone: 'signal' }),
          h(MetricCard, { index: 1, label: '平均得分', value: 78.6, decimals: 1, delta: 1.8, deltaDecimals: 1, data: [71, 72, 74, 73, 75, 76, 76, 77, 78, 78.6], tone: 'teal' }),
          h(MetricCard, { index: 2, label: '运行中任务', value: 6, delta: 2, data: [2, 3, 3, 5, 4, 4, 6, 5, 7, 6], tone: 'amber' }),
          h(MetricCard, { index: 3, label: '本周推理成本', value: 3482, prefix: '¥', delta: -6.2, deltaDecimals: 1, deltaSuffix: '%', data: [60, 58, 63, 55, 52, 54, 49, 47, 45, 44], tone: 'coral' })),
        h('section', { className: 'hg-row hg-row-a' },
          h('div', { className: 'hg-card hg-enter', style: { '--d': '200ms' } },
            h('div', { className: 'hg-card-hd' }, h('h2', null, '模型排行榜'), h(Badge, { tone: 'signal', pulse: true }, '实时')),
            h(Leaderboard, { rows: DEMO_ROWS, metrics: DEMO_METRICS })),
          h('div', { className: 'hg-card hg-enter', style: { '--d': '280ms' } },
            h('div', { className: 'hg-card-hd' }, h('h2', null, '能力雷达'), h('small', { className: 'hg-hint' }, '点击图例切换')),
            h(Radar, { size: 340, axes: ['推理', '代码', '中文', '安全', '长文本', '工具调用'], series: [
              { name: 'Orion-Ultra', values: [89, 84, 82, 90, 86, 88] },
              { name: 'Qilin-Max', values: [84, 80, 91, 86, 78, 74] },
              { name: 'Kestrel-70B', values: [85, 89, 75, 82, 70, 81] }] }))),
        h('section', { className: 'hg-row hg-row-b' },
          h('div', { className: 'hg-card hg-enter', style: { '--d': '360ms' } },
            h('div', { className: 'hg-card-hd' }, h('h2', null, '评测任务'), h(Button, { variant: 'ghost', size: 'sm' }, '全部任务')),
            h(RunProgress, { jobs: DEMO_JOBS, simulate: true })),
          h('div', { className: 'hg-card hg-enter', style: { '--d': '440ms' } },
            h('div', { className: 'hg-card-hd' }, h('h2', null, '对战竞技场'), h(Badge, { tone: 'neutral' }, '盲评 · 第 2,481 轮')),
            h(ArenaCompare, DEMO_ARENA)))));
  }

  window.Heng = {
    Button: Button, Badge: Badge, Tabs: Tabs, CountUp: CountUp, Sparkline: Sparkline, MetricCard: MetricCard,
    ScoreRing: ScoreRing, Leaderboard: Leaderboard, Radar: Radar, RunProgress: RunProgress, ArenaCompare: ArenaCompare,
    Dashboard: Dashboard, Icon: Icon, Delta: Delta,
    demo: { rows: DEMO_ROWS, metrics: DEMO_METRICS, jobs: DEMO_JOBS, arena: DEMO_ARENA }
  };
})();
