/* FileMaker (independent recreation) — the calculation language.
   FM.calc.parse(formula, scope) -> AST ; FM.calc.evaluate(ast, env) -> value
   Values: text (string), number, FM.FMDate, FM.FMTime, FM.FMTimestamp,
   FM.FMStyled (styled text), container values ({c, name, mime, size}), binary ({bin}). */
(function () {
  'use strict';
  const FM = window.FM;
  const { FMDate, FMTime, FMTimestamp, FMStyled } = FM;
  const D = FM.dt;

  class CalcError extends Error {
    constructor(message, pos, code) { super(message); this.pos = pos == null ? -1 : pos; this.code = code || 1200; }
  }

  // ═══════════════════════════════════════════════════════════════════════
  // values
  // ═══════════════════════════════════════════════════════════════════════
  const V = FM.V = {};
  const isContainer = v => v && typeof v === 'object' && ('c' in v || 'url' in v) && 'name' in v;
  const isBin = v => v && typeof v === 'object' && v.bin instanceof Uint8Array;
  V.isContainer = isContainer;
  V.empty = v => v == null || v === '' || (v instanceof FMStyled && v.text === '') || (typeof v === 'number' && isNaN(v));
  V.text = function (v) {
    if (v == null) return '';
    if (typeof v === 'string') return v;
    if (typeof v === 'number') return isNaN(v) ? '' : FM.num.text(v);
    if (typeof v === 'boolean') return v ? '1' : '0';
    if (v instanceof FMDate) return D.formatDate(v.n);
    if (v instanceof FMTime) return D.formatTime(v.s);
    if (v instanceof FMTimestamp) return D.formatTs(v.s);
    if (v instanceof FMStyled) return v.text;
    if (isContainer(v)) return v.name || '';
    if (isBin(v)) return '';
    return String(v);
  };
  V.numOrNull = function (v) {
    if (v == null || v === '') return null;
    if (typeof v === 'number') return isNaN(v) ? null : v;
    if (typeof v === 'boolean') return v ? 1 : 0;
    if (v instanceof FMDate) return v.n;
    if (v instanceof FMTime || v instanceof FMTimestamp) return v.s;
    if (v instanceof FMStyled) return FM.num.parse(v.text);
    if (isContainer(v) || isBin(v)) return null;
    return FM.num.parse(v);
  };
  V.num = v => { const n = V.numOrNull(v); return n == null ? 0 : n; };
  V.bool = v => { const n = V.numOrNull(v); return n != null && n !== 0; };
  V.date = function (v) {
    if (v instanceof FMDate) return v;
    if (v instanceof FMTimestamp) return new FMDate(Math.floor(v.s / 86400) + 1);
    if (typeof v === 'number') return new FMDate(v);
    const n = D.parseDate(V.text(v));
    if (n != null) return new FMDate(n);
    const t = D.parseTimestamp(V.text(v));
    if (t != null && /\d+:\d/.test(V.text(v))) return new FMDate(Math.floor(t / 86400) + 1);
    const x = FM.num.parse(V.text(v));
    return x != null && /^\s*\d+\s*$/.test(V.text(v)) ? new FMDate(x) : null;
  };
  V.time = function (v) {
    if (v instanceof FMTime) return v;
    if (v instanceof FMTimestamp) return new FMTime(((v.s % 86400) + 86400) % 86400);
    if (typeof v === 'number') return new FMTime(v);
    const s = D.parseTime(V.text(v));
    if (s != null) return new FMTime(s);
    const ts = D.parseTimestamp(V.text(v));
    if (ts != null && /:/.test(V.text(v))) return new FMTime(((ts % 86400) + 86400) % 86400);
    const x = FM.num.parse(V.text(v));
    return x != null && /^\s*-?\d+(\.\d+)?\s*$/.test(V.text(v)) ? new FMTime(x) : null;
  };
  V.ts = function (v) {
    if (v instanceof FMTimestamp) return v;
    if (v instanceof FMDate) return new FMTimestamp((v.n - 1) * 86400);
    if (typeof v === 'number') return new FMTimestamp(v);
    const s = D.parseTimestamp(V.text(v));
    if (s != null) return new FMTimestamp(s);
    const x = FM.num.parse(V.text(v));
    return x != null && /^\s*\d+(\.\d+)?\s*$/.test(V.text(v)) ? new FMTimestamp(x) : null;
  };
  // A field's stored text -> a calculation value of the field's type.
  V.fromStored = function (raw, type) {
    if (raw == null || raw === '') return '';
    if (typeof raw === 'object') return raw;
    switch (type) {
      case 'number': { const n = FM.num.parse(raw); return n == null ? String(raw) : n; }
      case 'date': { const n = D.parseDate(raw); return n == null ? String(raw) : new FMDate(n); }
      case 'time': { const n = D.parseTime(raw); return n == null ? String(raw) : new FMTime(n); }
      case 'timestamp': { const n = D.parseTimestamp(raw); return n == null ? String(raw) : new FMTimestamp(n); }
      default: return String(raw);
    }
  };
  // A calculation value -> text to store in a field of this type.
  V.toStored = function (v, type) {
    if (v == null || v === '') return '';
    if (isContainer(v)) return type === 'container' ? v : v.name;
    switch (type) {
      case 'number': {
        if (typeof v === 'number') return isNaN(v) ? '' : FM.num.plain(v);
        if (v instanceof FMDate) return String(v.n);
        if (v instanceof FMTime || v instanceof FMTimestamp) return FM.num.plain(v.s);
        return V.text(v);
      }
      case 'date': { const d = V.date(v); return d ? D.isoDate(d.n) : V.text(v); }
      case 'time': { const t = V.time(v); return t ? D.isoTime(t.s) : V.text(v); }
      case 'timestamp': { const t = V.ts(v); return t ? D.isoTs(t.s) : V.text(v); }
      case 'container': return typeof v === 'object' ? v : V.text(v);
      default: return V.text(v);
    }
  };
  V.coerce = function (v, type) {
    if (V.empty(v)) return '';
    switch (type) {
      case 'number': { if (typeof v === 'number') return v; const n = V.numOrNull(v); return n == null ? '' : n; }
      case 'date': return V.date(v) || '?';
      case 'time': return V.time(v) || '?';
      case 'timestamp': return V.ts(v) || '?';
      case 'container': return v;
      default: return v instanceof FMStyled ? v : V.text(v);
    }
  };
  const collator = new Intl.Collator(undefined, { sensitivity: 'accent', numeric: false });
  V.cmpText = (a, b) => collator.compare(a, b);
  // FileMaker comparison: by type when either side is typed, else text (case-insensitive)
  V.compare = function (a, b) {
    const ta = typeTag(a), tb = typeTag(b);
    if (ta === 'empty' && tb === 'empty') return 0;
    if (ta === 'date' || tb === 'date' || ta === 'time' || tb === 'time' || ta === 'ts' || tb === 'ts' || ta === 'num' || tb === 'num') {
      if (ta === 'empty' || tb === 'empty') return V.cmpText(V.text(a), V.text(b));
      const x = V.numOrNull(a), y = V.numOrNull(b);
      if (x != null && y != null) return x < y ? -1 : x > y ? 1 : 0;
      const kind = ta !== 'text' ? ta : tb;
      const conv = kind === 'date' ? V.date : kind === 'time' ? V.time : kind === 'ts' ? V.ts : null;
      if (conv) { const p = conv(a), q = conv(b); if (p && q) return p.valueOf() < q.valueOf() ? -1 : p.valueOf() > q.valueOf() ? 1 : 0; }
      return V.cmpText(V.text(a), V.text(b));
    }
    return V.cmpText(V.text(a), V.text(b));
  };
  function typeTag(v) {
    if (V.empty(v)) return 'empty';
    if (typeof v === 'number') return 'num';
    if (v instanceof FMDate) return 'date';
    if (v instanceof FMTime) return 'time';
    if (v instanceof FMTimestamp) return 'ts';
    return 'text';
  }
  V.typeName = v => {
    const t = typeTag(v);
    return { num: 'number', date: 'date', time: 'time', ts: 'timestamp', empty: 'text', text: isContainer(v) ? 'container' : 'text' }[t];
  };

  // ═══════════════════════════════════════════════════════════════════════
  // parser
  // ═══════════════════════════════════════════════════════════════════════
  const WORD = /[A-Za-z0-9_À-￿]/;
  const CONSTANTS = {
    true: 1, false: 0, plain: 0, bold: 1, italic: 2, underline: 4, highlightyellow: 8, condense: 16, extend: 32,
    strikethrough: 64, smallcaps: 128, superscript: 256, subscript: 512, uppercase: 1024, lowercase: 2048,
    titlecase: 4096, wordunderline: 8192, doubleunderline: 16384, allstyles: 32767,
    lower: -1, higher: 1, jsonraw: 0, jsonstring: 1, jsonnumber: 2, jsonobject: 3, jsonarray: 4, jsonboolean: 5, jsonnull: 6
  };
  const NOARG = new Set(['pi', 'random', 'self']);

  // scope: {toNames(): [names...], fields(toName|null): [{name, ref}], customFunction(name): {params, formula} | null}
  function parse(src, scope) {
    src = String(src == null ? '' : src);
    let pos = 0;
    const letScopes = [];
    const n = src.length;

    function err(msg, at, code) { throw new CalcError(msg, at == null ? pos : at, code); }
    function skip() {
      for (;;) {
        while (pos < n && /\s/.test(src[pos])) pos++;
        if (src.startsWith('//', pos)) { while (pos < n && src[pos] !== '\n' && src[pos] !== '\r') pos++; continue; }
        if (src.startsWith('/*', pos)) { const e = src.indexOf('*/', pos + 2); if (e < 0) err('The comment is not terminated with "*/".', pos, 1205); pos = e + 2; continue; }
        break;
      }
    }
    function peek(s) { skip(); return src.startsWith(s, pos); }
    function eat(s) { if (peek(s)) { pos += s.length; return true; } return false; }
    function expect(s, msg) { if (!eat(s)) err(msg || ('"' + s + '" is expected here.'), pos, 1204); }
    function keyword(w) {
      skip();
      if (src.substr(pos, w.length).toLowerCase() === w && !WORD.test(src[pos + w.length] || '') && !WORD.test(src[pos - 1] || ' ')) return true;
      return false;
    }
    function sepEat() { return eat(';') || eat(','); }

    function expr() { return orExpr(); }
    function orExpr() {
      let a = andExpr();
      for (;;) {
        if (keyword('or')) { pos += 2; a = { k: 'bin', op: 'or', a, b: andExpr() }; }
        else if (keyword('xor')) { pos += 3; a = { k: 'bin', op: 'xor', a, b: andExpr() }; }
        else return a;
      }
    }
    function andExpr() {
      let a = notExpr();
      while (keyword('and')) { pos += 3; a = { k: 'bin', op: 'and', a, b: notExpr() }; }
      return a;
    }
    function notExpr() {
      if (keyword('not')) { pos += 3; return { k: 'un', op: 'not', a: notExpr() }; }
      return cmpExpr();
    }
    const CMP = [['<>', '≠'], ['≠', '≠'], ['<=', '≤'], ['≤', '≤'], ['>=', '≥'], ['≥', '≥'], ['=', '='], ['<', '<'], ['>', '>']];
    function cmpExpr() {
      let a = catExpr();
      for (;;) {
        skip();
        const m = CMP.find(([s]) => src.startsWith(s, pos));
        if (!m) return a;
        pos += m[0].length;
        a = { k: 'bin', op: m[1], a, b: catExpr() };
      }
    }
    function catExpr() {
      let a = addExpr();
      while (eat('&')) a = { k: 'bin', op: '&', a, b: addExpr() };
      return a;
    }
    function addExpr() {
      let a = mulExpr();
      for (;;) {
        skip();
        if (src[pos] === '+' || src[pos] === '-') { const op = src[pos++]; a = { k: 'bin', op, a, b: mulExpr() }; }
        else return a;
      }
    }
    function mulExpr() {
      let a = powExpr();
      for (;;) {
        skip();
        if (src[pos] === '*' || src[pos] === '/') { const op = src[pos++]; a = { k: 'bin', op, a, b: powExpr() }; }
        else return a;
      }
    }
    function powExpr() {
      let a = unary();
      while (eat('^')) a = { k: 'bin', op: '^', a, b: unary() };
      return a;
    }
    function unary() {
      skip();
      if (src[pos] === '-') { pos++; return { k: 'un', op: '-', a: unary() }; }
      if (src[pos] === '+') { pos++; return unary(); }
      return postfix(primary());
    }
    function postfix(node) {
      // repetition: Field[2], $var[3]
      if ((node.k === 'field' || node.k === 'var') && peek('[')) {
        pos++;
        node.rep = expr();
        expect(']', 'A "]" is expected here.');
      }
      return node;
    }
    function primary() {
      skip();
      const start = pos;
      if (pos >= n) err('The calculation ends before it is complete.', pos, 1203);
      const c = src[pos];
      if (c === '(') { pos++; const e = expr(); expect(')', 'Unbalanced parentheses: ")" is expected here.'); return e; }
      if (c === '"') return { k: 'str', v: readString() };
      if (c === '¶') { pos++; return { k: 'str', v: '\n' }; }
      if (c === '[') { // list argument: ["a" ; "b"]
        pos++; const items = [expr()];
        while (sepEat()) items.push(expr());
        expect(']', 'A "]" is expected here.');
        return { k: 'list', items, pos: start };
      }
      const num = src.slice(pos).match(/^(\d+\.?\d*|\.\d+)(e[-+]?\d+)?/i);
      if (num) { pos += num[0].length; return { k: 'num', v: parseFloat(num[0]) }; }
      if (c === '$') {
        const m = src.slice(pos).match(/^\$\$?[^\s;,()[\]+\-*/^&=<>≠≤≥"¶]+/);
        if (!m) err('A variable name is expected here.', pos, 1209);
        pos += m[0].length;
        if (m[0].startsWith('${')) { // ${Table::Field Name}
          const end = src.indexOf('}', start);
          if (end < 0) err('A "}" is expected here.', start);
          pos = end + 1;
          return fieldByText(src.slice(start + 2, end), start);
        }
        return { k: 'var', name: m[0], pos: start };
      }
      if (c === '~' || WORD.test(c)) return named(start);
      err('A number, text constant, field name or "(" is expected here.', pos, 1204);
    }
    function readString() {
      let out = ''; pos++;
      for (;;) {
        if (pos >= n) err('Text constants must end with a quotation mark.', pos, 1206);
        const ch = src[pos++];
        if (ch === '"') break;
        if (ch === '\\') {
          const nx = src[pos++];
          if (nx === '¶') out += '¶'; else if (nx === 'n') out += '\n'; else if (nx === 't') out += '\t'; else out += nx == null ? '' : nx;
        } else if (ch === '¶') out += '\n';
        else out += ch;
      }
      return out;
    }
    function fieldByText(text, at) {
      const m = text.split('::');
      const toName = m.length > 1 ? m[0].trim() : null;
      const fname = (m.length > 1 ? m.slice(1).join('::') : m[0]).trim();
      const list = scope.fields(toName);
      if (!list) err('The specified table cannot be found.', at, 106);
      const f = list.find(x => x.name.toLowerCase() === fname.toLowerCase());
      if (!f) err('The specified field cannot be found.', at, 102);
      return { k: 'field', ref: f.ref, name: (toName ? toName + '::' : '') + f.name, pos: at };
    }
    function longestAt(names) {
      const rest = src.slice(pos, pos + 200).toLowerCase();
      let best = null;
      for (const nm of names) {
        const l = nm.toLowerCase();
        if (rest.startsWith(l) && !WORD.test(src[pos + l.length] || '') && (!best || l.length > best.length)) best = nm;
      }
      return best;
    }
    function named(start) {
      // 1) TO::Field
      const toName = longestAtTO();
      if (toName) {
        pos += toName.length; skip(); pos += 2; skip();
        const fields = scope.fields(toName) || [];
        const fn = longestAt(fields.map(f => f.name));
        if (!fn) err('The specified field cannot be found.', pos, 102);
        const f = fields.find(x => x.name === fn);
        pos += fn.length;
        return { k: 'field', ref: f.ref, name: toName + '::' + fn, pos: start };
      }
      const wm = src.slice(pos).match(/^~?[A-Za-z_À-￿][A-Za-z0-9_.À-￿]*/);
      const word = wm ? wm[0] : '';
      // 2) function call
      if (word && /^\s*\(/.test(src.slice(pos + word.length))) {
        const lw = word.toLowerCase();
        if (lw === 'get') return getCall(start, word);
        if (lw === 'let') return letCall(start);
        if (lw === 'while') return whileCall(start);
        if (LIB[lw] || scope.customFunction(word)) {
          pos += word.length; skip(); pos++;
          const args = [];
          skip();
          if (!peek(')')) { args.push(expr()); while (sepEat()) args.push(expr()); }
          expect(')', 'There are too few separators or ")" is missing in this function.');
          const def = LIB[lw];
          if (def) {
            if (args.length < def.min) err('There are too few parameters in this function.', pos - 1, 1201);
            if (def.max != null && args.length > def.max) err('There are too many parameters in this function.', pos - 1, 1202);
            return { k: 'call', name: lw, args, pos: start };
          }
          const cf = scope.customFunction(word);
          if (args.length !== cf.params.length) err('There are ' + (args.length < cf.params.length ? 'too few' : 'too many') + ' parameters in this function.', pos - 1, args.length < cf.params.length ? 1201 : 1202);
          return { k: 'cf', name: cf.name, args, pos: start };
        }
      }
      // 3) Let / While variables and custom function parameters
      for (let i = letScopes.length - 1; i >= 0; i--) {
        const hit = letScopes[i].find(v => v.toLowerCase() === word.toLowerCase());
        if (hit) {
          // a longer field name may start with the same word
          const fn = longestAt((scope.fields(null) || []).map(f => f.name));
          if (fn && fn.length > word.length) break;
          pos += word.length;
          return { k: 'lv', name: hit.toLowerCase(), pos: start };
        }
      }
      // 4) a field of the context table
      const fields = scope.fields(null) || [];
      const fn = longestAt(fields.map(f => f.name));
      if (fn) {
        const f = fields.find(x => x.name === fn);
        pos += fn.length;
        return { k: 'field', ref: f.ref, name: fn, pos: start };
      }
      const lw = word.toLowerCase();
      if (lw in CONSTANTS) { pos += word.length; return { k: 'num', v: CONSTANTS[lw] }; }
      if (NOARG.has(lw)) { pos += word.length; return { k: 'call', name: lw, args: [], pos: start }; }
      if (word && /^\s*\(/.test(src.slice(pos + word.length))) err('The specified function cannot be found.', start, 1208);
      err('The specified field cannot be found.', start, 102);
    }
    function longestAtTO() {
      const names = scope.toNames();
      const rest = src.slice(pos, pos + 200).toLowerCase();
      let best = null;
      for (const nm of names) {
        const l = nm.toLowerCase();
        if (rest.startsWith(l) && /^\s*::/.test(src.slice(pos + l.length, pos + l.length + 6)) && (!best || l.length > best.length)) best = nm;
      }
      return best;
    }
    function getCall(start, word) {
      pos += word.length; skip(); pos++; skip();
      const m = src.slice(pos).match(/^[A-Za-z]+/);
      if (!m) err('This parameter is an invalid Get function parameter.', pos, 1217);
      pos += m[0].length;
      expect(')', 'A ")" is expected here.');
      const name = m[0].toLowerCase();
      if (!GET_NAMES.has(name)) err('This parameter is an invalid Get function parameter.', start, 1217);
      return { k: 'get', name, pos: start };
    }
    function bindings() {
      const out = [];
      const one = () => {
        skip();
        const m = src.slice(pos).match(/^(\$\$|\$|~)?[A-Za-z_À-￿][A-Za-z0-9_.À-￿]*(\[[^\]]*\])?/);
        if (!m) err('A name is expected here.', pos, 1209);
        let name = m[0]; let repSrc = null;
        const br = name.indexOf('[');
        if (br > 0) { repSrc = name.slice(br + 1, -1); name = name.slice(0, br); }
        pos += m[0].length;
        expect('=', 'An "=" is expected here.');
        const local = !name.startsWith('$');
        if (local) letScopes[letScopes.length - 1].push(name);
        const value = expr();
        out.push({ name: local ? name.toLowerCase() : name, local, value, rep: repSrc ? parse(repSrc, scope) : null });
      };
      if (eat('[')) { one(); while (sepEat()) { if (peek(']')) break; one(); } expect(']', 'A "]" is expected here.'); }
      else one();
      return out;
    }
    function letCall(start) {
      pos += 3; skip(); pos++;
      letScopes.push([]);
      const binds = bindings();
      if (!sepEat()) err('There are too few separators in this function.', pos, 1201);
      const body = expr();
      letScopes.pop();
      expect(')', 'A ")" is expected here.');
      return { k: 'let', binds, body, pos: start };
    }
    function whileCall(start) {
      pos += 5; skip(); pos++;
      letScopes.push([]);
      const init = bindings();
      if (!sepEat()) err('There are too few separators in this function.', pos, 1201);
      const cond = expr();
      if (!sepEat()) err('There are too few separators in this function.', pos, 1201);
      const logic = bindings();
      if (!sepEat()) err('There are too few separators in this function.', pos, 1201);
      const result = expr();
      letScopes.pop();
      expect(')', 'A ")" is expected here.');
      return { k: 'while', init, cond, logic, result, pos: start };
    }

    if (scope.params) letScopes.push(scope.params.slice());
    skip();
    if (pos >= n) return { k: 'str', v: '', empty: true };
    const ast = expr();
    skip();
    if (pos < n) err('An operator (for example +, -, *, &) is expected here.', pos, 1212);
    return ast;
  }

  // field references in an AST: [{ref, name, related?}]
  function refs(ast, out) {
    out = out || [];
    (function walk(nd) {
      if (!nd || typeof nd !== 'object') return;
      if (nd.k === 'field') out.push(nd);
      for (const k in nd) { const v = nd[k]; if (Array.isArray(v)) v.forEach(walk); else if (v && typeof v === 'object' && k !== 'ref') walk(v); }
    })(ast);
    return out;
  }
  function usesGet(ast) {
    let found = false;
    (function walk(nd) {
      if (!nd || typeof nd !== 'object' || found) return;
      if (nd.k === 'get' || nd.k === 'var' || (nd.k === 'call' && /^(random|self|getfield|evaluate|executesql|getnthrecord|getsummary|lookup|lookupnext|getlayoutobjectattribute)$/.test(nd.name))) { found = true; return; }
      for (const k in nd) { const v = nd[k]; if (Array.isArray(v)) v.forEach(walk); else if (v && typeof v === 'object' && k !== 'ref') walk(v); }
    })(ast);
    return found;
  }

  // ═══════════════════════════════════════════════════════════════════════
  // evaluator
  // env: {field(ref, rep, all), getVar(name, rep), setVar(name, value, rep), get(name), self(),
  //       customFunction(name) -> {params, ast}, summary(ref, breakRef), nth(ref, n), sql(...),
  //       fieldByName(text) -> ref, fieldName(ref), design(name, args), layoutObject(name, attr, rep, row),
  //       parse(text) -> ast, lookupNext(ref, dir), fieldType(ref), isRelated(ref), repetitions(ref)}
  // ═══════════════════════════════════════════════════════════════════════
  const MAX_DEPTH = 1500;
  function evaluate(ast, env, locals) {
    let depth = 0;
    function ev(nd, L) {
      switch (nd.k) {
        case 'num': return nd.v;
        case 'str': return nd.v;
        case 'field': {
          const rep = nd.rep ? Math.max(1, Math.floor(V.num(ev(nd.rep, L)))) : null;
          return env.field(nd.ref, rep, false);
        }
        case 'var': {
          const rep = nd.rep ? Math.floor(V.num(ev(nd.rep, L))) : 1;
          return env.getVar(nd.name, rep);
        }
        case 'lv': {
          for (let s = L; s; s = s.parent) if (Object.prototype.hasOwnProperty.call(s.vars, nd.name)) return s.vars[nd.name];
          return '';
        }
        case 'get': return env.get(nd.name);
        case 'un': {
          const a = ev(nd.a, L);
          if (nd.op === 'not') return V.bool(a) ? 0 : 1;
          if (a instanceof FMTime) return new FMTime(-a.s);
          return -V.num(a);
        }
        case 'bin': return binop(nd, L);
        case 'list': throw new CalcError('A list ["..." ; "..."] cannot be used here.', nd.pos, 1211);
        case 'let': {
          const S = { vars: Object.create(null), parent: L };
          for (const b of nd.binds) assign(b, ev(b.value, S), S);
          return ev(nd.body, S);
        }
        case 'while': {
          const S = { vars: Object.create(null), parent: L };
          for (const b of nd.init) assign(b, ev(b.value, S), S);
          let guard = 0;
          while (V.bool(ev(nd.cond, S))) {
            if (++guard > 50000) throw new CalcError('While: the maximum number of iterations was exceeded.', nd.pos, 1240);
            for (const b of nd.logic) assign(b, ev(b.value, S), S);
          }
          return ev(nd.result, S);
        }
        case 'call': return call(nd, L);
        case 'cf': {
          const cf = env.customFunction(nd.name);
          if (!cf) throw new CalcError('The specified function cannot be found.', nd.pos, 1208);
          if (++depth > MAX_DEPTH) throw new CalcError('The maximum recursion depth was exceeded.', nd.pos, 1240);
          const S = { vars: Object.create(null), parent: null };
          cf.params.forEach((p, i) => { S.vars[p.toLowerCase()] = ev(nd.args[i], L); });
          try { return ev(cf.ast, S); } finally { depth--; }
        }
      }
      throw new CalcError('Unknown expression', nd.pos);
    }
    function assign(b, value, S) {
      if (b.local) S.vars[b.name] = value;
      else env.setVar(b.name, value, b.rep ? Math.floor(V.num(ev(b.rep, S))) : 1);
    }
    function binop(nd, L) {
      const op = nd.op;
      if (op === 'and') return V.bool(ev(nd.a, L)) && V.bool(ev(nd.b, L)) ? 1 : 0;
      if (op === 'or') return V.bool(ev(nd.a, L)) || V.bool(ev(nd.b, L)) ? 1 : 0;
      const a = ev(nd.a, L), b = ev(nd.b, L);
      switch (op) {
        case 'xor': return V.bool(a) !== V.bool(b) ? 1 : 0;
        case '&': {
          if (a instanceof FMStyled || b instanceof FMStyled) return new FMStyled(V.text(a) + V.text(b), styledHtml(a) + styledHtml(b));
          return V.text(a) + V.text(b);
        }
        case '=': return V.compare(a, b) === 0 ? 1 : 0;
        case '≠': return V.compare(a, b) !== 0 ? 1 : 0;
        case '<': return V.compare(a, b) < 0 ? 1 : 0;
        case '>': return V.compare(a, b) > 0 ? 1 : 0;
        case '≤': return V.compare(a, b) <= 0 ? 1 : 0;
        case '≥': return V.compare(a, b) >= 0 ? 1 : 0;
        case '+': {
          if (a instanceof FMDate && b instanceof FMTime) return new FMTimestamp((a.n - 1) * 86400 + b.s);
          if (a instanceof FMDate) return new FMDate(a.n + V.num(b));
          if (b instanceof FMDate && !(a instanceof FMDate)) return new FMDate(b.n + V.num(a));
          if (a instanceof FMTimestamp) return new FMTimestamp(a.s + V.num(b));
          if (b instanceof FMTimestamp) return new FMTimestamp(b.s + V.num(a));
          if (a instanceof FMTime || b instanceof FMTime) return new FMTime(V.num(a) + V.num(b));
          return V.num(a) + V.num(b);
        }
        case '-': {
          if (a instanceof FMDate && b instanceof FMDate) return a.n - b.n;
          if (a instanceof FMDate) return new FMDate(a.n - V.num(b));
          if (a instanceof FMTimestamp && (b instanceof FMTimestamp)) return new FMTime(a.s - b.s);
          if (a instanceof FMTimestamp) return new FMTimestamp(a.s - V.num(b));
          if (a instanceof FMTime) return new FMTime(a.s - V.num(b));
          return V.num(a) - V.num(b);
        }
        case '*': { const r = V.num(a) * V.num(b); return (a instanceof FMTime || b instanceof FMTime) ? new FMTime(r) : r; }
        case '/': { const d = V.num(b); if (d === 0) return '?'; const r = V.num(a) / d; return a instanceof FMTime && !(b instanceof FMTime) ? new FMTime(r) : r; }
        case '^': return Math.pow(V.num(a), V.num(b));
      }
      throw new CalcError('Unknown operator ' + op, nd.pos);
    }
    // aggregate arguments: a related or repeating field without a repetition gives every value
    function spread(argNodes, L) {
      const out = [];
      for (const a of argNodes) {
        if (a.k === 'field' && !a.rep && (env.isRelated(a.ref) || env.repetitions(a.ref) > 1)) out.push(...env.field(a.ref, null, true));
        else if (a.k === 'list') a.items.forEach(x => out.push(ev(x, L)));
        else out.push(ev(a, L));
      }
      return out;
    }
    function call(nd, L) {
      const def = LIB[nd.name];
      if (def.lazy) return def.fn(nd.args, { ev: x => ev(x, L), L, env, spread: xs => spread(xs, L), node: nd, evIn: (x, S) => ev(x, S) });
      const args = nd.args.map(a => a.k === 'list' ? { list: a.items.map(x => ev(x, L)) } : ev(a, L));
      return def.fn(args, env, nd);
    }
    try {
      return ev(ast, locals || null);
    } catch (e) {
      if (e instanceof RangeError) throw new CalcError('The calculation is too complex (maximum recursion reached).', ast.pos, 1240);
      throw e;
    }
  }

  function styledHtml(v) { return v instanceof FMStyled ? v.html : FM.esc(V.text(v)).replace(/\n/g, '<br>'); }

  // ═══════════════════════════════════════════════════════════════════════
  // function library
  // ═══════════════════════════════════════════════════════════════════════
  const LIB = Object.create(null);
  const CATALOG = [];
  function def(name, sig, cat, fn, o) {
    o = o || {};
    const m = sig.match(/\((.*)\)/);
    let min = 0, max = 0;
    if (m && m[1].trim()) {
      let inner = m[1]; while (/\([^()]*\)/.test(inner)) inner = inner.replace(/\([^()]*\)/g, '');
      const brace = inner.indexOf('{');
      min = (brace >= 0 ? inner.slice(0, brace) : inner).split(';').map(x => x.trim()).filter(Boolean).length;
      max = /\.\.\./.test(inner) ? null : inner.replace(/[{}]/g, '').split(';').map(x => x.trim()).filter(Boolean).length;
    }
    if (o.min != null) min = o.min;
    if (o.max !== undefined) max = o.max;
    LIB[name.toLowerCase()] = { name, fn, lazy: !!o.lazy, min, max };
    if (!o.hidden) CATALOG.push({ name, sig, cat });
  }
  const T = V.text, N = V.num;
  const ret = a => a.join('\n') + (a.length ? '\n' : '');           // values, each followed by ¶
  const values = t => FM.splitValues(V.text(t));
  const words = t => [...String(t).matchAll(/[\p{L}\p{N}_]+(?:['’.@][\p{L}\p{N}_]+)*/gu)];
  const roundTo = (x, p) => { const s = Math.sign(x) || 1; return s * Number(Math.round(Number(Math.abs(x) + 'e' + p)) + 'e' + (-p)); };
  const truncTo = (x, p) => { const s = Math.sign(x) || 1; return s * Number(Math.floor(Number(Math.abs(x) + 'e' + p)) + 'e' + (-p)); };
  const numOr = (v, fb) => { const n = V.numOrNull(v); return n == null ? fb : n; };
  const out = v => (typeof v === 'number' && !isFinite(v)) ? '?' : v;

  // ── text ────────────────────────────────────────────────────────────────
  def('Char', 'Char ( codePoints )', 'Text', ([c]) => {
    const s = FM.num.plain(Math.floor(Math.abs(N(c)))); const groups = [];
    for (let i = s.length; i > 0; i -= 5) groups.push(+s.slice(Math.max(0, i - 5), i));
    return groups.map(g => { try { return String.fromCodePoint(g === 13 ? 10 : g); } catch (e) { return ''; } }).join('');
  });
  def('Code', 'Code ( text )', 'Text', ([t]) => {
    const cps = [...T(t)].map(ch => ch === '\n' ? 13 : ch.codePointAt(0));
    if (!cps.length) return '';
    return Number(cps.reverse().map((c, i) => i === 0 ? String(c) : String(c).padStart(5, '0')).join(''));
  });
  def('Exact', 'Exact ( originalText ; comparisonText )', 'Text', ([a, b]) => T(a) === T(b) ? 1 : 0);
  def('Filter', 'Filter ( textToFilter ; filterText )', 'Text', ([a, b]) => { const keep = new Set([...T(b)]); return [...T(a)].filter(c => keep.has(c)).join(''); });
  def('FilterValues', 'FilterValues ( textToFilter ; filterValues )', 'Text', ([a, b]) => { const keep = new Set(values(b).map(x => x.toLowerCase())); return ret(values(a).filter(v => keep.has(v.toLowerCase()))); });
  def('GetAsBoolean', 'GetAsBoolean ( data )', 'Text', ([v]) => V.bool(v) ? 1 : 0);
  def('GetAsCSS', 'GetAsCSS ( text )', 'Text', ([v]) => '<SPAN STYLE= "" >' + styledHtml(v) + '</SPAN>');
  def('GetAsDate', 'GetAsDate ( text )', 'Text', ([v]) => V.empty(v) ? '' : (V.date(v) || '?'));
  def('GetAsNumber', 'GetAsNumber ( text )', 'Text', ([v]) => { const n = V.numOrNull(v); return n == null ? '' : n; });
  def('GetAsText', 'GetAsText ( data )', 'Text', ([v]) => T(v));
  def('GetAsTime', 'GetAsTime ( text )', 'Text', ([v]) => V.empty(v) ? '' : (V.time(v) || '?'));
  def('GetAsTimestamp', 'GetAsTimestamp ( text )', 'Text', ([v]) => V.empty(v) ? '' : (V.ts(v) || '?'));
  def('GetAsURLEncoded', 'GetAsURLEncoded ( text )', 'Text', ([v]) => encodeURIComponent(T(v)).replace(/%20/g, '%20'));
  def('GetValue', 'GetValue ( listOfValues ; valueNumber )', 'Text', ([l, n]) => values(l)[Math.floor(N(n)) - 1] || '');
  def('Left', 'Left ( text ; numberOfCharacters )', 'Text', ([t, n]) => [...T(t)].slice(0, Math.max(0, Math.floor(N(n)))).join(''));
  def('LeftValues', 'LeftValues ( text ; numberOfValues )', 'Text', ([t, n]) => ret(values(t).slice(0, Math.max(0, Math.floor(N(n))))));
  def('LeftWords', 'LeftWords ( text ; numberOfWords )', 'Text', ([t, n]) => { const s = T(t), w = words(s), k = Math.floor(N(n)); if (k <= 0 || !w.length) return ''; const e = w[Math.min(k, w.length) - 1]; return s.slice(w[0].index, e.index + e[0].length); });
  def('Length', 'Length ( text )', 'Text', ([t]) => isContainer(t) ? (t.size || 0) : [...T(t)].length);
  def('Lower', 'Lower ( text )', 'Text', ([t]) => T(t).toLowerCase());
  def('Middle', 'Middle ( text ; start ; numberOfCharacters )', 'Text', ([t, s, n]) => { const a = [...T(t)]; const st = Math.max(1, Math.floor(N(s))); return a.slice(st - 1, st - 1 + Math.max(0, Math.floor(N(n)))).join(''); });
  def('MiddleValues', 'MiddleValues ( text ; startingValue ; numberOfValues )', 'Text', ([t, s, n]) => { const st = Math.max(1, Math.floor(N(s))); return ret(values(t).slice(st - 1, st - 1 + Math.max(0, Math.floor(N(n))))); });
  def('MiddleWords', 'MiddleWords ( text ; startingWord ; numberOfWords )', 'Text', ([t, s, n]) => {
    const str = T(t), w = words(str); const st = Math.max(1, Math.floor(N(s))), k = Math.floor(N(n));
    if (k <= 0 || st > w.length) return '';
    const a = w[st - 1], e = w[Math.min(w.length, st - 1 + k) - 1];
    return str.slice(a.index, e.index + e[0].length);
  });
  def('PatternCount', 'PatternCount ( text ; searchString )', 'Text', ([t, s]) => {
    const hay = T(t).toLowerCase(), nd = T(s).toLowerCase(); if (!nd) return 0;
    let c = 0, i = hay.indexOf(nd); while (i >= 0) { c++; i = hay.indexOf(nd, i + 1); } return c;
  });
  def('Position', 'Position ( text ; searchString ; start ; occurrence )', 'Text', ([t, s, st, oc]) => {
    const hay = T(t).toLowerCase(), nd = T(s).toLowerCase(); let start = Math.floor(N(st)); const occ = Math.floor(N(oc));
    if (!nd || occ === 0) return 0;
    if (start < 1) start = 1;
    if (occ > 0) { let i = start - 2, c = 0; while (c < occ) { i = hay.indexOf(nd, i + 1); if (i < 0) return 0; c++; } return i + 1; }
    let i = Math.min(start - 1, hay.length), c = 0;
    while (c < -occ) { i = hay.lastIndexOf(nd, i - (c ? 1 : 0)); if (i < 0) return 0; c++; }
    return i + 1;
  });
  def('Proper', 'Proper ( text )', 'Text', ([t]) => T(t).toLowerCase().replace(/(^|[^\p{L}\p{N}'’])(\p{L})/gu, (m, a, b) => a + b.toUpperCase()));
  def('Quote', 'Quote ( text )', 'Text', ([t]) => '"' + T(t).replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/\n/g, '\\¶') + '"');
  def('Replace', 'Replace ( text ; start ; numberOfCharacters ; replacementText )', 'Text', ([t, s, n, r]) => { const a = [...T(t)]; const st = Math.max(1, Math.floor(N(s))); a.splice(st - 1, Math.max(0, Math.floor(N(n))), T(r)); return a.join(''); });
  def('Right', 'Right ( text ; numberOfCharacters )', 'Text', ([t, n]) => { const a = [...T(t)]; const k = Math.max(0, Math.floor(N(n))); return k ? a.slice(-k).join('') : ''; });
  def('RightValues', 'RightValues ( text ; numberOfValues )', 'Text', ([t, n]) => { const k = Math.max(0, Math.floor(N(n))); return k ? ret(values(t).slice(-k)) : ''; });
  def('RightWords', 'RightWords ( text ; numberOfWords )', 'Text', ([t, n]) => { const s = T(t), w = words(s), k = Math.floor(N(n)); if (k <= 0 || !w.length) return ''; const a = w[Math.max(0, w.length - k)], e = w[w.length - 1]; return s.slice(a.index, e.index + e[0].length); });
  def('SerialIncrement', 'SerialIncrement ( text ; incrementBy )', 'Text', ([t, by]) => serialIncrement(T(t), Math.floor(N(by))));
  def('SortValues', 'SortValues ( values {; datatype ; locale } )', 'Text', ([v, dt]) => sortValues(values(v), dt));
  def('Substitute', 'Substitute ( text ; [ searchString ; replaceString ] {; ...} )', 'Text', (args) => {
    let s = T(args[0]);
    const pairs = args.length === 3 && !args[1].list ? [[args[1], args[2]]] : args.slice(1).map(a => a.list || [a, '']);
    for (const [a, b] of pairs) { const x = T(a); if (x) s = s.split(x).join(T(b)); }
    return s;
  }, { min: 2, max: null });
  def('Trim', 'Trim ( text )', 'Text', ([t]) => T(t).replace(/^[  ]+|[  ]+$/g, ''));
  def('TrimAll', 'TrimAll ( text ; trimSpaces ; trimType )', 'Text', ([t]) => T(t).replace(/[  ]{2,}/g, ' ').replace(/^[  ]+|[  ]+$/gm, ''));
  def('UniqueValues', 'UniqueValues ( values {; datatype ; locale } )', 'Text', ([v, dt]) => {
    const seen = new Set(); const outv = [];
    const type = Math.abs(Math.floor(numOr(dt, 1)));
    values(v).forEach(x => { const k = type === 1 ? x.toLowerCase() : T(conv(x, type)); if (!seen.has(k)) { seen.add(k); outv.push(x); } });
    return ret(outv);
  });
  def('Upper', 'Upper ( text )', 'Text', ([t]) => T(t).toUpperCase());
  def('ValueCount', 'ValueCount ( text )', 'Text', ([t]) => values(t).length);
  def('WordCount', 'WordCount ( text )', 'Text', ([t]) => words(T(t)).length);
  def('Hiragana', 'Hiragana ( text )', 'Text', ([t]) => T(t), { hidden: true });
  def('Base64Decode', 'Base64Decode ( text {; fileNameWithExtension } )', 'Text', ([t]) => { try { return new TextDecoder().decode(Uint8Array.from(atob(T(t).replace(/\s/g, '')), c => c.charCodeAt(0))); } catch (e) { return '?'; } });
  def('Base64Encode', 'Base64Encode ( data )', 'Text', ([t]) => b64(isBin(t) ? t.bin : new TextEncoder().encode(T(t))));
  def('Base64EncodeRFC', 'Base64EncodeRFC ( RFCNumber ; data )', 'Text', ([rfc, t]) => { let s = b64(isBin(t) ? t.bin : new TextEncoder().encode(T(t))); const r = N(rfc); if (r === 4648) s = s.replace(/\+/g, '-').replace(/\//g, '_'); if (r === 2045) s = s.replace(/(.{76})/g, '$1\r\n'); return s; });
  def('HexEncode', 'HexEncode ( data )', 'Text', ([t]) => [...(isBin(t) ? t.bin : new TextEncoder().encode(T(t)))].map(b => b.toString(16).padStart(2, '0')).join(''));
  def('HexDecode', 'HexDecode ( text {; fileNameWithExtension } )', 'Text', ([t]) => { const s = T(t).replace(/\s/g, ''); if (!/^([0-9a-f]{2})*$/i.test(s)) return '?'; const b = new Uint8Array(s.length / 2); for (let i = 0; i < b.length; i++) b[i] = parseInt(s.substr(i * 2, 2), 16); return new TextDecoder().decode(b); });
  def('CryptDigest', 'CryptDigest ( data ; algorithm )', 'Text', ([t, a]) => {
    const bytes = isBin(t) ? t.bin : new TextEncoder().encode(T(t));
    const alg = T(a).toUpperCase().replace(/-/g, '');
    const f = { MD5: md5, SHA1: sha1, SHA256: sha256 }[alg];
    return f ? { bin: f(bytes), name: '' } : '?';
  });
  def('GetContainerAttribute', 'GetContainerAttribute ( sourceField ; attributeName )', 'Container', ([c, a]) => {
    if (!isContainer(c)) return '';
    const k = T(a).toLowerCase();
    if (k === 'filename') return c.name || ''; if (k === 'filesize') return c.size || 0;
    if (k === 'all') return 'Filename: ' + (c.name || '') + '\nFile size: ' + (c.size || 0) + '\nMIME type: ' + (c.mime || '');
    if (k === 'mimetype' || k === 'type') return c.mime || '';
    return '';
  });
  def('GetThumbnail', 'GetThumbnail ( sourceField ; width ; height )', 'Container', ([c]) => c);
  def('GetHeight', 'GetHeight ( sourceField )', 'Container', () => '', { hidden: false });
  def('GetWidth', 'GetWidth ( sourceField )', 'Container', () => '');

  // text formatting
  const styleCss = st => {
    const css = [];
    if (st & 1) css.push('font-weight:bold'); if (st & 2) css.push('font-style:italic');
    const deco = []; if (st & (4 | 8192 | 16384)) deco.push('underline'); if (st & 64) deco.push('line-through');
    if (deco.length) css.push('text-decoration:' + deco.join(' '));
    if (st & 8) css.push('background:#ff0'); if (st & 128) css.push('font-variant:small-caps');
    if (st & 256) css.push('vertical-align:super;font-size:smaller'); if (st & 512) css.push('vertical-align:sub;font-size:smaller');
    if (st & 1024) css.push('text-transform:uppercase'); if (st & 2048) css.push('text-transform:lowercase'); if (st & 4096) css.push('text-transform:capitalize');
    if (st & 16) css.push('letter-spacing:-.05em'); if (st & 32) css.push('letter-spacing:.1em');
    return css.join(';');
  };
  const wrapStyled = (t, css) => new FMStyled(T(t), '<span style="' + css + '">' + styledHtml(t) + '</span>');
  def('RGB', 'RGB ( red ; green ; blue )', 'Text Formatting', ([r, g, b]) => (FM.clamp(Math.floor(N(r)), 0, 255) << 16) + (FM.clamp(Math.floor(N(g)), 0, 255) << 8) + FM.clamp(Math.floor(N(b)), 0, 255));
  def('TextColor', 'TextColor ( text ; RGB ( red ; green ; blue ) )', 'Text Formatting', ([t, c]) => wrapStyled(t, 'color:#' + Math.floor(N(c)).toString(16).padStart(6, '0')));
  def('TextColorRemove', 'TextColorRemove ( text {; RGB ( red ; green ; blue ) } )', 'Text Formatting', ([t]) => T(t));
  def('TextFont', 'TextFont ( text ; fontName {; fontScript } )', 'Text Formatting', ([t, f]) => wrapStyled(t, 'font-family:' + T(f).replace(/[;"<>]/g, '')));
  def('TextFontRemove', 'TextFontRemove ( text {; fontToRemove ; fontScript } )', 'Text Formatting', ([t]) => T(t));
  def('TextFormatRemove', 'TextFormatRemove ( text )', 'Text Formatting', ([t]) => T(t));
  def('TextSize', 'TextSize ( text ; fontSize )', 'Text Formatting', ([t, s]) => wrapStyled(t, 'font-size:' + FM.clamp(N(s), 1, 500) + 'px'));
  def('TextSizeRemove', 'TextSizeRemove ( text {; sizeToRemove } )', 'Text Formatting', ([t]) => T(t));
  def('TextStyleAdd', 'TextStyleAdd ( text ; styles )', 'Text Formatting', ([t, s]) => N(s) ? wrapStyled(t, styleCss(N(s))) : T(t));
  def('TextStyleRemove', 'TextStyleRemove ( text ; styles )', 'Text Formatting', ([t]) => T(t));

  // ── number ──────────────────────────────────────────────────────────────
  const n1 = f => ([x]) => { const v = V.numOrNull(x); return v == null ? '' : out(f(v)); };
  def('Abs', 'Abs ( number )', 'Number', n1(Math.abs));
  def('Ceiling', 'Ceiling ( number )', 'Number', n1(Math.ceil));
  def('Combination', 'Combination ( setSize ; numberOfChoices )', 'Number', ([a, b]) => { const n = Math.floor(N(a)), k = Math.floor(N(b)); if (k < 0 || k > n) return 0; let r = 1; for (let i = 1; i <= k; i++) r = r * (n - k + i) / i; return Math.round(r); });
  def('Div', 'Div ( number ; divisor )', 'Number', ([a, b]) => { const d = N(b); return d === 0 ? '?' : Math.floor(N(a) / d); });
  def('Exp', 'Exp ( number )', 'Number', n1(Math.exp));
  def('Factorial', 'Factorial ( number {; numberOfFactors } )', 'Number', ([a, b]) => { const n = Math.floor(N(a)); if (n < 0) return '?'; const k = b == null ? n : Math.floor(N(b)); let r = 1; for (let i = 0; i < k && n - i > 0; i++) r *= n - i; return r; });
  def('Floor', 'Floor ( number )', 'Number', n1(Math.floor));
  def('Int', 'Int ( number )', 'Number', n1(Math.trunc));
  def('Lg', 'Lg ( number )', 'Number', n1(x => x > 0 ? Math.log2(x) : NaN));
  def('Ln', 'Ln ( number )', 'Number', n1(x => x > 0 ? Math.log(x) : NaN));
  def('Log', 'Log ( number )', 'Number', n1(x => x > 0 ? Math.log10(x) : NaN));
  def('Mod', 'Mod ( number ; divisor )', 'Number', ([a, b]) => { const d = N(b), x = N(a); if (d === 0) return '?'; return x - d * Math.floor(x / d); });
  def('Random', 'Random', 'Number', () => Math.random());
  def('Round', 'Round ( number ; precision )', 'Number', ([x, p]) => { const v = V.numOrNull(x); return v == null ? '' : roundTo(v, Math.floor(N(p))); });
  def('SetPrecision', 'SetPrecision ( expression ; precision )', 'Number', ([x, p]) => { const v = V.numOrNull(x); return v == null ? '' : roundTo(v, FM.clamp(Math.floor(N(p)), 0, 15)); });
  def('Sign', 'Sign ( number )', 'Number', n1(Math.sign));
  def('Sqrt', 'Sqrt ( number )', 'Number', n1(x => x < 0 ? NaN : Math.sqrt(x)));
  def('Truncate', 'Truncate ( number ; precision )', 'Number', ([x, p]) => { const v = V.numOrNull(x); return v == null ? '' : truncTo(v, Math.floor(N(p))); });
  // trigonometric
  def('Pi', 'Pi', 'Trigonometric', () => Math.PI);
  def('Sin', 'Sin ( angleInRadians )', 'Trigonometric', n1(Math.sin));
  def('Cos', 'Cos ( angleInRadians )', 'Trigonometric', n1(Math.cos));
  def('Tan', 'Tan ( angleInRadians )', 'Trigonometric', n1(Math.tan));
  def('Asin', 'Asin ( number )', 'Trigonometric', n1(Math.asin));
  def('Acos', 'Acos ( number )', 'Trigonometric', n1(Math.acos));
  def('Atan', 'Atan ( number )', 'Trigonometric', n1(Math.atan));
  def('Degrees', 'Degrees ( angleInRadians )', 'Trigonometric', n1(x => x * 180 / Math.PI));
  def('Radians', 'Radians ( angleInDegrees )', 'Trigonometric', n1(x => x * Math.PI / 180));
  // financial
  def('FV', 'FV ( payment ; interestRate ; periods )', 'Financial', ([p, r, n]) => { const rate = N(r); return rate === 0 ? N(p) * N(n) : N(p) * (Math.pow(1 + rate, N(n)) - 1) / rate; });
  LIB.npv = { name: 'NPV', min: 2, max: 2, lazy: true, fn: (args, c) => { const pays = c.spread([args[0]]).flatMap(v => values(v).length > 1 ? values(v) : [v]); const r = N(c.ev(args[1])); return pays.reduce((s, v, i) => s + N(v) / Math.pow(1 + r, i + 1), 0); } };
  CATALOG.push({ name: 'NPV', sig: 'NPV ( payment ; interestRate )', cat: 'Financial' });
  def('PMT', 'PMT ( principal ; interestRate ; term )', 'Financial', ([p, r, n]) => { const rate = N(r), t = N(n); if (t === 0) return '?'; return rate === 0 ? N(p) / t : N(p) * rate / (1 - Math.pow(1 + rate, -t)); });
  def('PV', 'PV ( payment ; interestRate ; periods )', 'Financial', ([p, r, n]) => { const rate = N(r); return rate === 0 ? N(p) * N(n) : N(p) * (1 - Math.pow(1 + rate, -N(n))) / rate; });

  // ── date / time / timestamp ─────────────────────────────────────────────
  const dateArg = v => V.empty(v) ? null : V.date(v);
  const timeArg = v => V.empty(v) ? null : V.time(v);
  def('Date', 'Date ( month ; day ; year )', 'Date', ([m, d, y]) => { if ([m, d, y].some(V.empty)) return ''; const n = D.num(Math.floor(N(y)), Math.floor(N(m)), Math.floor(N(d))); return n < 1 ? '?' : new FMDate(n); });
  def('Day', 'Day ( date )', 'Date', ([d]) => { const x = dateArg(d); return x ? D.parts(x.n)[2] : ''; });
  def('DayName', 'DayName ( date )', 'Date', ([d]) => { const x = dateArg(d); return x ? D.DAYS[D.dow(x.n) - 1] : ''; });
  def('DayOfWeek', 'DayOfWeek ( date )', 'Date', ([d]) => { const x = dateArg(d); return x ? D.dow(x.n) : ''; });
  def('DayOfYear', 'DayOfYear ( date )', 'Date', ([d]) => { const x = dateArg(d); if (!x) return ''; const y = D.parts(x.n)[0]; return x.n - D.num(y, 1, 1) + 1; });
  def('Month', 'Month ( date )', 'Date', ([d]) => { const x = dateArg(d); return x ? D.parts(x.n)[1] : ''; });
  def('MonthName', 'MonthName ( date )', 'Date', ([d]) => { const x = dateArg(d); return x ? D.MONTHS[D.parts(x.n)[1] - 1] : ''; });
  def('WeekOfYear', 'WeekOfYear ( date )', 'Date', ([d]) => { const x = dateArg(d); if (!x) return ''; const jan1 = D.num(D.parts(x.n)[0], 1, 1); return Math.floor((x.n - jan1 + D.dow(jan1) - 1) / 7) + 1; });
  def('WeekOfYearFiscal', 'WeekOfYearFiscal ( date ; startingDay )', 'Date', ([d, s]) => {
    const x = dateArg(d); if (!x) return '';
    const start = FM.clamp(Math.floor(N(s)) || 1, 1, 7);
    const weekStart = n => n - ((D.dow(n) - start + 7) % 7);
    const y = D.parts(x.n)[0];
    const firstWeek = yy => { const j = D.num(yy, 1, 1); const ws = weekStart(j); return (ws + 7 - j >= 4) ? ws : ws + 7; };
    let f = firstWeek(y);
    if (x.n < f) f = firstWeek(y - 1); else if (x.n >= firstWeek(y + 1)) f = firstWeek(y + 1);
    return Math.floor((weekStart(x.n) - f) / 7) + 1;
  });
  def('Year', 'Year ( date )', 'Date', ([d]) => { const x = dateArg(d); return x ? D.parts(x.n)[0] : ''; });
  def('YearName', 'YearName ( date ; format )', 'Date', ([d]) => { const x = dateArg(d); return x ? String(D.parts(x.n)[0]) : ''; }, { hidden: true });
  def('Hour', 'Hour ( time )', 'Time', ([t]) => { const x = timeArg(t); return x ? Math.floor(x.s / 3600) : ''; });
  def('Minute', 'Minute ( time )', 'Time', ([t]) => { const x = timeArg(t); return x ? Math.floor(((x.s % 3600) + 3600) % 3600 / 60) : ''; });
  def('Seconds', 'Seconds ( time )', 'Time', ([t]) => { const x = timeArg(t); return x ? ((x.s % 60) + 60) % 60 : ''; });
  def('Time', 'Time ( hours ; minutes ; seconds )', 'Time', ([h, m, s]) => [h, m, s].some(V.empty) ? '' : new FMTime(N(h) * 3600 + N(m) * 60 + N(s)));
  def('Timestamp', 'Timestamp ( date ; time )', 'Timestamp', ([d, t]) => { const x = dateArg(d), y = V.empty(t) ? new FMTime(0) : V.time(t); return x && y ? new FMTimestamp((x.n - 1) * 86400 + y.s) : ''; });

  // ── aggregate ───────────────────────────────────────────────────────────
  const agg = f => (args, c) => f(c.spread(args));
  const nums = vals => vals.map(V.numOrNull).filter(x => x != null);
  const variance = (vals, pop) => { const a = nums(vals); if (a.length < (pop ? 1 : 2)) return pop && a.length ? 0 : ''; const m = a.reduce((s, x) => s + x, 0) / a.length; return a.reduce((s, x) => s + (x - m) * (x - m), 0) / (a.length - (pop ? 0 : 1)); };
  const typedExtreme = (vals, dir) => {
    const ne = vals.filter(v => !V.empty(v)); if (!ne.length) return '';
    return ne.reduce((best, v) => (V.compare(v, best) * dir > 0 ? v : best));
  };
  def('Average', 'Average ( field {; field...} )', 'Aggregate', agg(v => { const a = nums(v); return a.length ? a.reduce((s, x) => s + x, 0) / a.length : ''; }), { lazy: true, min: 1, max: null });
  def('Count', 'Count ( field {; field...} )', 'Aggregate', agg(v => v.filter(x => !V.empty(x)).length), { lazy: true, min: 1, max: null });
  def('List', 'List ( field {; field...} )', 'Aggregate', agg(v => v.filter(x => !V.empty(x)).map(T).join('\n')), { lazy: true, min: 1, max: null });
  def('Max', 'Max ( field {; field...} )', 'Aggregate', agg(v => typedExtreme(v, 1)), { lazy: true, min: 1, max: null });
  def('Min', 'Min ( field {; field...} )', 'Aggregate', agg(v => typedExtreme(v, -1)), { lazy: true, min: 1, max: null });
  def('StDev', 'StDev ( field {; field...} )', 'Aggregate', agg(v => { const x = variance(v, false); return x === '' ? '' : Math.sqrt(x); }), { lazy: true, min: 1, max: null });
  def('StDevP', 'StDevP ( field {; field...} )', 'Aggregate', agg(v => { const x = variance(v, true); return x === '' ? '' : Math.sqrt(x); }), { lazy: true, min: 1, max: null });
  def('Sum', 'Sum ( field {; field...} )', 'Aggregate', agg(v => nums(v).reduce((s, x) => s + x, 0)), { lazy: true, min: 1, max: null });
  def('Variance', 'Variance ( field {; field...} )', 'Aggregate', agg(v => variance(v, false)), { lazy: true, min: 1, max: null });
  def('VarianceP', 'VarianceP ( field {; field...} )', 'Aggregate', agg(v => variance(v, true)), { lazy: true, min: 1, max: null });

  // ── repeating ───────────────────────────────────────────────────────────
  def('Extend', 'Extend ( nonRepeatingField )', 'Repeating', (args, c) => c.ev(args[0]), { lazy: true });
  def('GetRepetition', 'GetRepetition ( repeatingField ; numberOfRepetition )', 'Repeating', (args, c) => {
    const n = Math.max(1, Math.floor(N(c.ev(args[1]))));
    if (args[0].k === 'field') return c.env.field(args[0].ref, n, false);
    if (args[0].k === 'var') return c.env.getVar(args[0].name, n);
    return n === 1 ? c.ev(args[0]) : '';
  }, { lazy: true });
  def('Last', 'Last ( field )', 'Repeating', (args, c) => {
    if (args[0].k === 'field') { const all = c.env.field(args[0].ref, null, true).filter(v => !V.empty(v)); return all.length ? all[all.length - 1] : ''; }
    return c.ev(args[0]);
  }, { lazy: true });

  // ── summary ─────────────────────────────────────────────────────────────
  def('GetSummary', 'GetSummary ( summaryField ; breakField )', 'Summary', (args, c) => {
    if (args[0].k !== 'field' || args[1].k !== 'field') throw new CalcError('GetSummary needs a summary field and a break field.', c.node.pos, 1218);
    return c.env.summary(args[0].ref, args[1].ref);
  }, { lazy: true });

  // ── logical ─────────────────────────────────────────────────────────────
  def('Case', 'Case ( test1 ; result1 {; test2 ; result2 ; ... ; defaultResult } )', 'Logical', (args, c) => {
    for (let i = 0; i + 1 < args.length; i += 2) if (V.bool(c.ev(args[i]))) return c.ev(args[i + 1]);
    return args.length % 2 ? c.ev(args[args.length - 1]) : '';
  }, { lazy: true, min: 2, max: null });
  def('Choose', 'Choose ( test ; result0 {; result1 ; result2 ... } )', 'Logical', (args, c) => {
    const i = Math.floor(N(c.ev(args[0])));
    return i >= 0 && i + 1 < args.length ? c.ev(args[i + 1]) : '';
  }, { lazy: true, min: 2, max: null });
  def('If', 'If ( test ; resultIfTrue {; resultIfFalse } )', 'Logical', (args, c) => V.bool(c.ev(args[0])) ? c.ev(args[1]) : (args[2] ? c.ev(args[2]) : ''), { lazy: true, min: 2, max: 3 });
  def('IsEmpty', 'IsEmpty ( field )', 'Logical', (args, c) => {
    const a = args[0];
    if (a.k === 'field' && !a.rep && c.env.isRelated(a.ref)) { const v = c.env.field(a.ref, null, false); return V.empty(v) ? 1 : 0; }
    return V.empty(c.ev(a)) ? 1 : 0;
  }, { lazy: true });
  def('IsValid', 'IsValid ( field )', 'Logical', (args, c) => { try { const v = c.ev(args[0]); return v === '?' ? 0 : 1; } catch (e) { return 0; } }, { lazy: true });
  def('IsValidExpression', 'IsValidExpression ( expression )', 'Logical', ([t], env) => { try { env.parse(T(t)); return 1; } catch (e) { return 0; } });
  def('EvaluationError', 'EvaluationError ( expression )', 'Logical', (args, c) => {
    try { if (args[0].k === 'call' && args[0].name === 'evaluate') { env_parse_eval(c, args[0]); return 0; } c.ev(args[0]); return 0; } catch (e) { return e instanceof CalcError ? e.code : 1200; }
  }, { lazy: true });
  function env_parse_eval(c, node) { const text = T(c.ev(node.args[0])); const ast = c.env.parse(text); return evaluate(ast, c.env); }
  def('Evaluate', 'Evaluate ( expression {; [ field1 ; field2 ; ... ] } )', 'Logical', (args, c) => {
    const text = T(c.ev(args[0]));
    let ast; try { ast = c.env.parse(text); } catch (e) { return '?'; }
    return evaluate(ast, c.env);
  }, { lazy: true, min: 1, max: 2 });
  def('ExecuteSQL', 'ExecuteSQL ( sqlQuery ; fieldSeparator ; rowSeparator {; arguments... } )', 'Logical', (args, env) => env.sql(T(args[0]), args[1] === '' ? ',' : T(args[1]), args[2] === '' ? '\n' : T(args[2]), args.slice(3)), { min: 3, max: null });
  def('GetField', 'GetField ( fieldName )', 'Logical', ([t], env, nd) => {
    const ref = env.fieldByName(T(t));
    if (!ref) throw new CalcError('GetField: the field "' + T(t) + '" cannot be found.', nd.pos, 102);
    return env.field(ref, null, false);
  });
  def('GetFieldName', 'GetFieldName ( field )', 'Logical', (args, c) => {
    if (args[0].k === 'field') return c.env.fieldName(args[0].ref);
    const v = T(c.ev(args[0])); const ref = c.env.fieldByName(v); return ref ? c.env.fieldName(ref) : '';
  }, { lazy: true });
  def('GetLayoutObjectAttribute', 'GetLayoutObjectAttribute ( objectName ; attributeName {; repetitionNumber ; portalRowNumber } )', 'Logical', ([n, a, r, p], env) => env.layoutObject(T(n), T(a).toLowerCase(), r, p));
  def('GetNthRecord', 'GetNthRecord ( fieldName ; recordNumber )', 'Logical', (args, c) => {
    if (args[0].k !== 'field') return '';
    return c.env.nth(args[0].ref, Math.floor(N(c.ev(args[1]))));
  }, { lazy: true });
  def('Lookup', 'Lookup ( sourceField {; failExpression } )', 'Logical', (args, c) => {
    const v = args[0].k === 'field' ? c.env.field(args[0].ref, null, false) : c.ev(args[0]);
    return V.empty(v) && args[1] ? c.ev(args[1]) : v;
  }, { lazy: true, min: 1, max: 2 });
  def('LookupNext', 'LookupNext ( sourceField ; lower/higher Flag )', 'Logical', (args, c) => {
    if (args[0].k !== 'field') return '';
    const dir = N(c.ev(args[1])) > 0 ? 1 : -1;
    return c.env.lookupNext(args[0].ref, dir);
  }, { lazy: true });
  def('Self', 'Self', 'Logical', (a, env) => env.self());
  def('Not', 'Not ( value )', 'Logical', ([v]) => V.bool(v) ? 0 : 1, { hidden: true });

  // ── JSON ────────────────────────────────────────────────────────────────
  const JTYPES = { 0: 'raw', 1: 'string', 2: 'number', 3: 'object', 4: 'array', 5: 'boolean', 6: 'null' };
  function jsonParse(t) {
    const s = T(t).trim();
    if (s === '') return { v: undefined };
    try { return { v: JSON.parse(s) }; } catch (e) { return { err: '? * ' + e.message }; }
  }
  function jsonPath(p) {
    if (typeof p === 'number') return [Math.floor(p)];
    const s = T(p); const outp = []; let i = 0, cur = '';
    while (i < s.length) {
      const ch = s[i];
      if (ch === '.') { if (cur) outp.push(cur); cur = ''; i++; continue; }
      if (ch === '[') {
        if (cur) outp.push(cur); cur = '';
        const end = s.indexOf(']', i);
        let inner = s.slice(i + 1, end < 0 ? s.length : end).trim();
        if (/^['"]/.test(inner)) outp.push(inner.slice(1, -1));
        else outp.push(inner === '+' ? '+' : parseInt(inner, 10));
        i = end < 0 ? s.length : end + 1; continue;
      }
      cur += ch; i++;
    }
    if (cur) outp.push(cur);
    return outp;
  }
  function jget(root, path) { let v = root; for (const k of path) { if (v == null || typeof v !== 'object') return undefined; v = v[k]; } return v; }
  function jsonOut(v) {
    if (v === undefined || v === null) return '';
    if (typeof v === 'boolean') return v ? 1 : 0;
    if (typeof v === 'number') return v;
    if (typeof v === 'string') return v;
    return JSON.stringify(v);
  }
  def('JSONGetElement', 'JSONGetElement ( json ; keyOrIndexOrPath )', 'JSON', ([j, p]) => { const r = jsonParse(j); if (r.err) return r.err; return jsonOut(jget(r.v, jsonPath(p))); });
  def('JSONGetElementType', 'JSONGetElementType ( json ; keyOrIndexOrPath )', 'JSON', ([j, p]) => {
    const r = jsonParse(j); if (r.err) return r.err;
    const v = jget(r.v, jsonPath(p));
    if (v === undefined) return ''; if (v === null) return 6; if (Array.isArray(v)) return 4;
    return { string: 1, number: 2, object: 3, boolean: 5 }[typeof v] || 0;
  });
  function jsonValue(value, type) {
    const t = JTYPES[Math.floor(N(type))] || 'raw';
    const s = T(value);
    switch (t) {
      case 'string': return s;
      case 'number': { const n = V.numOrNull(value); return n == null ? 0 : n; }
      case 'boolean': return V.bool(value) || s.toLowerCase() === 'true';
      case 'null': return null;
      case 'object': case 'array': case 'raw': default: {
        if (s.trim() === '') return t === 'array' ? [] : t === 'object' ? {} : '';
        try { return JSON.parse(s); } catch (e) { if (t === 'raw') { const n = V.numOrNull(s); return /^-?\d+(\.\d+)?$/.test(s.trim()) ? n : s; } throw new Error('? * ' + e.message); }
      }
    }
  }
  function jset(root, path, val) {
    if (!path.length) return val;
    if (root == null || typeof root !== 'object') root = typeof path[0] === 'number' || path[0] === '+' ? [] : {};
    let o = root;
    for (let i = 0; i < path.length; i++) {
      let k = path[i];
      if (k === '+' && Array.isArray(o)) k = o.length;
      if (i === path.length - 1) { o[k] = val; break; }
      if (o[k] == null || typeof o[k] !== 'object') o[k] = (typeof path[i + 1] === 'number' || path[i + 1] === '+') ? [] : {};
      o = o[k];
    }
    return root;
  }
  def('JSONSetElement', 'JSONSetElement ( json ; keyOrIndexOrPath ; value ; type )', 'JSON', (args) => {
    const r = jsonParse(args[0]); if (r.err) return r.err;
    let root = r.v;
    const triples = args.length === 4 && !args[1].list ? [[args[1], args[2], args[3]]] : args.slice(1).map(a => a.list || []);
    try {
      for (const [p, v, t] of triples) root = jset(root, jsonPath(p), jsonValue(v, t));
    } catch (e) { return e.message; }
    return JSON.stringify(root === undefined ? {} : root);
  }, { min: 2, max: null });
  def('JSONDeleteElement', 'JSONDeleteElement ( json ; keyOrIndexOrPath )', 'JSON', ([j, p]) => {
    const r = jsonParse(j); if (r.err) return r.err;
    const path = jsonPath(p); const parent = jget(r.v, path.slice(0, -1)); const k = path[path.length - 1];
    if (Array.isArray(parent) && typeof k === 'number') parent.splice(k, 1); else if (parent && typeof parent === 'object') delete parent[k];
    return JSON.stringify(r.v);
  });
  def('JSONFormatElements', 'JSONFormatElements ( json )', 'JSON', ([j]) => { const r = jsonParse(j); if (r.err) return r.err; return r.v === undefined ? '' : JSON.stringify(r.v, null, '\t'); });
  def('JSONListKeys', 'JSONListKeys ( json ; keyOrIndexOrPath )', 'JSON', ([j, p]) => {
    const r = jsonParse(j); if (r.err) return r.err;
    const v = jget(r.v, jsonPath(p)); if (!v || typeof v !== 'object') return '';
    return Object.keys(v).join('\n');
  });
  def('JSONListValues', 'JSONListValues ( json ; keyOrIndexOrPath )', 'JSON', ([j, p]) => {
    const r = jsonParse(j); if (r.err) return r.err;
    const v = jget(r.v, jsonPath(p)); if (!v || typeof v !== 'object') return '';
    return Object.values(v).map(x => T(jsonOut(x))).join('\n');
  });
  def('JSONMakeArray', 'JSONMakeArray ( listOfValues ; separator ; type )', 'JSON', ([l, s, t]) => {
    const sep = T(s) || '\n'; const items = T(l) === '' ? [] : T(l).split(sep === '¶' ? '\n' : sep);
    return JSON.stringify(items.map(x => jsonValue(x, t == null || t === '' ? 0 : t)));
  });
  ['JSONString', 'JSONNumber', 'JSONObject', 'JSONArray', 'JSONBoolean', 'JSONNull', 'JSONRaw'].forEach(n => CATALOG.push({ name: n, sig: n, cat: 'JSON' }));

  // ── design ──────────────────────────────────────────────────────────────
  const designFns = [
    ['DatabaseNames', 'DatabaseNames'], ['FieldBounds', 'FieldBounds ( fileName ; layoutName ; fieldName )'],
    ['FieldComment', 'FieldComment ( fileName ; fieldName )'], ['FieldIDs', 'FieldIDs ( fileName ; layoutName )'],
    ['FieldNames', 'FieldNames ( fileName ; layoutName )'], ['FieldRepetitions', 'FieldRepetitions ( fileName ; layoutName ; fieldName )'],
    ['FieldStyle', 'FieldStyle ( fileName ; layoutName ; fieldName )'], ['FieldType', 'FieldType ( fileName ; fieldName )'],
    ['GetNextSerialValue', 'GetNextSerialValue ( fileName ; fieldName )'], ['LayoutIDs', 'LayoutIDs ( fileName )'],
    ['LayoutNames', 'LayoutNames ( fileName )'], ['LayoutObjectNames', 'LayoutObjectNames ( fileName ; layoutName )'],
    ['RelationInfo', 'RelationInfo ( fileName ; tableOccurrenceName )'], ['ScriptIDs', 'ScriptIDs ( fileName )'],
    ['ScriptNames', 'ScriptNames ( fileName )'], ['TableIDs', 'TableIDs ( fileName )'], ['TableNames', 'TableNames ( fileName )'],
    ['BaseTableIDs', 'BaseTableIDs ( fileName )'], ['BaseTableNames', 'BaseTableNames ( fileName )'],
    ['ValueListIDs', 'ValueListIDs ( fileName )'], ['ValueListItems', 'ValueListItems ( fileName ; valueListName )'],
    ['ValueListNames', 'ValueListNames ( fileName )'], ['WindowNames', 'WindowNames {( fileName )}'], ['GetFieldNames', 'GetFieldNames ( fileName ; layoutName )']
  ];
  designFns.forEach(([n, sig]) => def(n, sig, 'Design', (args, env) => env.design(n.toLowerCase(), args.map(T)), { min: 0, max: null }));

  // ── Get ─────────────────────────────────────────────────────────────────
  const GET_LIST = ['AccountExtendedPrivileges', 'AccountGroupName', 'AccountName', 'AccountPrivilegeSetName', 'AccountType', 'ActiveFieldContents', 'ActiveFieldName', 'ActiveFieldTableName', 'ActiveLayoutObjectName', 'ActiveModifierKeys', 'ActivePortalRowNumber', 'ActiveRecordNumber', 'ActiveRepetitionNumber', 'ActiveSelectionSize', 'ActiveSelectionStart', 'AllowAbortState', 'AllowFormattingBarState', 'ApplicationArchitecture', 'ApplicationLanguage', 'ApplicationVersion', 'CalculationRepetitionNumber', 'ConnectionState', 'CurrentDate', 'CurrentExtendedPrivileges', 'CurrentHostTimestamp', 'CurrentPrivilegeSetName', 'CurrentTime', 'CurrentTimestamp', 'CurrentTimeUTCMicroseconds', 'CurrentTimeUTCMilliseconds', 'CustomMenuSetName', 'Device', 'DesktopPath', 'DocumentsPath', 'DocumentsPathListing', 'ErrorCaptureState', 'FileMakerPath', 'FileName', 'FilePath', 'FileSize', 'FoundCount', 'HighContrastState', 'HostApplicationVersion', 'HostIPAddress', 'HostName', 'InstalledFMPlugins', 'LastError', 'LastErrorDetail', 'LastErrorLocation', 'LastExternalErrorDetail', 'LastMessageChoice', 'LayoutAccess', 'LayoutCount', 'LayoutName', 'LayoutNumber', 'LayoutTableName', 'LayoutViewState', 'MenubarState', 'ModifiedFields', 'MultiUserState', 'NetworkProtocol', 'NetworkType', 'PageNumber', 'PersistentID', 'PreferencesPath', 'PrinterName', 'QuickFindText', 'RecordAccess', 'RecordID', 'RecordModificationCount', 'RecordNumber', 'RecordOpenCount', 'RecordOpenState', 'RequestCount', 'RequestOmitState', 'ScreenDepth', 'ScreenHeight', 'ScreenScaleFactor', 'ScreenWidth', 'ScriptAnimationState', 'ScriptName', 'ScriptParameter', 'ScriptResult', 'SessionIdentifier', 'SortState', 'StatusAreaState', 'SystemDrive', 'SystemIPAddress', 'SystemLanguage', 'SystemNICAddress', 'SystemPlatform', 'SystemVersion', 'TemporaryPath', 'TextRulerVisible', 'TotalRecordCount', 'TransactionOpenState', 'TriggerCurrentPanel', 'TriggerCurrentTabPanel', 'TriggerExternalEvent', 'TriggerGestureInfo', 'TriggerKeystroke', 'TriggerModifierKeys', 'TriggerTargetPanel', 'TriggerTargetTabPanel', 'UserCount', 'UserName', 'UseSystemFormatsState', 'UUID', 'UUIDNumber', 'WindowContentHeight', 'WindowContentWidth', 'WindowDesktopHeight', 'WindowDesktopWidth', 'WindowHeight', 'WindowLeft', 'WindowMode', 'WindowName', 'WindowOrientation', 'WindowStyle', 'WindowTop', 'WindowVisible', 'WindowWidth', 'WindowZoomLevel'];
  const GET_NAMES = new Set(GET_LIST.map(s => s.toLowerCase()));
  GET_LIST.forEach(n => CATALOG.push({ name: 'Get ( ' + n + ' )', sig: 'Get ( ' + n + ' )', cat: 'Get' }));

  // ── helpers ─────────────────────────────────────────────────────────────
  function serialIncrement(text, by) {
    const m = text.match(/(\d+)(?!.*\d)/);
    if (!m) return text + by;
    const digits = m[1];
    const s = String(Math.max(0, parseInt(digits, 10) + by)).padStart(digits.length, '0');
    return text.slice(0, m.index) + s + text.slice(m.index + digits.length);
  }
  FM.serialIncrement = serialIncrement;
  function conv(x, type) { return type === 2 ? V.num(x) : type === 3 ? (V.date(x) || x) : type === 4 ? (V.time(x) || x) : type === 5 ? (V.ts(x) || x) : x; }
  function sortValues(list, dt) {
    const t = dt == null || dt === '' ? 1 : Math.floor(N(dt));
    const type = Math.abs(t) || 1, dir = t < 0 ? -1 : 1;
    return ret(list.map(x => [x, conv(x, type)]).sort((a, b) => dir * (type === 1 ? V.cmpText(a[0], b[0]) : V.compare(a[1], b[1]))).map(x => x[0]));
  }
  function b64(bytes) { let s = ''; for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000)); return btoa(s); }

  // digests (synchronous, for CryptDigest)
  function sha256(bytes) {
    const K = new Uint32Array([0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2]);
    const H = new Uint32Array([0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19]);
    const m = pad64(bytes, false); const w = new Uint32Array(64);
    const rot = (x, n) => (x >>> n) | (x << (32 - n));
    for (let i = 0; i < m.length; i += 64) {
      for (let t = 0; t < 16; t++) w[t] = (m[i + t * 4] << 24) | (m[i + t * 4 + 1] << 16) | (m[i + t * 4 + 2] << 8) | m[i + t * 4 + 3];
      for (let t = 16; t < 64; t++) { const s0 = rot(w[t - 15], 7) ^ rot(w[t - 15], 18) ^ (w[t - 15] >>> 3); const s1 = rot(w[t - 2], 17) ^ rot(w[t - 2], 19) ^ (w[t - 2] >>> 10); w[t] = (w[t - 16] + s0 + w[t - 7] + s1) | 0; }
      let [a, b, c, d, e, f, g, hh] = H;
      for (let t = 0; t < 64; t++) {
        const t1 = (hh + (rot(e, 6) ^ rot(e, 11) ^ rot(e, 25)) + ((e & f) ^ (~e & g)) + K[t] + w[t]) | 0;
        const t2 = ((rot(a, 2) ^ rot(a, 13) ^ rot(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))) | 0;
        hh = g; g = f; f = e; e = (d + t1) | 0; d = c; c = b; b = a; a = (t1 + t2) | 0;
      }
      H[0] += a; H[1] += b; H[2] += c; H[3] += d; H[4] += e; H[5] += f; H[6] += g; H[7] += hh;
    }
    return words2bytes(H, false);
  }
  function sha1(bytes) {
    const H = new Uint32Array([0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0]);
    const m = pad64(bytes, false); const w = new Uint32Array(80);
    const rol = (x, n) => (x << n) | (x >>> (32 - n));
    for (let i = 0; i < m.length; i += 64) {
      for (let t = 0; t < 16; t++) w[t] = (m[i + t * 4] << 24) | (m[i + t * 4 + 1] << 16) | (m[i + t * 4 + 2] << 8) | m[i + t * 4 + 3];
      for (let t = 16; t < 80; t++) w[t] = rol(w[t - 3] ^ w[t - 8] ^ w[t - 14] ^ w[t - 16], 1);
      let [a, b, c, d, e] = H;
      for (let t = 0; t < 80; t++) {
        const f = t < 20 ? (b & c) | (~b & d) : t < 40 ? b ^ c ^ d : t < 60 ? (b & c) | (b & d) | (c & d) : b ^ c ^ d;
        const k = t < 20 ? 0x5A827999 : t < 40 ? 0x6ED9EBA1 : t < 60 ? 0x8F1BBCDC : 0xCA62C1D6;
        const tmp = (rol(a, 5) + f + e + k + w[t]) | 0; e = d; d = c; c = rol(b, 30); b = a; a = tmp;
      }
      H[0] += a; H[1] += b; H[2] += c; H[3] += d; H[4] += e;
    }
    return words2bytes(H, false);
  }
  function md5(bytes) {
    const S = [7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21];
    const K = new Uint32Array(64); for (let i = 0; i < 64; i++) K[i] = Math.floor(Math.abs(Math.sin(i + 1)) * 4294967296);
    const H = new Uint32Array([0x67452301, 0xefcdab89, 0x98badcfe, 0x10325476]);
    const m = pad64(bytes, true);
    for (let i = 0; i < m.length; i += 64) {
      const M = new Uint32Array(16); for (let t = 0; t < 16; t++) M[t] = m[i + t * 4] | (m[i + t * 4 + 1] << 8) | (m[i + t * 4 + 2] << 16) | (m[i + t * 4 + 3] << 24);
      let [a, b, c, d] = H;
      for (let t = 0; t < 64; t++) {
        let f, g;
        if (t < 16) { f = (b & c) | (~b & d); g = t; } else if (t < 32) { f = (d & b) | (~d & c); g = (5 * t + 1) % 16; } else if (t < 48) { f = b ^ c ^ d; g = (3 * t + 5) % 16; } else { f = c ^ (b | ~d); g = (7 * t) % 16; }
        const tmp = d; d = c; c = b;
        const x = (a + f + K[t] + M[g]) | 0; b = (b + ((x << S[t]) | (x >>> (32 - S[t])))) | 0; a = tmp;
      }
      H[0] += a; H[1] += b; H[2] += c; H[3] += d;
    }
    return words2bytes(H, true);
  }
  function pad64(bytes, little) {
    const len = bytes.length, total = Math.ceil((len + 9) / 64) * 64; const m = new Uint8Array(total);
    m.set(bytes); m[len] = 0x80;
    const bits = len * 8;
    for (let i = 0; i < 8; i++) { const byte = Math.floor(bits / Math.pow(2, 8 * i)) & 0xff; if (little) m[total - 8 + i] = byte; else m[total - 1 - i] = byte; }
    return m;
  }
  function words2bytes(H, little) { const o = new Uint8Array(H.length * 4); H.forEach((w, i) => { for (let j = 0; j < 4; j++) o[i * 4 + j] = little ? (w >>> (8 * j)) & 255 : (w >>> (24 - 8 * j)) & 255; }); return o; }

  FM.calc = {
    parse, evaluate, refs, usesGet, CalcError, LIB, CATALOG, GET_LIST,
    CATEGORIES: ['Text', 'Text Formatting', 'Number', 'Date', 'Time', 'Timestamp', 'Container', 'JSON', 'Aggregate', 'Summary', 'Repeating', 'Financial', 'Trigonometric', 'Logical', 'Get', 'Design'],
    jsonPath
  };
})();
