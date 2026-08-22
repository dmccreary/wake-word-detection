/* Wake Word Explorer -- plots the takes recorded by record-wake-words.py.
 *
 * This file draws pictures. It does not analyze anything.
 *
 * Every measurement comes from data/takes.json, built by
 * src/tools/build-explorer-data.py out of src/tools/wakeword_analysis.py --
 * the same module src/tools/analyze-wake-words.py prints its tables from. The
 * only arithmetic here is summing subsets of an already-computed power
 * spectrogram, which is what lets the BAND_LO_HZ slider move without shipping
 * a copy of the analysis to the browser. Python ships a checksum of each of
 * those sums and check() below complains loudly if they ever disagree.
 */

'use strict';

var D = null;          // the parsed takes.json
var C = null;          // D.constants, for brevity
var TAKES = [];        // decoded per-take arrays
var cutIdx = 0;        // index into D.cutoffs
var current = null;    // take index, or null for the overview
var audio = null;      // lazily created AudioContext
var playing = null;    // the running source node, if any

var OPT = {
  bandRms: true,
  broadRms: true,
  floor: true,
  speechFloor: true,
  extent: true,
  logFreq: true,
  meanSub: true,
  zoom: true
};

var COLOR = {
  wave: '#b0bec5',
  broad: '#90a4ae',
  band: '#1565c0',
  floor: '#78909c',
  gate: '#c62828',
  extent: 'rgba(230,74,25,0.09)',
  speech: '#1565c0',
  room: '#e64a19',
  cut: '#e64a19',
  edge: 'rgba(255,255,255,0.8)',
  edgeLight: 'rgba(21,101,192,0.55)'
};

var FONT = { family: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace', size: 10 };

/* ---- decoding ------------------------------------------------------- */

function b64ToBytes(s) {
  var bin = atob(s), out = new Uint8Array(bin.length);
  for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

// The .bin payloads are written little-endian by numpy. Every platform that
// runs a browser is little-endian too, but reading through a DataView costs
// nothing here and means the file format does not quietly depend on that.
function readI16(bytes) {
  var v = new DataView(bytes.buffer), n = bytes.length >> 1, out = new Int16Array(n);
  for (var i = 0; i < n; i++) out[i] = v.getInt16(i * 2, true);
  return out;
}

function readU16(bytes) {
  var v = new DataView(bytes.buffer), n = bytes.length >> 1, out = new Uint16Array(n);
  for (var i = 0; i < n; i++) out[i] = v.getUint16(i * 2, true);
  return out;
}

function decodeTake(t) {
  var F = t.spec_shape[0], NB = t.spec_shape[1];
  var q = readU16(b64ToBytes(t.spec_b64));
  var pow = new Float64Array(q.length);
  for (var i = 0; i < q.length; i++) {
    pow[i] = Math.pow(10, (C.DB_OFFSET + q[i] * C.DB_STEP) / 10);
  }
  var lo = readI16(b64ToBytes(t.wave_min_b64));
  var hi = readI16(b64ToBytes(t.wave_max_b64));
  return {
    meta: t, F: F, NB: NB, pow: pow,
    waveLo: lo, waveHi: hi,
    rms: t.rms,
    loud: t.rms.map(function (r) { return r > t.floor_rms * Math.pow(10, C.LOUD_DB / 20); }),
    quiet: t.rms.map(function (r) { return r <= t.floor_rms * Math.pow(10, C.QUIET_DB / 20); })
  };
}

/* ---- the only arithmetic in this file ------------------------------- */

function bandEnergy(tk, edges) {
  var B = edges.length - 1, out = new Float64Array(tk.F * B);
  for (var f = 0; f < tk.F; f++) {
    var base = f * tk.NB;
    for (var b = 0; b < B; b++) {
      var acc = 0;
      for (var k = edges[b]; k < edges[b + 1]; k++) acc += tk.pow[base + k];
      out[f * B + b] = acc;
    }
  }
  return out;
}

function bandRms(tk, edges) {
  var B = edges.length - 1, e = bandEnergy(tk, edges), out = new Float64Array(tk.F);
  for (var f = 0; f < tk.F; f++) {
    var s = 0;
    for (var b = 0; b < B; b++) s += e[f * B + b];
    out[f] = Math.sqrt(C.BAND_RMS_SCALE * s);
  }
  return out;
}

// Lab 4's feature vector: log-compressed band energy with the frame's mean
// removed. See wakeword_analysis.feature_vectors() for why the subtraction is
// the load-bearing step.
function featureVectors(tk, edges, meanSub) {
  var B = edges.length - 1, e = bandEnergy(tk, edges), out = new Float64Array(tk.F * B);
  for (var f = 0; f < tk.F; f++) {
    var mean = 0;
    for (var b = 0; b < B; b++) {
      var v = Math.log1p(e[f * B + b] / (edges[b + 1] - edges[b]));
      out[f * B + b] = v;
      mean += v;
    }
    mean /= B;
    if (meanSub) for (var b2 = 0; b2 < B; b2++) out[f * B + b2] -= mean;
  }
  return out;
}

// Mean power per FFT bin over a set of frames -- the "FFT of the take".
function meanSpectrum(tk, mask) {
  var out = new Float64Array(tk.NB), n = 0;
  for (var f = 0; f < tk.F; f++) {
    if (mask && !mask[f]) continue;
    var base = f * tk.NB;
    for (var k = 0; k < tk.NB; k++) out[k] += tk.pow[base + k];
    n++;
  }
  if (n) for (var k2 = 0; k2 < tk.NB; k2++) out[k2] /= n;
  return out;
}

/* ---- the drift guard ------------------------------------------------ */

function check() {
  var bad = [];
  D.cutoffs.forEach(function (cut) {
    var edges = cut.edges;
    TAKES.forEach(function (tk) {
      var want = tk.meta.checks[String(cut.hz)];
      if (!want) return;
      var br = bandRms(tk, edges), sum = 0;
      for (var i = 0; i < br.length; i++) sum += br[i];
      var gotDb = 20 * Math.log10(sum / br.length);
      if (Math.abs(gotDb - want[0]) > 0.02) {
        bad.push(tk.meta.name + ' @' + cut.hz + 'Hz band RMS ' +
                 gotDb.toFixed(4) + ' vs numpy ' + want[0]);
      }
      var fv = featureVectors(tk, edges, true), acc = 0;
      for (var j = 0; j < fv.length; j++) acc += Math.abs(fv[j]);
      var gotF = acc / fv.length;
      if (Math.abs(gotF - want[1]) > 1e-4) {
        bad.push(tk.meta.name + ' @' + cut.hz + 'Hz mean|feature| ' +
                 gotF.toFixed(6) + ' vs numpy ' + want[1]);
      }
    });
  });
  if (bad.length) {
    console.error('Wake Word Explorer: the browser and numpy disagree.\n' +
                  bad.slice(0, 10).join('\n'));
  } else {
    console.log('Wake Word Explorer: ' + TAKES.length + ' takes x ' +
                D.cutoffs.length + ' cutoffs agree with numpy to 0.02 dB.');
  }
  return bad.length === 0;
}

/* ---- small helpers -------------------------------------------------- */

function cut() { return D.cutoffs[cutIdx]; }

// Shape and tick coordinates on a log axis go in DATA units -- 350, not
// log10(350). Measured against Plotly 2.35 rather than assumed: Plotly 1.x
// wanted log units for shapes, and a band edge given in log units lands far
// down the plot rather than erroring, which looks exactly like having
// forgotten to draw it. If band edges ever go missing again, check this first.

// Explicit frequency ticks. Plotly's log minor ticks read "5 6 7 8 9 100 2 3",
// which is not what anyone wants to see under a spectrum.
var HZ_TICKS = [50, 100, 200, 350, 500, 1000, 2000, 4000, 6000];

function hzAxis(title) {
  return {
    type: OPT.logFreq ? 'log' : 'linear',
    range: OPT.logFreq ? [Math.log10(50), Math.log10(6400)] : [0, 6400],
    tickmode: 'array', tickvals: HZ_TICKS,
    ticktext: HZ_TICKS.map(function (v) { return v >= 1000 ? (v / 1000) + 'k' : String(v); }),
    tickfont: FONT,
    title: title ? { text: title, font: { size: 11 } } : undefined
  };
}

// The x-range for one take. Zoomed, every strip gets the SAME width -- anchored
// on its own phrase onset, so ten takes spoken at ten different moments line up
// without being stretched to different time scales.
var ZOOM_LEAD = 0.15;                       // seconds of room before the phrase
var zoomWidth = 0;

function xrange(tk) {
  if (!OPT.zoom || tk.meta.first_frame === null) return [0, tk.meta.seconds];
  var t0 = Math.max(0, frameT(tk.meta.first_frame) - ZOOM_LEAD);
  var t1 = Math.min(tk.meta.seconds, t0 + zoomWidth);
  return [t1 - zoomWidth < 0 ? 0 : t1 - zoomWidth, t1];
}

// Wide enough for the median phrase with room to breathe, and deliberately not
// wide enough for take 07's 1,900 ms outlier -- sizing every strip around the
// worst one would shrink the other nine back to invisibility.
function setZoomWidth() {
  var spans = TAKES.map(function (t) { return t.meta.span_frames; })
                   .filter(function (v) { return v; })
                   .sort(function (a, b) { return a - b; });
  var med = spans.length ? spans[Math.floor(spans.length / 2)] : 30;
  var w = med * C.FRAME_MS / 1000 * 2.2 + ZOOM_LEAD;
  zoomWidth = Math.min(3.0, Math.max(0.8, w));
}
function binHz(k) { return k * C.BIN_HZ; }
function frameT(f) { return f * C.FRAME_MS / 1000; }

function fmtLevel(v) {
  return v >= 1000 ? Math.round(v).toLocaleString() : v.toFixed(0);
}

// Waveform as one trace of vertical min/max bars, the way Audacity draws it.
// `step` merges adjacent columns so the overview strips carry a few hundred
// bars instead of twelve hundred.
function waveTrace(tk, step, axis) {
  var n = Math.floor(tk.waveLo.length / step), x = [], y = [];
  var dt = C.WAVE_DECIM * step / C.RATE;
  for (var i = 0; i < n; i++) {
    var lo = 32767, hi = -32768;
    for (var j = i * step; j < (i + 1) * step; j++) {
      if (tk.waveLo[j] < lo) lo = tk.waveLo[j];
      if (tk.waveHi[j] > hi) hi = tk.waveHi[j];
    }
    x.push(i * dt, i * dt, null);
    y.push(lo * C.GAIN, hi * C.GAIN, null);
  }
  return {
    x: x, y: y, mode: 'lines', type: 'scatter',
    line: { color: COLOR.wave, width: 1 },
    hoverinfo: 'none', showlegend: false,
    xaxis: axis.x, yaxis: axis.y
  };
}

// An envelope drawn above and below the zero line, so it reads against the
// waveform rather than beside it.
function envTrace(vals, color, width, dash, name, axis, showlegend) {
  var x = [], y = [];
  for (var f = 0; f < vals.length; f++) { x.push(frameT(f)); y.push(vals[f]); }
  x.push(null); y.push(null);
  for (var g = 0; g < vals.length; g++) { x.push(frameT(g)); y.push(-vals[g]); }
  return {
    x: x, y: y, mode: 'lines', type: 'scatter', name: name,
    line: { color: color, width: width, dash: dash || 'solid' },
    hoverinfo: 'none', showlegend: !!showlegend, connectgaps: false,
    xaxis: axis.x, yaxis: axis.y
  };
}

function hline(v, color, dash, axis, width) {
  return {
    type: 'line', xref: axis.x, yref: axis.y,
    x0: 0, x1: 1, xsizemode: 'scaled', y0: v, y1: v,
    line: { color: color, width: width || 1, dash: dash || 'dot' }
  };
}

/* ---- overview ------------------------------------------------------- */

function drawOverview() {
  var traces = [], shapes = [], annots = [];
  var rows = TAKES.length;
  var gapY = 0.022, rowH = 1 / rows;
  var edges = cut().edges;
  var gate = C.SPEECH_FLOOR;

  TAKES.forEach(function (tk, i) {
    var y0 = 1 - (i + 1) * rowH + gapY / 2, y1 = 1 - i * rowH - gapY / 2;
    var L = { x: 'x' + (2 * i + 1), y: 'y' + (2 * i + 1) };
    var R = { x: 'x' + (2 * i + 2), y: 'y' + (2 * i + 2) };
    var last = i === rows - 1;

    var br = bandRms(tk, edges);
    var peak = 0;
    for (var w = 0; w < tk.waveHi.length; w++) {
      peak = Math.max(peak, Math.abs(tk.waveHi[w]), Math.abs(tk.waveLo[w]));
    }
    peak = Math.max(peak * C.GAIN, gate * 1.15);

    var xr = xrange(tk);

    // Clickable backdrop: a transparent filled rectangle behind the strip.
    traces.push({
      x: [xr[0], xr[1], xr[1], xr[0], xr[0]],
      y: [-peak, -peak, peak, peak, -peak],
      fill: 'toself', fillcolor: 'rgba(0,0,0,0)', mode: 'lines',
      line: { width: 0 }, hoverinfo: 'none', hoveron: 'fills',
      showlegend: false, meta: i, xaxis: L.x, yaxis: L.y
    });

    if (OPT.extent && tk.meta.first_frame !== null) {
      shapes.push({
        type: 'rect', xref: L.x, yref: L.y, layer: 'below',
        x0: frameT(tk.meta.first_frame), x1: frameT(tk.meta.last_frame + 1),
        y0: -peak, y1: peak, fillcolor: COLOR.extent, line: { width: 0 }
      });
    }

    traces.push(waveTrace(tk, OPT.zoom ? 1 : 3, L));
    if (OPT.broadRms) traces.push(envTrace(tk.rms, COLOR.broad, 1, 'dot', null, L));
    if (OPT.bandRms) traces.push(envTrace(br, COLOR.band, 1.4, null, null, L));
    if (OPT.floor) shapes.push(hline(tk.meta.floor_rms, COLOR.floor, 'dot', L),
                                hline(-tk.meta.floor_rms, COLOR.floor, 'dot', L));
    if (OPT.speechFloor) shapes.push(hline(gate, COLOR.gate, 'dash', L),
                                     hline(-gate, COLOR.gate, 'dash', L));

    // FFT alongside: the take's mean spectrum over its speech frames and over
    // its quiet frames, so the two curves cross where the decision lives.
    var sp = meanSpectrum(tk, tk.loud), rm = meanSpectrum(tk, tk.quiet);
    var fx = [], fs = [], fr = [];
    for (var k = 1; k < tk.NB; k++) {
      fx.push(binHz(k));
      fs.push(10 * Math.log10(Math.max(sp[k], 1e-9)));
      fr.push(10 * Math.log10(Math.max(rm[k], 1e-9)));
    }
    traces.push({
      x: fx, y: fr, mode: 'lines', type: 'scatter', name: 'room',
      line: { color: COLOR.room, width: 1 }, hoverinfo: 'none',
      showlegend: false, xaxis: R.x, yaxis: R.y
    });
    traces.push({
      x: fx, y: fs, mode: 'lines', type: 'scatter', name: 'speech',
      line: { color: COLOR.speech, width: 1.4 }, hoverinfo: 'none',
      showlegend: false, meta: i, xaxis: R.x, yaxis: R.y
    });
    shapes.push({
      type: 'rect', xref: R.x, yref: 'paper', layer: 'below',
      x0: 50, x1: cut().hz,
      y0: y0, y1: y1, fillcolor: 'rgba(120,144,156,0.13)', line: { width: 0 }
    });

    annots.push({
      xref: 'paper', yref: 'paper', x: 0.002, y: (y0 + y1) / 2,
      xanchor: 'left', yanchor: 'middle', showarrow: false,
      text: '<b>' + tk.meta.label + '</b>', font: { size: 11, color: '#52606d' }
    });
    if (i === 0) {
      annots.push({
        xref: 'paper', yref: 'paper', x: 0.34, y: 1.008, xanchor: 'center',
        yanchor: 'bottom', showarrow: false, text: 'waveform, 24-bit units',
        font: { size: 11, color: '#7b8794' }
      });
      annots.push({
        xref: 'paper', yref: 'paper', x: 0.85, y: 1.008, xanchor: 'center',
        yanchor: 'bottom', showarrow: false,
        text: 'mean spectrum: <span style="color:#1565c0">speech</span> vs <span style="color:#e64a19">room</span>',
        font: { size: 11, color: '#7b8794' }
      });
    }

    var layoutAxes = drawOverview.axes;
    layoutAxes['xaxis' + (2 * i + 1)] = {
      domain: [0.035, 0.63], anchor: L.y, range: xr,
      showticklabels: last, tickfont: FONT, showgrid: false, zeroline: false,
      title: last ? { text: 'seconds', font: { size: 11 } } : undefined
    };
    layoutAxes['yaxis' + (2 * i + 1)] = {
      domain: [y0, y1], anchor: L.x, range: [-peak, peak],
      showticklabels: false, showgrid: false, zeroline: true,
      zerolinecolor: '#eceff1', fixedrange: true
    };
    layoutAxes['xaxis' + (2 * i + 2)] = Object.assign(
      hzAxis(last ? 'Hz' : null),
      { domain: [0.70, 0.995], anchor: R.y, showticklabels: last, showgrid: false });
    layoutAxes['yaxis' + (2 * i + 2)] = {
      domain: [y0, y1], anchor: R.x, showticklabels: false,
      showgrid: false, zeroline: false, fixedrange: true
    };
  });

  var layout = {
    height: Math.max(520, rows * 96 + 46),
    margin: { l: 34, r: 10, t: 26, b: 40 },
    paper_bgcolor: '#fff', plot_bgcolor: '#fff',
    shapes: shapes, annotations: annots, hovermode: false, dragmode: false
  };
  Object.keys(drawOverview.axes).forEach(function (k) { layout[k] = drawOverview.axes[k]; });

  var host = document.getElementById('plots');
  host.innerHTML = '<div class="plot"><div id="ov"></div></div>';
  Plotly.newPlot('ov', traces, layout, { displayModeBar: false, responsive: true })
    .then(function (gd) {
      gd.on('plotly_click', function (ev) {
        var m = ev.points && ev.points[0] && ev.points[0].data.meta;
        if (m !== undefined && m !== null) select(m);
      });
    });
}
drawOverview.axes = {};

/* ---- drill-down ----------------------------------------------------- */

function drawDetail() {
  var tk = TAKES[current], edges = cut().edges, gate = C.SPEECH_FLOOR;
  var host = document.getElementById('plots');
  host.innerHTML =
    '<div class="plot"><h2>' + tk.meta.name + '</h2>' +
    '<p id="cap1"></p><div id="d1"></div></div>' +
    '<div class="plot"><h2>Spectrogram and the 12 bands</h2>' +
    '<p id="cap2"></p><div id="d2"></div></div>' +
    '<div class="plot"><h2>Mean spectrum</h2><p id="cap3"></p><div id="d3"></div></div>';

  /* --- panel 1: waveform and envelopes --- */
  var br = bandRms(tk, edges);
  var peak = 0;
  for (var w = 0; w < tk.waveHi.length; w++) {
    peak = Math.max(peak, Math.abs(tk.waveHi[w]), Math.abs(tk.waveLo[w]));
  }
  peak = Math.max(peak * C.GAIN, gate * 1.15) * 1.04;

  var A = { x: 'x', y: 'y' };
  var t1 = [waveTrace(tk, 1, A)];
  if (OPT.broadRms) t1.push(envTrace(tk.rms, COLOR.broad, 1.2, 'dot', 'broadband RMS', A, true));
  if (OPT.bandRms) t1.push(envTrace(br, COLOR.band, 1.8, null,
    'band RMS (' + cut().hz + '–6000 Hz) — what the gate sees', A, true));

  var sh1 = [];
  if (OPT.extent && tk.meta.first_frame !== null) {
    sh1.push({
      type: 'rect', xref: 'x', yref: 'y', layer: 'below',
      x0: frameT(tk.meta.first_frame), x1: frameT(tk.meta.last_frame + 1),
      y0: -peak, y1: peak, fillcolor: COLOR.extent, line: { width: 0 }
    });
  }
  if (OPT.floor) sh1.push(hline(tk.meta.floor_rms, COLOR.floor, 'dot', A),
                          hline(-tk.meta.floor_rms, COLOR.floor, 'dot', A));
  if (OPT.speechFloor) sh1.push(hline(gate, COLOR.gate, 'dash', A, 1.4),
                                hline(-gate, COLOR.gate, 'dash', A, 1.4));

  // Both labels ride the right edge on a solid backing. Left-anchoring the
  // floor put it straight through the start of the waveform.
  var ann1 = [];
  if (OPT.speechFloor) {
    ann1.push({
      xref: 'paper', yref: 'y', x: 0.999, y: gate, xanchor: 'right', yanchor: 'bottom',
      showarrow: false, text: 'SPEECH_FLOOR ' + fmtLevel(gate),
      font: { size: 10, color: COLOR.gate },
      bgcolor: 'rgba(255,255,255,0.85)', borderpad: 2
    });
  }
  if (OPT.floor) {
    ann1.push({
      xref: 'paper', yref: 'y', x: 0.999, y: -tk.meta.floor_rms, xanchor: 'right',
      yanchor: 'top', showarrow: false,
      text: 'noise floor ' + fmtLevel(tk.meta.floor_rms),
      font: { size: 10, color: COLOR.floor },
      bgcolor: 'rgba(255,255,255,0.85)', borderpad: 2
    });
  }

  Plotly.newPlot('d1', t1, {
    height: 280, margin: { l: 62, r: 12, t: 8, b: 38 },
    xaxis: { range: xrange(tk), title: { text: 'seconds', font: { size: 11 } },
             tickfont: FONT, showgrid: false },
    yaxis: { range: [-peak, peak], title: { text: '24-bit units', font: { size: 11 } },
             tickfont: FONT, zeroline: true, zerolinecolor: '#eceff1', showgrid: false },
    shapes: sh1, annotations: ann1, hovermode: false, dragmode: 'pan',
    legend: { orientation: 'h', x: 0, y: 1.14, font: { size: 11 } },
    paper_bgcolor: '#fff', plot_bgcolor: '#fff'
  }, { displayModeBar: false, responsive: true });

  document.getElementById('cap1').innerHTML =
    'Peak frame ' + fmtLevel(tk.meta.peak_rms) + ', floor ' + fmtLevel(tk.meta.floor_rms) +
    ' &mdash; ' + (20 * Math.log10(tk.meta.peak_rms / tk.meta.floor_rms)).toFixed(1) +
    ' dB of headroom. The shaded span is the phrase, gated at the floor +' +
    C.LOUD_DB + ' dB: frames ' + tk.meta.first_frame + '–' + tk.meta.last_frame +
    ', ' + tk.meta.span_frames + ' frames, ' +
    Math.round(tk.meta.span_frames * C.FRAME_MS) + ' ms.';

  /* --- panel 2: spectrogram + band feature matrix, sharing the time axis --- */
  var zs = [], ys = [];
  for (var k = 1; k < tk.NB; k++) {
    ys.push(binHz(k));
    var row = new Array(tk.F);
    for (var f = 0; f < tk.F; f++) row[f] = 10 * Math.log10(Math.max(tk.pow[f * tk.NB + k], 1e-9));
    zs.push(row);
  }
  var times = [];
  for (var f2 = 0; f2 < tk.F; f2++) times.push(frameT(f2));

  var fv = featureVectors(tk, edges, OPT.meanSub);
  var zb = [], yb = [];
  for (var b = 0; b < C.BANDS; b++) {
    yb.push(b);
    var rb = new Array(tk.F);
    for (var f3 = 0; f3 < tk.F; f3++) rb[f3] = fv[f3 * C.BANDS + b];
    zb.push(rb);
  }

  var xr2 = xrange(tk);
  // Everything BAND_LO_HZ discards, shaded on the spectrogram the same way it
  // is shaded on the spectrum below -- so "the detector has no bands down
  // there" is something you can see rather than something you are told.
  var sh2 = [{
    type: 'rect', xref: 'x', yref: 'y', layer: 'above',
    x0: xr2[0], x1: xr2[1], y0: 50, y1: cut().hz,
    fillcolor: 'rgba(236,239,241,0.62)', line: { width: 0 }
  }];
  cut().edges_hz.forEach(function (hz) {
    sh2.push({
      type: 'line', xref: 'x', yref: 'y', x0: xr2[0], x1: xr2[1],
      y0: hz, y1: hz,
      line: { color: COLOR.edge, width: 1.5 }   // white: the spectrogram behind it is dark
    });
  });

  Plotly.newPlot('d2', [
    {
      z: zs, x: times, y: ys, type: 'heatmap', colorscale: 'Viridis',
      showscale: false, hoverinfo: 'none', xaxis: 'x', yaxis: 'y'
    },
    {
      z: zb, x: times, y: yb, type: 'heatmap', colorscale: 'RdBu',
      reversescale: true, zmid: 0, showscale: false, hoverinfo: 'none',
      xaxis: 'x2', yaxis: 'y2'
    }
  ], {
    height: 400, margin: { l: 62, r: 12, t: 8, b: 38 },
    xaxis: { domain: [0, 1], anchor: 'y', range: xrange(tk),
             showticklabels: false, showgrid: false },
    yaxis: Object.assign(hzAxis('Hz'), {
      domain: [0.42, 1], anchor: 'x',
      tickvals: cut().edges_hz,
      ticktext: cut().edges_hz.map(function (v) {
        return v >= 1000 ? (Math.round(v / 100) / 10) + 'k' : String(Math.round(v));
      })
    }),
    xaxis2: { domain: [0, 1], anchor: 'y2', range: xrange(tk),
              title: { text: 'seconds', font: { size: 11 } }, tickfont: FONT,
              showgrid: false },
    yaxis2: { domain: [0, 0.33], anchor: 'x2', title: { text: 'band', font: { size: 11 } },
              tickfont: FONT, dtick: 2 },
    shapes: sh2, hovermode: false, dragmode: false,
    paper_bgcolor: '#fff', plot_bgcolor: '#fff'
  }, { displayModeBar: false, responsive: true });

  document.getElementById('cap2').innerHTML =
    'Top: every FFT bin, in dB. The blue lines are the ' + C.BANDS + ' band edges at ' +
    'BAND_LO_HZ = ' + cut().hz + ' Hz &mdash; evenly spaced on a log axis, because that ' +
    'is what log-spaced means. Bottom: the ' + C.BANDS + ' band energies Lab&nbsp;4 ' +
    'actually matches on' + (OPT.meanSub
      ? ', with each frame’s mean log-energy subtracted. Red is above the frame mean, blue below.'
      : ' as raw log energy, before the mean subtraction. Notice how little the columns differ &mdash; that is why the subtraction is not optional.');

  /* --- panel 3: mean spectrum --- */
  var sp = meanSpectrum(tk, tk.loud), rm = meanSpectrum(tk, tk.quiet);
  var fx = [], fs = [], fr = [];
  for (var k3 = 1; k3 < tk.NB; k3++) {
    fx.push(binHz(k3));
    fs.push(10 * Math.log10(Math.max(sp[k3], 1e-9)));
    fr.push(10 * Math.log10(Math.max(rm[k3], 1e-9)));
  }
  var sh3 = [{
    type: 'rect', xref: 'x', yref: 'paper',
    x0: 50, x1: cut().hz,
    y0: 0, y1: 1, fillcolor: 'rgba(120,144,156,0.14)', line: { width: 0 }, layer: 'below'
  }];
  cut().edges_hz.forEach(function (hz) {
    sh3.push({
      type: 'line', xref: 'x', yref: 'paper', x0: hz, x1: hz, y0: 0, y1: 1,
      line: { color: COLOR.edgeLight, width: 1.2 }
    });
  });

  Plotly.newPlot('d3', [
    { x: fx, y: fr, mode: 'lines', type: 'scatter', name: 'room (quiet frames)',
      line: { color: COLOR.room, width: 1.6 } },
    { x: fx, y: fs, mode: 'lines', type: 'scatter', name: 'speech frames',
      line: { color: COLOR.speech, width: 2 } }
  ], {
    height: 260, margin: { l: 62, r: 12, t: 8, b: 42 },
    xaxis: hzAxis('Hz'),
    yaxis: { title: { text: 'dB', font: { size: 11 } }, tickfont: FONT },
    shapes: sh3, hovermode: 'x unified',
    legend: { orientation: 'h', x: 0, y: 1.16, font: { size: 11 } },
    paper_bgcolor: '#fff', plot_bgcolor: '#fff'
  }, { displayModeBar: false, responsive: true });

  document.getElementById('cap3').innerHTML =
    'Where the blue curve sits above the orange one, a band is worth keeping. ' +
    'The grey block is everything BAND_LO_HZ = ' + cut().hz + ' Hz throws away.';
}

/* ---- the verdict strip ---------------------------------------------- */

function drawVerdict() {
  var c = cut();
  var useLab3 = document.getElementById('noiseRef').value === 'lab3';
  var kept = useLab3 ? c.lab3_noise_kept : c.noise_kept;
  var snr = useLab3 ? c.lab3_snr_change_db : c.snr_change_db;
  var el = document.getElementById('verdict');

  if (useLab3 && kept === null) {
    el.innerHTML = '<span class="note">Lab&nbsp;3 measured its furnace spectrum on its own ' +
      'band edges, and ' + c.hz + '&nbsp;Hz is not one of them. Lining up two different ' +
      'frequency layouts would compare one band of speech against a different band of ' +
      'noise, so this cutoff can only be scored against the takes’ own quiet frames. ' +
      'Try 150, 200, 250, 350, 500, 650 or 900&nbsp;Hz.</span>';
    return;
  }

  var cls = snr > 0 ? 'good' : 'bad';
  el.innerHTML =
    '<span class="stat"><span>BAND_LO_HZ</span> <b>' + c.hz + ' Hz</b></span>' +
    '<span class="stat"><span>speech kept</span> <b>' + (100 * c.speech_kept).toFixed(1) + '%</b></span>' +
    '<span class="stat"><span>noise kept</span> <b>' + (100 * kept).toFixed(1) + '%</b></span>' +
    '<span class="stat"><span>SNR vs ' + C.REFERENCE_CUTOFF_HZ + ' Hz</span> <b class="' + cls + '">' +
      (snr >= 0 ? '+' : '') + snr.toFixed(1) + ' dB</b></span>' +
    '<span class="note">' + verdictNote(c, snr) + '</span>';
}

function verdictNote(c, snr) {
  var lost = (100 - 100 * c.speech_kept).toFixed(0);
  // Order matters: a cutoff can be BOTH lossy and worse than the baseline, and
  // "a good ratio bought by throwing away 95% of the phrase" is the wrong thing
  // to say about a cutoff whose ratio is not good either.
  if (snr < 0) {
    return 'Worse than the ' + C.REFERENCE_CUTOFF_HZ + ' Hz baseline — ' + lost +
      '% of the phrase given up for nothing.';
  }
  if (c.hz === C.BAND_LO_HZ) return 'This is the value Lab 4 ships.';
  if (c.speech_kept < 0.6) {
    return 'A better ratio, bought by throwing away ' + lost +
      '% of the phrase. Judge on both numbers.';
  }
  return 'Keeps most of the phrase. Compare against ' + C.BAND_LO_HZ +
    ' Hz, which is what Lab 4 ships.';
}

/* ---- audio ---------------------------------------------------------- */

function playTake() {
  var idx = current === null ? 0 : current;
  var tk = TAKES[idx];
  var btn = document.getElementById('play');

  if (playing) { playing.stop(); playing = null; btn.classList.remove('on'); return; }
  if (!audio) audio = new (window.AudioContext || window.webkitAudioContext)();

  btn.classList.add('on');
  btn.textContent = '■  Stop';
  fetch(tk.meta.wav)
    .then(function (r) { return r.arrayBuffer(); })
    .then(function (buf) { return audio.decodeAudioData(buf); })
    .then(function (decoded) {
      var src = audio.createBufferSource();
      src.buffer = decoded;
      var node = src;
      if (document.getElementById('playFiltered').checked && cut().hz > 20) {
        // Two cascaded biquads: a 4th-order Butterworth high-pass, flat in the
        // passband, -3 dB at the cutoff, 24 dB per octave below it. This is the
        // ear's version of the grey block on the spectrum plot, not the same
        // operation -- the plots cut bins off square, a biquad rolls off. Close
        // enough to hear which side of the cutoff the phrase lives on.
        //
        // The Q values look wrong and are not. Web Audio takes Q for lowpass
        // and highpass in DECIBELS, so the familiar 0.707 would ask for
        // 10^(0.707/20) = 1.085 -- a resonant filter that BOOSTS by 1.7 dB just
        // above the corner. Measured with getFrequencyResponse() rather than
        // trusted: a "high-pass" that made the takes 2 dB louder is what
        // exposed it. These are the 4th-order Butterworth section Qs,
        // 0.5412 and 1.3066, converted to dB.
        [-5.33, 2.32].forEach(function (qDb) {
          var hp = audio.createBiquadFilter();
          hp.type = 'highpass';
          hp.frequency.value = cut().hz;
          hp.Q.value = qDb;
          node.connect(hp);
          node = hp;
        });
      }
      var gain = audio.createGain();
      gain.gain.value = 3.0;   // the takes sit ~20 dB below full scale
      node.connect(gain).connect(audio.destination);
      src.onended = function () {
        playing = null;
        btn.classList.remove('on');
        btn.innerHTML = '&#9654;&nbsp; Play';
      };
      src.start();
      playing = src;
    })
    .catch(function (e) {
      console.error(e);
      btn.classList.remove('on');
      btn.innerHTML = '&#9654;&nbsp; Play';
    });
}

/* ---- wiring --------------------------------------------------------- */

function select(i) {
  current = i;
  document.querySelectorAll('#takebar button').forEach(function (b) {
    b.classList.toggle('on', b.dataset.i === String(i));
  });
  render();
}

function render() {
  drawVerdict();
  document.getElementById('hint').textContent = current === null
    ? 'Ten takes of “Hey Pico”. Click any strip to open it full width.'
    : 'Showing one take. Choose “All takes” to go back.';
  drawOverview.axes = {};
  if (current === null) drawOverview(); else drawDetail();
}

var TOGGLE_DEFS = [
  ['bandRms', 'band RMS'],
  ['broadRms', 'broadband RMS'],
  ['floor', 'noise floor'],
  ['speechFloor', 'SPEECH_FLOOR'],
  ['extent', 'phrase extent'],
  ['zoom', 'zoom to phrase'],
  ['logFreq', 'log frequency'],
  ['meanSub', 'mean-subtracted bands']
];

function buildControls() {
  document.getElementById('source').textContent =
    TAKES.length + ' takes from ' + D.source_folder;

  var bar = document.getElementById('takebar');
  var all = document.createElement('button');
  all.textContent = 'All takes';
  all.className = 'on';
  all.dataset.i = 'null';
  all.onclick = function () { select(null); };
  bar.appendChild(all);
  TAKES.forEach(function (tk, i) {
    var b = document.createElement('button');
    b.textContent = tk.meta.label;
    b.dataset.i = String(i);
    b.onclick = function () { select(i); };
    bar.appendChild(b);
  });

  var slider = document.getElementById('cutoff');
  slider.max = D.cutoffs.length - 1;
  cutIdx = D.cutoffs.findIndex(function (c) { return c.hz === C.BAND_LO_HZ; });
  if (cutIdx < 0) cutIdx = 0;
  slider.value = cutIdx;
  slider.oninput = function () {
    cutIdx = +slider.value;
    document.getElementById('cutoffOut').textContent = cut().hz + ' Hz';
    render();
  };
  document.getElementById('cutoffOut').textContent = cut().hz + ' Hz';

  document.getElementById('noiseRef').onchange = drawVerdict;
  document.getElementById('play').onclick = playTake;

  var host = document.getElementById('toggles');
  TOGGLE_DEFS.forEach(function (d) {
    var l = document.createElement('label');
    var cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = OPT[d[0]];
    cb.onchange = function () { OPT[d[0]] = cb.checked; render(); };
    l.appendChild(cb);
    l.appendChild(document.createTextNode(d[1]));
    host.appendChild(l);
  });
}

fetch('data/takes.json')
  .then(function (r) {
    if (!r.ok) throw new Error(r.status + ' ' + r.statusText);
    return r.json();
  })
  .then(function (doc) {
    D = doc;
    C = D.constants;
    TAKES = D.takes.map(decodeTake);
    setZoomWidth();
    buildControls();
    check();
    render();
  })
  .catch(function (e) {
    document.getElementById('plots').innerHTML =
      '<div class="oops">Could not load <b>data/takes.json</b> (' + e.message + ').' +
      '<code>python3 src/tools/build-explorer-data.py</code></div>';
  });
