// Settings slider math (plain JS, also loaded by tests/test_slider.py through node).
(function (root) {
  'use strict';
  const STEPS = 200;
  const isLog = (min, max, type) => min > 0 && max / min >= 100;
  function nice(v, type) {
    if (type === 'int') return Math.round(v);
    if (v === 0) return 0;
    const mag = Math.pow(10, Math.floor(Math.log10(Math.abs(v))) - 1);   // 2 significant digits: 20000, 25000, 150000
    return +(Math.round(v / mag) * mag).toPrecision(6);
  }
  function valueAt(min, max, type, pos) {
    const k = Math.max(0, Math.min(STEPS, +pos)) / STEPS;
    if (isLog(min, max, type)) return Math.min(max, Math.max(min, nice(min * Math.pow(max / min, k), type)));
    const raw = min + (max - min) * k;
    return type === 'int' ? Math.round(raw) : Math.min(max, Math.max(min, +raw.toPrecision(4)));
  }
  function posFor(min, max, type, v) {
    v = Math.max(min, Math.min(max, +v));
    if (isLog(min, max, type)) return Math.round(STEPS * Math.log(v / min) / Math.log(max / min));
    return Math.round(STEPS * (v - min) / (max - min || 1));
  }
  const api = {STEPS, isLog, nice, valueAt, posFor,
    toValue: el => valueAt(+el.dataset.min, +el.dataset.max, el.dataset.t, +el.value),
    toPos: (el, v) => posFor(+el.dataset.min, +el.dataset.max, el.dataset.t, v)};
  if (typeof module !== 'undefined') module.exports = api; else root.DeskSlider = api;
})(this);
