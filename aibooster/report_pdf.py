"""Listing Audit as a downloadable PDF (reportlab, Helvetica)."""
import io
import unicodedata
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ORANGE = colors.HexColor('#EB5310')
INK = colors.HexColor('#1E252F')
MUTED = colors.HexColor('#64748b')
LINE = colors.HexColor('#e5e7eb')
SOFT = colors.HexColor('#FFF9F4')
MISSING = 'DATA_NOT_AVAILABLE'

_SWAPS = {'‘': "'", '’': "'", '“': '"', '”': '"', '–': '-', '—': '-',
          '…': '...', ' ': ' ', '•': '-'}


def _t(value):
    """Escape for reportlab and drop characters Helvetica can't draw."""
    text = '' if value is None else str(value)
    for a, b in _SWAPS.items():
        text = text.replace(a, b)
    text = unicodedata.normalize('NFKD', text).encode('latin-1', 'ignore').decode('latin-1')
    return escape(text).replace('\n', '<br/>')


def _band(score):
    """Hex colour for a 0-100 score."""
    return '#16a34a' if score >= 75 else '#d97706' if score >= 50 else '#dc2626'


def build(report, res):
    base = getSampleStyleSheet()['Normal']
    st = {
        'body': ParagraphStyle('b', parent=base, fontName='Helvetica', fontSize=9.5, leading=13.5, textColor=INK),
        'muted': ParagraphStyle('m', parent=base, fontName='Helvetica', fontSize=8.5, leading=12, textColor=MUTED),
        'h1': ParagraphStyle('h1', parent=base, fontName='Helvetica-Bold', fontSize=20, leading=24, textColor=INK),
        'h2': ParagraphStyle('h2', parent=base, fontName='Helvetica-Bold', fontSize=13, leading=17, textColor=INK,
                             spaceBefore=14, spaceAfter=6),
        'label': ParagraphStyle('l', parent=base, fontName='Helvetica-Bold', fontSize=8, leading=10, textColor=ORANGE),
        'score': ParagraphStyle('s', parent=base, fontName='Helvetica-Bold', fontSize=34, leading=38, alignment=1),
        'fname': ParagraphStyle('fn', parent=base, fontName='Helvetica-Bold', fontSize=10.5, leading=14, textColor=INK),
        'center': ParagraphStyle('c', parent=base, fontName='Helvetica', fontSize=8.5, leading=12, textColor=MUTED, alignment=1),
    }
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title='Listing Audit', author='Favhost')
    width = A4[0] - 36 * mm
    score = int(res.get('overall_score') or 0)
    out = [Paragraph('FAVHOST  ·  LISTING AUDIT', st['label']), Spacer(1, 3), Paragraph('Your listing report', st['h1'])]

    sub = report.created_at.strftime('%d %b %Y')
    if report.source_url:
        sub += '  ·  ' + report.source_url
    out += [Paragraph(_t(sub), st['muted']), Spacer(1, 10)]

    score_cell = [Paragraph(f'<font color="{_band(score)}">{score}</font>', st['score']),
                  Paragraph(f'out of 100  ·  <b>{_t(res.get("grade", ""))}</b>', st['center'])]
    issue_cell = [Paragraph('BIGGEST ISSUE', st['label']), Spacer(1, 3), Paragraph(_t(res.get('biggest_issue')), st['body'])]
    top = Table([[score_cell, issue_cell]], colWidths=[width * 0.24, width * 0.76])
    top.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), SOFT), ('BOX', (0, 0), (-1, -1), 0.6, LINE),
                             ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('LEFTPADDING', (0, 0), (-1, -1), 12),
                             ('RIGHTPADDING', (0, 0), (-1, -1), 12), ('TOPPADDING', (0, 0), (-1, -1), 12),
                             ('BOTTOMPADDING', (0, 0), (-1, -1), 12)]))
    out.append(top)

    rows = res.get('scorecard') or []
    weakest = sorted([r for r in rows if r['assessed']], key=lambda r: r['score'])[:3]
    if weakest:
        out.append(Paragraph('Fix these first', st['h2']))
        for i, r in enumerate(weakest, 1):
            out.append(KeepTogether([
                Paragraph(f'<b>{i}. {_t(r["category"])}</b>  <font color="{_band(r["score"])}">{r["score"]}/100</font>', st['body']),
                Paragraph(_t(r['fix']), st['muted']), Spacer(1, 5)]))

    if rows:
        out.append(Paragraph('Scorecard', st['h2']))
        data = [[Paragraph(h, st['label']) for h in ('CATEGORY', 'SCORE', 'WHAT WE FOUND', 'HOW TO FIX IT')]]
        for r in rows:
            score_txt = f'<font color="{_band(r["score"])}"><b>{r["score"]}</b></font>' if r['assessed'] else 'n/a'
            data.append([Paragraph(_t(r['category']), st['body']), Paragraph(score_txt, st['body']),
                         Paragraph(_t(r['issue']), st['muted']), Paragraph(_t(r['fix']), st['muted'])])
        table = Table(data, colWidths=[width * 0.17, width * 0.09, width * 0.37, width * 0.37], repeatRows=1)
        table.setStyle(TableStyle([('LINEBELOW', (0, 0), (-1, -1), 0.4, LINE), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                                   ('BACKGROUND', (0, 0), (-1, 0), SOFT), ('TOPPADDING', (0, 0), (-1, -1), 5),
                                   ('BOTTOMPADDING', (0, 0), (-1, -1), 5), ('LEFTPADDING', (0, 0), (-1, -1), 4)]))
        out.append(table)

    fields = [f for f in res.get('fields') or [] if f.get('suggested') and f['suggested'] != MISSING]
    if fields:
        out.append(Paragraph('Recommended rewrites', st['h2']))
        for f in fields:
            current = '' if f.get('current') == MISSING else (f.get('current') or '')
            block = [Paragraph(_t(f['field_name']), st['fname']), Spacer(1, 3)]
            if current:
                block += [Paragraph('CURRENT', st['label']), Paragraph(_t(current), st['muted']), Spacer(1, 4)]
            block += [Paragraph('RECOMMENDED', st['label']), Paragraph(_t(f['suggested']), st['body'])]
            limit = f.get('char_limit') or 0
            count = f.get('char_count') or len(f['suggested'])
            note = f'{count}' + (f' / {limit}' if limit else '') + ' characters'
            if f.get('reason'):
                note += '  ·  ' + f['reason']
            block += [Spacer(1, 2), Paragraph(_t(note), st['muted']), Spacer(1, 4),
                      HRFlowable(width='100%', thickness=0.4, color=LINE), Spacer(1, 6)]
            out.append(KeepTogether(block))

    if res.get('missing_data'):
        out.append(Paragraph('Not checked', st['h2']))
        out.append(Paragraph('We could not read these from the listing, so we left them out rather than guess: '
                             + _t('; '.join(res['missing_data'])) + '.', st['muted']))

    def footer(canvas, pdf_doc):
        canvas.saveState()
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, 9 * mm, 'Generated by Favhost Listing Audit')
        canvas.drawRightString(A4[0] - 18 * mm, 9 * mm, f'Page {pdf_doc.page}')
        canvas.restoreState()

    doc.build(out, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
