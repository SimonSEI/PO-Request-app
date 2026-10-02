"""
Pump report rebranding: turn a subcontractor's Word pump report into a
Stahlman-England report.

    rebrand_report(docx_bytes, vendor) -> (new_docx_bytes, info)

What it does, in order:
  1. Drops the sub's letterhead - everything above the report title (the first
     paragraph with "REPORT" in it), or the leading lines that carry the sub's
     name, licence, address, phone or email when there is no such title.
  2. Puts our letterhead (pumps_assets/report_letterhead.docx: logo, company
     name, rule, service lines) on top and the sub's report body under it,
     keeping its tables, highlights and photos.
  3. Deletes the technician: any table row labelled technician/signature/
     serviced by (a table left empty goes too), "Technician: ..." lines, and
     every other mention of those names.
  4. Replaces the sub's name with ours and strips their phone numbers, emails,
     licence number and address.
  5. Takes our name off the front of the customer ("Stahlman-Moritz HOA" ->
     "Moritz HOA").

Only .docx is rebranded. Used by pumps.py; no Flask in here.
"""
import copy
import io
import os
import re

from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml.ns import qn

HERE = os.path.dirname(os.path.abspath(__file__))
LETTERHEAD_PATH = os.path.join(HERE, 'pumps_assets', 'report_letterhead.docx')

OUR_NAME = os.environ.get('PUMPS_COMPANY_NAME', 'Stahlman-England Irrigation')
# Optional: our contact details, swapped in where the sub's were. Unset = the
# sub's details are simply removed.
OUR_PHONE = os.environ.get('PUMPS_COMPANY_PHONE', '')
OUR_EMAIL = os.environ.get('PUMPS_COMPANY_EMAIL', '')

# The sub we get pump reports from today. Extra subs can be added with
# PUMPS_VENDORS_JSON (see PUMPS_README.md); each needs names and identifiers.
DEFAULT_VENDORS = [{
    'key': 'wettech',
    'display': 'Wettech',
    # Longest first: the first match wins at each position.
    'names': ['Water Equipment Technologies of Southwest Florida LLC',
              'Water Equipment Technologies of Southwest Florida',
              'Water Equipment Technologies of SW Florida',
              'Water Equipment Technologies of SWFL',
              'Water Equipment Technologies',
              'Wettech', 'Wet Tech', 'Wetech', 'Wettec'],
    'emails': ['wettec.biz', 'wettec@verizon.net'],
    'phones': ['941-232-4629', '941-371-5151', '941.232.4629', '941.371.5151',
               '(941) 232-4629', '(941) 371-5151'],
    'other': ['CFC1429137', '#CFC1429137', '451 Interstate Court', '451 interstate Court',
              'State of Florida Certified Plumbing Contractor'],
    'sender_match': ['wettec', 'wetech', 'wettech', 'water equipment technologies'],
}]

# A whole cell that is a technician label: "Service Technician Signature",
# "Tech", "Technician Name:", "Serviced by". Customer signature rows stay.
TECH_LABEL = re.compile(r'^\s*(?:(?:service|field|pump|lead)\s+)?tech(?:nician)?(?:\'?s)?'
                        r'(?:\s+(?:signature|name|sign(?:ed)?))?\s*:?\s*$|'
                        r'^\s*signature\s*:?\s*$|'
                        r'^\s*(?:serviced|performed|completed|inspected|reported|work\s+done)\s+by\s*:?\s*$', re.I)
CUSTOMER_LABEL = re.compile(r'^\s*(customer|client|customer\s+name|community|property|site)\s*:?\s*$', re.I)
# "Stahlman-Moritz HOA", "Stahlman England - Moritz HOA", "SEI - Moritz HOA"
# (but never our own name on its own).
OUR_PREFIX = re.compile(r'^\s*(?:Stahlman(?:[\s\-–]*England)?|S\.?E\.?I\.?)\s*[-–:/]\s*(?!England\b)', re.I)
TITLE = re.compile(r'\bREPORT\b')

W_P, W_TBL, W_TR, W_TC, W_SECTPR = qn('w:p'), qn('w:tbl'), qn('w:tr'), qn('w:tc'), qn('w:sectPr')


def load_vendors():
    vendors = [dict(v) for v in DEFAULT_VENDORS]
    raw = os.environ.get('PUMPS_VENDORS_JSON', '').strip()
    if raw:
        import json
        try:
            extra = json.loads(raw)
            if isinstance(extra, list):
                vendors.extend(v for v in extra if isinstance(v, dict) and v.get('names'))
        except ValueError:
            print('⚠ PUMPS_VENDORS_JSON is not valid JSON - ignored')
    return vendors


def vendor_for(text):
    """The vendor profile whose name or email shows up in text, or None."""
    low = (text or '').lower()
    for v in load_vendors():
        keys = [n.lower() for n in v.get('names', [])] + [s.lower() for s in v.get('sender_match', [])] + \
               [e.lower() for e in v.get('emails', [])]
        if any(k and k in low for k in keys):
            return v
    return None


# ── text helpers ──────────────────────────────────────────────────────────────

def _el_text(el):
    return ''.join(t.text or '' for t in el.iter(qn('w:t')))


def _paragraphs_in(el):
    if el.tag == W_P:
        return [el]
    return list(el.iter(W_P))


def _replace_in_paragraph(p, pattern, repl):
    """Regex-replace across a paragraph's runs (Word splits text into runs at
    random places). The replacement takes the formatting of the run where the
    match starts. Returns the number of replacements."""
    ts = [t for t in p.iter(qn('w:t'))]
    if not ts:
        return 0
    full = ''.join(t.text or '' for t in ts)
    matches = list(pattern.finditer(full))
    if not matches:
        return 0
    # Map each character to (node index, offset).
    owners = []
    for i, t in enumerate(ts):
        owners.extend([i] * len(t.text or ''))
    texts = [list(t.text or '') for t in ts]
    starts = []
    pos = 0
    for t in ts:
        starts.append(pos)
        pos += len(t.text or '')
    for m in reversed(matches):
        a, b = m.start(), m.end()
        new = m.expand(repl) if isinstance(repl, str) else repl(m)
        if a == b:
            continue
        first = owners[a]
        last = owners[b - 1]
        if first == last:
            off = starts[first]
            texts[first][a - off:b - off] = list(new)
        else:
            off_f = starts[first]
            texts[first][a - off_f:] = list(new)
            for k in range(first + 1, last):
                texts[k] = []
            off_l = starts[last]
            texts[last][:b - off_l] = []
    for t, chars in zip(ts, texts):
        t.text = ''.join(chars)
        t.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
    return len(matches)


def _phrase_pattern(phrases):
    phrases = sorted({p for p in phrases if p}, key=len, reverse=True)
    if not phrases:
        return None
    parts = []
    for p in phrases:
        esc = re.escape(p).replace(r'\ ', r'\s+')
        # Word boundaries only where the phrase starts/ends with a word char.
        left = r'(?<![\w@.])' if p[0].isalnum() else ''
        right = r'(?![\w@])' if p[-1].isalnum() else ''
        parts.append(left + esc + right)
    return re.compile('|'.join(parts), re.I)


def _remove(el):
    parent = el.getparent()
    if parent is not None:
        parent.remove(el)


# ── header detection ─────────────────────────────────────────────────────────

def _looks_like_sub_header(el, vendor):
    text = _el_text(el).strip()
    if not text:
        # Empty spacer, or the sub's logo picture.
        return True
    low = text.lower()
    keys = [n.lower() for n in vendor.get('names', [])] + [e.lower() for e in vendor.get('emails', [])] + \
           [p.lower() for p in vendor.get('phones', [])] + [o.lower() for o in vendor.get('other', [])]
    if any(k in low for k in keys):
        return True
    if re.search(r'\b(phone|fax|email|license|licence|lic\.?\s*#|certified)\b', low):
        return True
    if re.search(r'\b\d{3}[-.)\s]\s*\d{3}[-.\s]\d{4}\b', low):
        return True
    return False


def _body_children(doc):
    return [el for el in doc.element.body if el.tag != W_SECTPR]


def _split_header(doc, vendor):
    """Index of the first body element to keep (the report title, else the
    first element after the sub's letterhead lines)."""
    kids = _body_children(doc)
    for i, el in enumerate(kids[:15]):
        if el.tag == W_P and TITLE.search(_el_text(el).upper()) and len(_el_text(el).strip()) < 80:
            return i, 'title'
    i = 0
    while i < len(kids) and i < 12 and kids[i].tag == W_P and _looks_like_sub_header(kids[i], vendor):
        i += 1
    return i, 'header-lines'


# ── copying across documents ─────────────────────────────────────────────────

def _copy_relationships(el, src_part, dst_part):
    """Re-point images and hyperlinks in a copied element at the new document."""
    r_ns = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    for node in el.iter():
        for attr in (f'{{{r_ns}}}embed', f'{{{r_ns}}}id', f'{{{r_ns}}}link'):
            rid = node.get(attr)
            if not rid or rid not in src_part.rels:
                continue
            rel = src_part.rels[rid]
            try:
                if rel.is_external:
                    node.set(attr, dst_part.relate_to(rel.target_ref, rel.reltype, is_external=True))
                elif rel.reltype == RT.IMAGE:
                    new_rid, _ = dst_part.get_or_add_image(io.BytesIO(rel.target_part.blob))
                    node.set(attr, new_rid)
                else:
                    node.attrib.pop(attr, None)
            except Exception:
                node.attrib.pop(attr, None)


def _copy_missing_styles(elements, src, dst):
    used = set()
    for el in elements:
        for tag in ('w:pStyle', 'w:rStyle', 'w:tblStyle'):
            for node in el.iter(qn(tag)):
                v = node.get(qn('w:val'))
                if v:
                    used.add(v)
    if not used:
        return
    dst_styles = dst.styles.element
    have = {s.get(qn('w:styleId')) for s in dst_styles.iter(qn('w:style'))}
    for s in src.styles.element.iter(qn('w:style')):
        sid = s.get(qn('w:styleId'))
        if sid in used and sid not in have:
            dst_styles.append(copy.deepcopy(s))
            have.add(sid)


# ── the clean-up passes ──────────────────────────────────────────────────────

def _remove_technicians(elements):
    """Remove technician/signature rows and lines; return the names removed."""
    names = set()
    for el in list(elements):
        for tbl in list(el.iter(W_TBL)):
            for tr in list(tbl.iter(W_TR)):
                cells = [_el_text(tc).strip() for tc in tr.iter(W_TC)]
                if any(TECH_LABEL.match(c) for c in cells if c):
                    for c in cells:
                        if c and not TECH_LABEL.match(c) and len(c) < 60:
                            names.add(c)
                    _remove(tr)
            if tbl.getparent() is not None and not list(tbl.iter(W_TR)):
                if tbl in elements:
                    elements.remove(tbl)
                _remove(tbl)
    for el in list(elements):
        for p in _paragraphs_in(el):
            text = _el_text(p).strip()
            m = re.match(r'^\s*(?:service\s+)?(?:tech(?:nician)?|serviced\s+by|performed\s+by|completed\s+by|'
                         r'inspected\s+by|signature)\s*[:#-]\s*(.*)$', text, re.I)
            if m:
                if m.group(1).strip():
                    names.add(m.group(1).strip())
                if p is el and el in elements:
                    elements.remove(el)
                _remove(p)
    return {n for n in names if re.search(r'[A-Za-z]', n)}


def _scrub_names(elements, names):
    count = 0
    if not names:
        return 0
    # Full names, and each part of a two-or-more-word name on its own
    # ("Justin Burnett", then "Burnett") - short tokens are left alone.
    full = _phrase_pattern(names)
    parts = {part for n in names if len(n.split()) > 1 for part in n.split()
             if len(part) >= 5 and part[0].isupper()}
    part_pat = re.compile('|'.join(r'\b' + re.escape(x) + r'\b' for x in sorted(parts, key=len, reverse=True))) \
        if parts else None
    def ours(m):
        # "Justin found the float stuck" -> "Our technician found the float stuck"
        before = m.string[:m.start()].rstrip()
        return 'Our technician' if not before or before[-1] in '.!?:' else 'our technician'
    for el in elements:
        for p in _paragraphs_in(el):
            count += _replace_in_paragraph(p, full, ours)
            if part_pat:
                count += _replace_in_paragraph(p, part_pat, ours)
    return count


def _fix_customer(elements):
    fixed = 0
    for el in elements:
        for tbl in list(el.iter(W_TBL)):
            for tr in tbl.iter(W_TR):
                tcs = list(tr.iter(W_TC))
                for i, tc in enumerate(tcs[:-1]):
                    if CUSTOMER_LABEL.match(_el_text(tc)):
                        for p in _paragraphs_in(tcs[i + 1]):
                            fixed += _replace_in_paragraph(p, OUR_PREFIX, '')
        for p in _paragraphs_in(el):
            m = re.match(r'^\s*(customer|client)\s*:\s*', _el_text(p), re.I)
            if m:
                fixed += _replace_in_paragraph(p, re.compile(r'(?<=:)\s*(?:Stahlman(?:[\s\-–]*England)?|SEI)\s*[-–/]\s*(?!England\b)', re.I), ' ')
    return fixed


def _replace_vendor(elements, vendor):
    count = 0
    names = _phrase_pattern(vendor.get('names', []))
    emails = re.compile(r'[\w.+-]*@?(?:' + '|'.join(re.escape(e) for e in vendor.get('emails', []) if e) + r')', re.I) \
        if vendor.get('emails') else None
    phones = _phrase_pattern(vendor.get('phones', []))
    other = _phrase_pattern(vendor.get('other', []))
    for el in elements:
        for p in _paragraphs_in(el):
            # Emails first: "wettec@verizon.net" must not become "<our name>@verizon.net".
            if emails:
                count += _replace_in_paragraph(p, emails, OUR_EMAIL)
            if phones:
                count += _replace_in_paragraph(p, phones, OUR_PHONE)
            if other:
                count += _replace_in_paragraph(p, other, '')
            if names:
                count += _replace_in_paragraph(p, names, OUR_NAME)
    return count


# ── reading a report ─────────────────────────────────────────────────────────

LABELS = {
    'date': re.compile(r'^\s*(date|service\s+date|date\s+of\s+service)\s*:?\s*$', re.I),
    'time': re.compile(r'^\s*time\s*:?\s*$', re.I),
    'customer': CUSTOMER_LABEL,
    'location': re.compile(r'^\s*(location|pump|pump\s+station|station|site\s+location|address)\s*:?\s*$', re.I),
}


def read_report(docx_bytes):
    """Pull the title, date, customer and location out of a report, plus a
    plain-text version of every line and table row (for a Jobber note)."""
    doc = Document(io.BytesIO(docx_bytes))
    out = {'title': '', 'date': '', 'time': '', 'customer': '', 'location': '', 'lines': []}
    for el in _body_children(doc):
        if el.tag == W_P:
            t = _el_text(el).strip()
            if t:
                out['lines'].append(t)
                if not out['title'] and TITLE.search(t.upper()) and len(t) < 80:
                    out['title'] = t
        elif el.tag == W_TBL:
            for tr in el.iter(W_TR):
                cells = [re.sub(r'\s+', ' ', _el_text(tc)).strip() for tc in tr.iter(W_TC)]
                for i, c in enumerate(cells[:-1]):
                    for key, pat in LABELS.items():
                        if not out[key] and pat.match(c) and cells[i + 1]:
                            out[key] = cells[i + 1]
                row = ' · '.join(c for c in cells if c)
                if row:
                    out['lines'].append(row)
    out['customer'] = OUR_PREFIX.sub('', out['customer']).strip()
    return out


# ── the main entry point ─────────────────────────────────────────────────────

def rebrand_report(docx_bytes, vendor=None, extra_tech_names=None, letterhead_path=LETTERHEAD_PATH):
    """Return (rebranded .docx bytes, info dict)."""
    src = Document(io.BytesIO(docx_bytes))
    all_text = '\n'.join(_el_text(el) for el in _body_children(src))
    vendor = vendor or vendor_for(all_text) or load_vendors()[0]

    start, how = _split_header(src, vendor)
    keep = _body_children(src)[start:]

    dst = Document(letterhead_path)
    body = dst.element.body
    sectpr = body.find(W_SECTPR)
    # Drop the letterhead's own title and the blank lines after it: the sub's
    # title (FOUNTAIN MAINTENANCE REPORT, PUMP REPORT...) takes its place.
    dst_kids = _body_children(dst)
    cut = next((i for i, el in enumerate(dst_kids) if TITLE.search(_el_text(el).upper())), len(dst_kids))
    for el in dst_kids[cut:]:
        if el.tag != qn('w:bookmarkEnd'):
            body.remove(el)
    if how != 'title':
        # No title of the sub's to carry over: keep ours.
        for el in dst_kids[cut:cut + 1]:
            body.insert(list(body).index(sectpr) if sectpr is not None else len(body), el)

    copied = [copy.deepcopy(el) for el in keep]
    _copy_missing_styles(copied, src, dst)
    for el in copied:
        _copy_relationships(el, src.part, dst.part)
        if sectpr is not None:
            sectpr.addprevious(el)
        else:
            body.append(el)

    techs = _remove_technicians(copied)
    techs |= {n for n in (extra_tech_names or []) if n}
    scrubbed = _scrub_names(copied, techs)
    customer_fixed = _fix_customer(copied)
    vendor_hits = _replace_vendor(copied, vendor)

    # Trim trailing blank paragraphs left behind by removed rows.
    while copied and copied[-1].tag == W_P and not _el_text(copied[-1]).strip() and \
            not list(copied[-1].iter(qn('w:drawing'))):
        _remove(copied.pop())

    # Anything of the sub's still left anywhere is reported, not hidden.
    final_text = '\n'.join(_el_text(el) for el in _body_children(dst))
    leftovers = [n for n in vendor.get('names', []) + vendor.get('phones', []) + vendor.get('emails', [])
                 if n and n.lower() in final_text.lower()]
    leftovers += [n for n in techs if n and n.lower() in final_text.lower()]

    buf = io.BytesIO()
    dst.save(buf)
    return buf.getvalue(), {
        'vendor': vendor.get('display') or vendor.get('key'),
        'header_removed_by': how,
        'header_elements_removed': start,
        'technicians_removed': sorted(techs),
        'technician_mentions_scrubbed': scrubbed,
        'customer_prefix_fixed': customer_fixed,
        'vendor_mentions_replaced': vendor_hits,
        'leftovers': leftovers,
    }


def docx_to_pdf(docx_bytes):
    """PDF bytes via LibreOffice when it is installed on the server, else None."""
    import shutil
    import subprocess
    import tempfile
    soffice = shutil.which('soffice') or shutil.which('libreoffice')
    if not soffice:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, 'report.docx')
        with open(src, 'wb') as f:
            f.write(docx_bytes)
        try:
            subprocess.run([soffice, '--headless', '--convert-to', 'pdf', '--outdir', tmp, src],
                           check=True, timeout=120, capture_output=True,
                           env=dict(os.environ, HOME=tmp))
            with open(os.path.join(tmp, 'report.pdf'), 'rb') as f:
                return f.read()
        except Exception as e:
            print(f'⚠ Report PDF conversion failed: {e}')
            return None
