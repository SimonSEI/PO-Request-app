/* Tests for the FileMaker engine that runs in the browser: the calculation
   language (filemaker_assets/fm-calc.js) and the data layer (fm-data.js:
   relationships, finds, sorts, summaries, validation, ExecuteSQL).

       node tests/filemaker_calc_test.js

   No browser needed: a few DOM globals are stubbed. */
'use strict';
const path = require('path');
const ASSETS = path.join(__dirname, '..', 'filemaker_assets');
global.window = global;
global.document = { querySelector() { return null; }, addEventListener() { }, cookie: '', readyState: 'complete', getElementById() { return null; } };
Object.defineProperty(global, 'navigator', { value: { platform: 'Linux', userAgent: 'node' }, configurable: true });
global.Node = function () { };
global.location = { host: 'test.local' };
global.screen = { width: 1, height: 1, colorDepth: 24 };
require(path.join(ASSETS, 'fm-core.js'));
require(path.join(ASSETS, 'fm-calc.js'));
require(path.join(ASSETS, 'fm-data.js'));
const FM = window.FM, V = FM.V, D = FM.dt;

let failures = 0, passed = 0;
function eq(got, want, label) {
  if (got === want) { passed++; return; }
  failures++;
  console.log('FAIL', label, '=>', JSON.stringify(got), 'want', JSON.stringify(want));
}

// ── calculations with a stand-in context ─────────────────────────────────
const fields = [{ name: 'First Name', ref: { fid: 'F1' } }, { name: 'Last', ref: { fid: 'F2' } }, { name: 'Amount', ref: { fid: 'F3' } }, { name: 'Due', ref: { fid: 'F4' } }];
const rel = [{ name: 'Total', ref: { fid: 'L1', rel: true } }];
const data = { F1: 'Ada', F2: 'Lovelace', F3: '12.5', F4: '2025-03-01' };
const types = { F1: 'text', F2: 'text', F3: 'number', F4: 'date' };
const scope = { toNames: () => ['Contacts', 'Line Items'], fields: to => to == null || to === 'Contacts' ? fields : to === 'Line Items' ? rel : null, customFunction: n => n.toLowerCase() === 'double' ? { name: 'Double', params: ['x'] } : null };
const vars = {};
const env = {
  field(ref, rep, all) { if (ref.rel) return all ? [10, 20, '', 5] : 10; const v = V.fromStored(data[ref.fid], types[ref.fid]); return all ? [v] : v; },
  isRelated: r => !!r.rel, repetitions: () => 1,
  getVar: n => vars[n] == null ? '' : vars[n], setVar: (n, v) => { vars[n] = v; },
  get: n => n === 'accountname' ? 'Admin' : '',
  customFunction: () => ({ params: ['x'], ast: FM.calc.parse('x*2', Object.assign({}, scope, { params: ['x'] })) }),
  parse: t => FM.calc.parse(t, scope), self: () => '',
  fieldByName: t => (fields.find(f => f.name.toLowerCase() === t.toLowerCase()) || {}).ref,
  fieldName: r => 'Contacts::' + fields.find(f => f.ref === r).name
};
const calc = f => { try { return V.text(FM.calc.evaluate(FM.calc.parse(f, scope), env)); } catch (e) { return 'ERR: ' + e.message; } };
[
  ['1 + 2 * 3', '7'], ['"a" & "b"', 'ab'], ['First Name & " " & Last', 'Ada Lovelace'], ['Contacts::First Name', 'Ada'],
  ['Amount * 2', '25'], ['1/2', '.5'], ['1/0', '?'], ['Round ( 2.345 ; 2 )', '2.35'], ['Round ( -2.5 ; 0 )', '-3'], ['Mod ( -15 ; 4 )', '1'], ['Div ( 7 ; 2 )', '3'],
  ['Let ( [ a = 2 ; b = a * 3 ] ; a + b )', '8'], ['Let ( $x = 5 ; $x * 2 )', '10'], ['$x', '5'],
  ['If ( Amount > 10 ; "big" ; "small" )', 'big'], ['Case ( 0 ; "a" ; 1 ; "b" ; "c" )', 'b'], ['Choose ( 2 ; "a" ; "b" ; "c" )', 'c'],
  ['Sum ( Line Items::Total )', '35'], ['Count ( Line Items::Total )', '3'], ['Average ( 1 ; 2 ; 3 )', '2'], ['List ( "a" ; "" ; "b" )', 'a\nb'], ['Max ( 3 ; 9 ; 4 )', '9'],
  ['Due + 30', '3/31/2025'], ['Month ( Due )', '3'], ['DayName ( Date ( 1 ; 1 ; 2025 ) )', 'Wednesday'], ['Date ( 13 ; 1 ; 2024 )', '1/1/2025'], ['Date ( 3 ; 0 ; 2025 )', '2/28/2025'],
  ['Date ( 3 ; 1 ; 2025 ) - Date ( 2 ; 1 ; 2025 )', '28'], ['WeekOfYear ( Date ( 1 ; 5 ; 2025 ) )', '2'], ['WeekOfYearFiscal ( Date ( 1 ; 1 ; 2021 ) ; 2 )', '53'],
  ['Substitute ( "a-b-c" ; "-" ; "+" )', 'a+b+c'], ['Substitute ( "abc" ; ["a";"x"] ; ["b";"y"] )', 'xyc'],
  ['PatternCount ( "banana" ; "an" )', '2'], ['Position ( "banana" ; "a" ; 1 ; 2 )', '4'], ['Position ( "banana" ; "a" ; 6 ; -1 )', '6'],
  ['GetValue ( "a¶b¶c" ; 2 )', 'b'], ['ValueCount ( "a¶b¶c¶" )', '3'], ['LeftValues ( "a¶b¶c" ; 2 )', 'a\nb\n'], ['FilterValues ( "a¶b¶c" ; "c¶a" )', 'a\nc\n'],
  ['LeftWords ( "The quick brown fox" ; 2 )', 'The quick'], ['MiddleWords ( "The quick brown fox" ; 2 ; 2 )', 'quick brown'], ['WordCount ( "one, two three" )', '3'],
  ['Proper ( "hello WORLD" )', 'Hello World'], ['Trim ( "  x  " )', 'x'], ['Upper ( "a" ) & Lower ( "B" )', 'Ab'],
  ['Left ( "abcdef" ; 3 ) & Right ( "abcdef" ; 2 ) & Middle ( "abcdef" ; 2 ; 2 )', 'abcefbc'], ['Replace ( "abcdef" ; 2 ; 3 ; "X" )', 'aXef'],
  ['"A" = "a"', '1'], ['"10" < "9"', '1'], ['10 < 9', '0'], ['IsEmpty ( "" ) and not IsEmpty ( "x" )', '1'], ['"" = 0', '0'],
  ['JSONGetElement ( "{\\"a\\":{\\"b\\":[1,2,3]}}" ; "a.b[1]" )', '2'], ['JSONSetElement ( "" ; "name" ; "Ada" ; JSONString )', '{"name":"Ada"}'],
  ['JSONSetElement ( "{}" ; ["a" ; 1 ; JSONNumber] ; ["b.c" ; "x" ; JSONString] )', '{"a":1,"b":{"c":"x"}}'], ['JSONListKeys ( "{\\"a\\":1,\\"b\\":2}" ; "" )', 'a\nb'],
  ['JSONDeleteElement ( "{\\"a\\":1,\\"b\\":2}" ; "a" )', '{"b":2}'], ['JSONGetElement ( "{bad" ; "a" )', '? * Expected property name or \'}\' in JSON at position 1 (line 1 column 2)'],
  ['While ( [ i = 0 ; out = "" ] ; i < 3 ; [ i = i + 1 ; out = out & i ] ; out )', '123'], ['Double ( 21 )', '42'],
  ['GetAsNumber ( "abc123.5x" )', '123.5'], ['Int ( -3.7 )', '-3'], ['Truncate ( 3.789 ; 1 )', '3.7'], ['Ceiling ( 1.2 )', '2'], ['Floor ( -1.2 )', '-2'],
  ['Time ( 13 ; 5 ; 0 )', '1:05:00 PM'], ['Hour ( Time ( 13 ; 5 ; 0 ) )', '13'], ['Timestamp ( Date ( 1 ; 2 ; 2025 ) ; Time ( 8 ; 0 ; 0 ) )', '1/2/2025 8:00:00 AM'],
  ['SerialIncrement ( "INV0099" ; 1 )', 'INV0100'], ['SerialIncrement ( "A-7-B" ; 1 )', 'A-8-B'], ['Code ( "Ab" )', '9800065'], ['Char ( 9800065 )', 'Ab'],
  ['Quote ( "say \\"hi\\"" )', '"say \\"hi\\""'], ['GetField ( "Last" )', 'Lovelace'], ['GetFieldName ( First Name )', 'Contacts::First Name'],
  ['Evaluate ( "1+1" )', '2'], ['SortValues ( "b¶a¶c" )', 'a\nb\nc\n'], ['SortValues ( "10¶9¶100" ; 2 )', '9\n10\n100\n'], ['UniqueValues ( "a¶A¶b" )', 'a\nb\n'],
  ['HexEncode ( CryptDigest ( "abc" ; "SHA256" ) )', 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'],
  ['HexEncode ( CryptDigest ( "abc" ; "MD5" ) )', '900150983cd24fb0d6963f7d28e17f72'], ['HexEncode ( CryptDigest ( "abc" ; "SHA1" ) )', 'a9993e364706816aba3e25717850c26c9cd0d89d'],
  ['Base64Encode ( "héllo" )', 'aMOpbGxv'], ['Base64Decode ( "aMOpbGxv" )', 'héllo'], ['Factorial ( 5 )', '120'], ['PMT ( 1000 ; .01 ; 12 ) > 88', '1'],
  ['/* comment */ 1 // trailing', '1'], ['Get ( AccountName )', 'Admin'], ['2^3^2', '64'], ['-2^2', '4'], ['"x" & ¶ & "y"', 'x\ny'],
  ['Exact ( "a" ; "A" )', '0'], ['Filter ( "(555) 123-4567" ; "0123456789" )', '5551234567'], ['GetAsText ( TextColor ( "red" ; RGB ( 255 ; 0 ; 0 ) ) )', 'red'],
  ['${Last}', 'Lovelace'], ['Contacts :: Last', 'Lovelace'], ['IsValidExpression ( "1 +" )', '0'], ['EvaluationError ( Evaluate ( "1 +" ) )', '1203']
].forEach(([f, want]) => eq(calc(f), want, f));
// regressions: rounding tiny/huge numbers, decimal Div/Mod, typed comparison with text, Position, Time + Date
[
  ['Round ( 0.1 + 0.2 - 0.3 ; 2 )', '0'], ['Round ( 0.0000001 ; 2 )', '0'], ['Round ( -0.0000001 ; 2 )', '0'], ['Truncate ( 0.0000001 ; 2 )', '0'],
  ['SetPrecision ( 0.0000001 ; 2 )', '0'], ['Round ( 10^21 ; 0 )', '1000000000000000000000'], ['Round ( 1.005 ; 2 )', '1.01'], ['Round ( 1234 ; -2 )', '1200'],
  ['If ( Round ( 100.1 - 100 - 0.1 ; 2 ) = 0 ; "balanced" ; "OUT" )', 'balanced'],
  ['Div ( 0.3 ; 0.1 )', '3'], ['Div ( 1.15 ; 0.05 )', '23'], ['Mod ( 0.3 ; 0.1 )', '0'], ['Mod ( 1.15 ; 0.05 )', '0'], ['Mod ( 10 ; 3.3 )', '.1'],
  ['Div ( -15 ; 4 )', '-4'], ['Mod ( 15 ; -4 )', '-1'], ['Div ( 7 ; 0 )', '?'], ['Mod ( 10^-20 ; 1 ) = 10^-20', '1'], ['Div ( 10^20 ; 0.5 )', '200000000000000000000'],
  ['Div ( 200 ; 200/3 )', '3'], ['Mod ( 200 ; 200/3 )', '0'], ['Div ( 1 ; 1/7 )', '7'], ['Div ( 7 ; 7/9 )', '9'], ['Mod ( 2 ; 2/3 )', '0'], ['Mod ( 123456789012.3456 ; 1 )', '.3456'],
  ['Round ( 10^300 ; 9 ) = 10^300', '1'], ['Truncate ( 10^300 ; 9 ) = 10^300', '1'], ['SetPrecision ( 10^300 ; 9 ) = 10^300', '1'], ['Round ( 1/3 ; 400 ) = 1/3', '1'],
  ['Due = "3/1/2025"', '1'], ['GetAsDate ( "3/1/2025" ) = "3/1/2025"', '1'], ['Due > "1/1/2026"', '0'], ['Due < "1/1/2026"', '1'], ['Due = 45000', '0'],
  ['Position ( "abc" ; "a" ; 3 ; -2 )', '0'], ['Position ( "aaa" ; "a" ; 3 ; -4 )', '0'], ['Position ( "aaa" ; "a" ; 3 ; -3 )', '1'],
  ['Time ( 1 ; 0 ; 0 ) + Date ( 1 ; 1 ; 2025 )', '1/1/2025 1:00:00 AM']
].forEach(([f, want]) => eq(calc(f), want, f));
['1 +', 'Foo ( 1 )', 'Nope', 'If ( 1 )', '"abc', '(1', 'Get ( Nonsense )', 'Left ( "a" ; 1 ; 2 )'].forEach(bad => {
  try { FM.calc.parse(bad, scope); eq('parsed', 'error', 'should not parse: ' + bad); } catch (e) { eq(e instanceof FM.calc.CalcError, true, 'error type for ' + bad); }
});

// ── the data layer: a two-table file ─────────────────────────────────────
const schema = {
  tables: [
    { id: 'TC', name: 'Customers', fields: [{ id: 'cid', name: 'CustomerID', type: 'number' }, { id: 'cname', name: 'Name', type: 'text' }, { id: 'ctot', name: 'Invoiced', type: 'calculation', options: { calc: { formula: 'Sum ( Invoices::Amount )', resultType: 'number', stored: false } } }] },
    { id: 'TI', name: 'Invoices', fields: [{ id: 'iid', name: 'InvoiceID', type: 'number' }, { id: 'icust', name: 'CustomerID', type: 'number' }, { id: 'iamt', name: 'Amount', type: 'number' }, { id: 'idate', name: 'Date', type: 'date' }, { id: 'istat', name: 'Status', type: 'text', options: { validation: { notEmpty: true, memberOf: 'VS' } } },
      { id: 'isum', name: 'Total Amount', type: 'summary', options: { summary: { op: 'total', field: 'iamt' } } }, { id: 'irun', name: 'Running', type: 'summary', options: { summary: { op: 'total', field: 'iamt', running: true } } },
      { id: 'icname', name: 'Customer', type: 'calculation', options: { calc: { formula: 'Customers::Name', resultType: 'text', stored: false } } }] }
  ],
  tableOccurrences: [{ id: 'OC', name: 'Customers', table: 'TC' }, { id: 'OI', name: 'Invoices', table: 'TI' }],
  relationships: [{ id: 'R1', left: 'OC', right: 'OI', predicates: [{ leftField: 'cid', op: '=', rightField: 'icust' }], leftOpts: {}, rightOpts: { sort: [{ fid: 'iamt', dir: 'desc' }] } }],
  layouts: [], scripts: [], valueLists: [{ id: 'VS', name: 'Status', type: 'custom', values: ['Draft', 'Paid'] }], customFunctions: [], privilegeSets: [{ id: 'PS_FULL', name: '[Full Access]', extended: ['fmapp'] }], fileOptions: {}
};
const recs = {
  TC: [[1, 'Acme'], [2, 'Globex'], [3, 'Initech']].map(([id, n], i) => ({ id: i + 1, t: 'TC', d: { cid: String(id), cname: n }, mc: 0 })),
  TI: [[101, 1, 50, '2025-01-05', 'Paid'], [102, 1, 75.5, '2025-02-10', 'Draft'], [103, 2, 20, '2025-02-11', 'Paid'], [104, 2, '', '2025-03-01', 'Draft'], [105, 9, 5, '2024-12-31', 'Paid']]
    .map(([id, c, a, d, s], i) => ({ id: 10 + i, t: 'TI', d: { iid: String(id), icust: String(c), iamt: String(a), idate: d, istat: s }, mc: 0 }))
};
const app = { userName: () => 'Tester', persistentId: () => 'X', openFiles: () => [], windows: [], recordsChanged() { }, schemaChanged() { } };
const file = new FM.FMFile(app, { file: { id: 1, name: 'T' }, token: 't', account: { name: 'Admin', privilegeSet: 'PS_FULL' }, schema, version: 1, serials: {}, records: recs, seq: 0 });
const cust = id => file.records('TC').find(r => r.d.cid === String(id));
const inv = id => file.records('TI').find(r => r.d.iid === String(id));
eq(file.related('OC', cust(1), 'OI').map(r => r.d.iid).join(','), '102,101', 'related records follow the relationship sort');
eq(V.text(file.keyValue('OC::ctot', cust(1), { to: 'OC' })), '125.5', 'calc summing a related field');
eq(V.text(file.keyValue('OI::icname', inv(103), { to: 'OI' })), 'Globex', 'related field from the child side');
eq(V.text(file.keyValue('OI::icname', inv(105), { to: 'OI' })), '', 'no related record gives empty');
const find = (crit, opts) => file.find('TI', 'OI', [{ omit: false, crit }].concat((opts && opts.omit) ? [{ omit: true, crit: opts.omit }] : []), null, null).map(r => r.d.iid).join(',');
eq(find({ 'OI::istat': 'paid' }), '101,103,105', 'find text, case-insensitive');
eq(find({ 'OI::iamt': '>20' }), '101,102', 'find greater than');
eq(find({ 'OI::iamt': '20...60' }), '101,103', 'find range');
eq(find({ 'OI::iamt': '=' }), '104', 'find empty');
eq(find({ 'OI::idate': '2/2025' }), '102,103', 'find a month');
eq(find({ 'OI::idate': '2025' }), '101,102,103,104', 'find a year');
eq(find({ 'OI::idate': '<1/1/2025' }), '105', 'find dates before');
eq(find({ 'OI::istat': 'Paid' }, { omit: { 'OI::iamt': '5' } }), '101,103', 'find then omit');
eq(find({ 'OI::icname': 'glo*' }), '103,104', 'find on a calculation with a wildcard');
eq(file.find('TC', 'OC', [{ omit: false, crit: { 'OI::istat': 'Draft' } }]).map(r => r.d.cname).join(','), 'Acme,Globex', 'find on a related field');
eq(find({ 'OI::istat': '!' }), '101,102,103,104,105', 'duplicates');
let threw = false; try { file.find('TI', 'OI', [{ omit: false, crit: {} }]); } catch (e) { threw = e.fmError === 400; } eq(threw, true, 'empty find request is error 400');
const sorted = file.sortRecs(file.records('TI').slice(), [{ key: 'OI::iamt', dir: 'desc' }], 'OI').map(r => r.d.iid).join(',');
eq(sorted, '102,101,103,105,104', 'sort descending puts empty last');
eq(file.sortRecs(file.records('TI').slice(), [{ key: 'OI::istat', dir: 'vl', vl: 'VS' }, { key: 'OI::iid', dir: 'asc' }], 'OI').map(r => r.d.iid).join(','), '102,104,101,103,105', 'sort by value list order');
eq(V.text(file.summarize(file.field('isum'), file.records('TI'))), '150.5', 'summary total');
const set = file.records('TI').slice(0, 3);
eq(V.text(file.summaryInContext(file.field('irun'), set[1], { summarySet: set })), '125.5', 'running total');
const fails = file.validate(file.table('TI'), inv(101), { istat: 'Void' }, new Set(['istat']), {});
eq(fails.map(f => f.code).join(','), '506', 'value list validation');
eq(file.validate(file.table('TI'), inv(101), { istat: '' }, new Set(['istat']), {}).map(f => f.code).join(','), '509', 'not empty validation');
eq(file.sql('SELECT Name FROM Customers WHERE CustomerID > ? ORDER BY Name DESC', ',', '\n', [1]), 'Initech\nGlobex', 'ExecuteSQL with a parameter');
eq(file.sql('SELECT c.Name, SUM(i.Amount) FROM Customers c JOIN Invoices i ON c.CustomerID = i.CustomerID GROUP BY c.Name ORDER BY 2 DESC', '|', ';', []), 'Acme|125.5;Globex|20', 'ExecuteSQL join and group');
eq(file.sql('SELECT COUNT(*) FROM Invoices WHERE Status = \'Paid\'', ',', '\n', []), '3', 'ExecuteSQL count');
eq(file.sql('SELECT Date FROM Invoices WHERE InvoiceID = 101', ',', '\n', []), '2025-01-05', 'ExecuteSQL dates as ISO');
eq(file.sql('SELECT nope FROM Invoices', ',', '\n', []), '?', 'ExecuteSQL error gives ?');
eq(file.sql('SELECT Name FROM Customers WHERE Name LIKE \'%e%\' FETCH FIRST 1 ROWS ONLY', ',', '\n', []), 'Acme', 'ExecuteSQL LIKE and FETCH');
eq(V.text(file.evaluate('ExecuteSQL ( "SELECT Name FROM Customers WHERE CustomerID = ?" ; "" ; "" ; 2 )', { to: 'OC', rec: cust(1) })), 'Globex', 'ExecuteSQL from a calculation');
eq(V.text(file.evaluate('Customers::Name & " has " & Count ( Invoices::InvoiceID ) & " invoices"', { to: 'OC', rec: cust(2) })), 'Globex has 2 invoices', 'context calculation');
eq(V.text(file.evaluate('GetSummary ( Invoices::Total Amount ; Invoices::Status )', { to: 'OI', rec: inv(101), summarySet: file.records('TI') })), '75', 'GetSummary by break field');
eq(V.text(file.evaluate('ValueListItems ( "T" ; "Status" )', { to: 'OI', rec: inv(101) })), 'Draft\nPaid', 'design function');
eq(V.text(file.evaluate('LookupNext ( Invoices::Amount ; Higher )', { to: 'OC', rec: cust(3) })), '5', 'LookupNext takes the next higher key (9)');
eq(V.text(file.evaluate('LookupNext ( Invoices::Amount ; Lower )', { to: 'OC', rec: cust(3) })), '20', 'LookupNext takes the next lower key (2)');
// ExecuteSQL regressions: ORDER BY ordinal or alias with GROUP BY, NULL in NOT/AND/OR, ROUND of tiny numbers
const join = 'FROM Customers c JOIN Invoices i ON c.CustomerID = i.CustomerID GROUP BY c.Name ';
eq(file.sql('SELECT c.Name, SUM(i.Amount) ' + join + 'ORDER BY 2 ASC', '|', ';', []), 'Globex|20;Acme|125.5', 'ExecuteSQL ORDER BY ordinal with GROUP BY');
eq(file.sql('SELECT c.Name, SUM(i.Amount) AS tot ' + join + 'ORDER BY tot', '|', ';', []), 'Globex|20;Acme|125.5', 'ExecuteSQL ORDER BY alias with GROUP BY');
eq(file.sql('SELECT InvoiceID FROM Invoices WHERE NOT (Amount > 30)', ',', ',', []), '103,105', 'ExecuteSQL NOT of NULL is not true');
eq(file.sql('SELECT InvoiceID FROM Invoices WHERE Amount > 30 OR Amount IS NULL', ',', ',', []), '101,102,104', 'ExecuteSQL OR with a NULL side');
eq(file.sql('SELECT InvoiceID FROM Invoices WHERE NOT (Amount > 30 AND Status = \'Paid\')', ',', ',', []), '102,103,104,105', 'ExecuteSQL FALSE AND NULL is false');
eq(file.sql('SELECT ROUND(0.0000001, 2), ROUND(2.345, 2), ROUND(-2.5, 0), ROUND(0.1, 400) FROM Customers FETCH FIRST 1 ROWS ONLY', ',', ';', []), '0,2.35,-3,0.1', 'ExecuteSQL ROUND');

// ── a second file for relationship keys, finds, repeating calcs, summaries and validation ──
const calcF = (id, name, formula, resultType, more) => Object.assign({ id, name, type: 'calculation', options: { calc: { formula, resultType } } }, more || {});
const schema2 = {
  tables: [
    { id: 'TP', name: 'People', fields: [{ id: 'pid', name: 'PersonID', type: 'number' }, { id: 'pname', name: 'Name', type: 'text' }, { id: 'pzip', name: 'Zip', type: 'text' },
      { id: 'pstat', name: 'Status', type: 'text' }, { id: 'pamt', name: 'Amount', type: 'number' }, { id: 'pprice', name: 'Price', type: 'number' },
      { id: 'ptot', name: 'Total', type: 'summary', options: { summary: { op: 'total', field: 'pamt' } } },
      { id: 'prun', name: 'Running', type: 'summary', options: { summary: { op: 'total', field: 'pamt', running: true, restart: 'pstat' } } },
      { id: 'pfrac', name: 'Fraction', type: 'summary', options: { summary: { op: 'fraction', field: 'pamt', subtotal: 'pstat' } } },
      calcF('pshare', 'Share', 'Amount / Total', 'number'),
      calcF('prep', 'RepCalc', 'Price * 2', 'number', { options: { calc: { formula: 'Price * 2', resultType: 'number', evalIfAllEmpty: false }, storage: { repetitions: 3 } } }),
      calcF('prepx', 'RepCalcExt', 'Extend ( Price ) * 2', 'number', { options: { calc: { formula: 'Extend ( Price ) * 2', resultType: 'number', evalIfAllEmpty: false }, storage: { repetitions: 3 } } }),
      calcF('prepd', 'RepCalcDefault', 'Price * 2', 'number', { options: { calc: { formula: 'Price * 2', resultType: 'number' }, storage: { repetitions: 3 } } }),
      calcF('preps', 'RepCalcSub', 'Price[1] * 2', 'number', { options: { calc: { formula: 'Price[1] * 2', resultType: 'number', evalIfAllEmpty: false }, storage: { repetitions: 3 } } }),
      calcF('prepg', 'RepCalcGet', 'GetRepetition ( Price ; 1 ) * 2', 'number', { options: { calc: { formula: 'GetRepetition ( Price ; 1 ) * 2', resultType: 'number', evalIfAllEmpty: false }, storage: { repetitions: 3 } } }),
      calcF('prepn', 'RepCalcNoFields', 'Get ( CalculationRepetitionNumber ) * 2', 'number', { options: { calc: { formula: 'Get ( CalculationRepetitionNumber ) * 2', resultType: 'number' }, storage: { repetitions: 3 } } }),
      { id: 'pdate', name: 'PayDate', type: 'date', options: { validation: { memberOf: 'VD' } } }, { id: 'ptime', name: 'PayTime', type: 'time', options: { validation: { memberOf: 'VT' } } },
      { id: 'pn', name: 'N', type: 'number', options: { validation: { unique: true } } }] },
    { id: 'TZ', name: 'Zips', fields: [{ id: 'zzip', name: 'Zip', type: 'text' }, { id: 'zcity', name: 'City', type: 'text' }] },
    { id: 'TO', name: 'Orders', fields: [{ id: 'oid', name: 'OrderID', type: 'number' }, { id: 'opid', name: 'PersonID', type: 'number' }] }
  ],
  tableOccurrences: [{ id: 'OP', name: 'People', table: 'TP' }, { id: 'OZ', name: 'Zips', table: 'TZ' }, { id: 'OO', name: 'Orders', table: 'TO' }],
  relationships: [{ id: 'RZ', left: 'OP', right: 'OZ', predicates: [{ leftField: 'pzip', op: '=', rightField: 'zzip' }], leftOpts: {}, rightOpts: {} },
    { id: 'RO', left: 'OP', right: 'OO', predicates: [{ leftField: 'pid', op: '=', rightField: 'opid' }], leftOpts: {}, rightOpts: {} }],
  layouts: [], scripts: [], valueLists: [{ id: 'VD', name: 'Dates', type: 'custom', values: ['1/5/2025', '2/10/2025'] }, { id: 'VT', name: 'Times', type: 'custom', values: ['1:05:00 PM'] }],
  customFunctions: [], privilegeSets: [{ id: 'PS_FULL', name: '[Full Access]', extended: ['fmapp'] }], fileOptions: {}
};
const people = [['Ann Lee', '01234', 'Paid', 10, 5, '1.50'], ['Joann Leeds', '007', 'paid', 30, null, '4111111111111111'],['Mary Ann Leeway', '', 'Paid', 60], ['Bob', 'K1A', 'Draft'], ['apple'], ['école'], ['Zebra'], ['Émile'], ['Joanne Leeds'], ['Carter']];
const recs2 = {
  TP: people.map(([n, z, s, a, pr, num], i) => ({ id: 100 + i, t: 'TP', d: { pid: String(i + 1), pname: n, pzip: z || '', pstat: s || '', pamt: a == null ? '' : String(a), pprice: pr == null ? '' : String(pr), pn: num || '' }, mc: 0 })),
  TZ: [['1234', 'Springfield'], ['01234', 'Boston'], ['7', 'Seven'], ['007', 'Bond'], ['k1a', 'Ottawa'], ['63101', 'St. Louis'], ['10001', 'Acme, Inc.']].map(([z, c], i) => ({ id: 200 + i, t: 'TZ', d: { zzip: z, zcity: c }, mc: 0 })),
  TO: ['1.0', '1', '01', '2'].map((p, i) => ({ id: 300 + i, t: 'TO', d: { oid: String(i + 1), opid: p }, mc: 0 }))
};
const file2 = new FM.FMFile(app, { file: { id: 2, name: 'T2' }, token: 't', account: { name: 'Admin', privilegeSet: 'PS_FULL' }, schema: schema2, version: 1, serials: {}, records: recs2, seq: 0 });
const person = n => file2.records('TP').find(r => r.d.pname === n);
const cities = n => file2.related('OP', person(n), 'OZ').map(r => r.d.zcity).join(',');
eq(cities('Ann Lee'), 'Boston', 'text key "01234" does not match "1234"');
eq(cities('Joann Leeds'), 'Bond', 'text key "007" does not match "7"');
eq(cities('Bob'), 'Ottawa', 'text keys match ignoring case');
eq(file2.related('OP', person('Ann Lee'), 'OO').length, 3, 'number keys match by value (1 = 1.0 = 01)');
const find2 = crit => file2.find('TP', 'OP', [{ omit: false, crit: { 'OP::pname': crit } }]).map(r => r.d.pname).join(',');
eq(find2('=Ann Lee'), 'Ann Lee', 'find = with several words matches whole words');
eq(find2('=Jo* Leeds'), 'Joann Leeds,Joanne Leeds', 'find = with several words keeps wildcards');
const findZ = crit => file2.find('TZ', 'OZ', [{ omit: false, crit: { 'OZ::zcity': crit } }]).map(r => r.d.zcity).join('|');
eq(findZ('=Acme, Inc.'), 'Acme, Inc.', 'find = with several words ignores punctuation between words');
eq(findZ('=St. Louis'), 'St. Louis', 'find = with a word ending in a full stop');
eq(find2('"oann"'), '', 'quoted find starts at a word start');
eq(find2('"joann"'), 'Joann Leeds,Joanne Leeds', 'quoted find matches a word start');
eq(find2('*"oann"'), 'Joann Leeds,Joanne Leeds', '*"" find matches anywhere');
eq(find2('a...c'), 'Ann Lee,Bob,apple,Carter', 'text range find');
eq(find2('<f'), 'Ann Lee,Bob,apple,école,Émile,Carter', 'text < find uses the sort order');
const paid = file2.sortRecs(file2.records('TP').filter(r => /paid/i.test(r.d.pstat)), [{ key: 'OP::pstat', dir: 'asc' }], 'OP');
const share = set => V.text(file2.value(person('Ann Lee'), file2.field('pshare'), 1, { summarySet: set }));
eq(share(paid), '.1', 'calculation over a summary field');
eq(share(paid.slice(0, 2)), '.25', 'calculation over a summary field follows the found set');
eq(V.text(file2.evaluate('GetSummary ( People::Total ; People::Status )', { to: 'OP', rec: person('Ann Lee'), summarySet: paid })), '100', 'GetSummary break ignores case like the sort');
eq(V.text(file2.summaryInContext(file2.field('pfrac'), person('Ann Lee'), { summarySet: paid })), '.1', 'fraction of subtotal ignores case like the sort');
eq(V.text(file2.summaryInContext(file2.field('prun'), paid[2], { summarySet: paid })), '100', 'running total restart ignores case like the sort');
const reps = fid => [1, 2, 3].map(i => V.text(file2.value(person('Ann Lee'), file2.field(fid), i, {}))).join(',');
eq(reps('prep'), '10,,', 'repeating calculation sees a non-repeating field in repetition 1 only');
eq(reps('prepx'), '10,10,10', 'Extend gives every repetition the field');
eq(reps('prepd'), '10,,', 'repeating calculation of non-repeating fields is blank past repetition 1 by default');
eq(reps('preps'), '10,10,10', 'a subscript Field[1] is read from repetition 1 when checking for empty fields');
eq(reps('prepg'), '10,10,10', 'GetRepetition ( Field ; 1 ) is read from repetition 1 when checking for empty fields');
eq(reps('prepn'), '2,4,6', 'a repeating calculation without fields calculates every repetition');
eq(V.text(file2.evaluate('Sum ( People::RepCalcExt ) & "/" & Count ( People::RepCalcExt ) & "/" & Count ( People::RepCalc )', { to: 'OP', rec: person('Ann Lee') })), '30/3/1', 'aggregates over a repeating calculation');
const v2 = (who, data) => file2.validate(file2.table('TP'), person(who), data, new Set(Object.keys(data)), {}).map(f => f.code).join(',');
eq(v2('Bob', { pdate: '2025-01-05' }), '', 'date in a value list');
eq(v2('Bob', { pdate: '2025-01-06' }), '506', 'date not in a value list');
eq(v2('Bob', { ptime: '13:05:00' }), '', 'time in a value list');
eq(v2('Bob', { pn: '1.5' }), '504', 'unique number compares by value');
eq(v2('Bob', { pn: '2' }), '', 'unique number');
eq(v2('Bob', { pn: '4111111111111112' }), '', 'unique 16-digit number compares every digit');
eq(v2('Bob', { pn: '4111111111111111' }), '504', 'unique 16-digit number');

// JSON keys are data: "__proto__" and "constructor" are ordinary keys and never reach Object.prototype
eq(calc('JSONSetElement ( "{}" ; "__proto__.html" ; "<img src=x>" ; JSONString )'), '{"__proto__":{"html":"<img src=x>"}}', 'JSONSetElement __proto__ path is an own key');
eq(({}).html, undefined, 'JSONSetElement does not pollute Object.prototype');
eq(calc('JSONSetElement ( "{}" ; "[\\"__proto__\\"].yy" ; 1 ; JSONNumber )'), '{"__proto__":{"yy":1}}', 'bracket __proto__ path');
eq(({}).yy, undefined, 'bracket path does not pollute Object.prototype');
eq(calc('JSONSetElement ( "{}" ; "constructor.prototype.zz" ; 1 ; JSONNumber )'), '{"constructor":{"prototype":{"zz":1}}}', 'constructor.prototype path is data');
eq(({}).zz, undefined, 'constructor path does not pollute Object.prototype');
eq(calc('JSONDeleteElement ( "{}" ; "__proto__.hasOwnProperty" )'), '{}', 'JSONDeleteElement of an inherited key does nothing');
eq(typeof Object.prototype.hasOwnProperty, 'function', 'JSONDeleteElement leaves Object.prototype alone');
eq(calc('JSONGetElement ( "{}" ; "constructor" )'), '', 'JSONGetElement does not read inherited keys');
eq(calc('JSONGetElement ( "{\\"__proto__\\":{\\"a\\":5}}" ; "__proto__.a" )'), '5', 'an own __proto__ key in JSON data is read');

console.log(failures ? failures + ' failure(s), ' + passed + ' passed' : 'all ' + passed + ' engine checks pass');
process.exit(failures ? 1 : 0);
