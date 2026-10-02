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

console.log(failures ? failures + ' failure(s), ' + passed + ' passed' : 'all ' + passed + ' engine checks pass');
process.exit(failures ? 1 : 0);
