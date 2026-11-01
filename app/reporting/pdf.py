from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.analysis.diligence.evaluator import PILLAR_KEYWORDS
from app.analysis.diligence.models import DiligencePillar
from app.domain.enums import CitationTag, Recommendation
from app.domain.models import Analysis, Candidate, Evidence
from app.reporting.memo import _build_evidence_map, _format_source_category, _resolve_evidence_entry

LOGGER = logging.getLogger("dealgraph.reporting.pdf")

# Palette Constants
COLOR_SLATE_DARK = HexColor("#0F172A")
COLOR_SLATE_MID = HexColor("#1E293B")
COLOR_SLATE_MUTED = HexColor("#64748B")
COLOR_SLATE_LIGHT = HexColor("#F8FAFC")
COLOR_SLATE_BORDER = HexColor("#E2E8F0")

COLOR_COBALT = HexColor("#2563EB")
COLOR_COBALT_LIGHT = HexColor("#EFF6FF")

COLOR_EMERALD = HexColor("#059669")
COLOR_EMERALD_LIGHT = HexColor("#ECFDF5")

COLOR_AMBER = HexColor("#D97706")
COLOR_AMBER_LIGHT = HexColor("#FFFBEB")

COLOR_ROSE = HexColor("#DC2626")
COLOR_ROSE_LIGHT = HexColor("#FEF2F2")

COLOR_WHITE = HexColor("#FFFFFF")


class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas for precise page numbering and running headers/footers."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict[str, Any]] = []

    def showPage(self) -> None:
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count: int) -> None:
        self.saveState()
        self.setFont("Helvetica-Bold", 8)
        self.setFillColor(COLOR_SLATE_MUTED)

        # Running header (pages 2+)
        if self._pageNumber > 1:
            self.drawString(36, 760, "DEALGRAPH // INVESTMENT COMMITTEE MEMO")
            self.drawRightString(612 - 36, 760, "STRICTLY CONFIDENTIAL")
            self.setStrokeColor(COLOR_SLATE_BORDER)
            self.setLineWidth(0.5)
            self.line(36, 752, 612 - 36, 752)

        # Running footer (all pages)
        self.setStrokeColor(COLOR_SLATE_BORDER)
        self.setLineWidth(0.5)
        self.line(36, 42, 612 - 36, 42)

        self.setFont("Helvetica", 8)
        self.drawString(36, 28, "DEALGRAPH // INVESTMENT COMMITTEE MEMO — STRICTLY CONFIDENTIAL")
        self.drawRightString(612 - 36, 28, f"Page {self._pageNumber} of {page_count}")
        self.restoreState()


def _clean_for_xml(text: str) -> str:
    """Escape text for ReportLab XML paragraph rendering."""
    if not text:
        return ""
    return html.escape(text)


def _transform_citations_for_pdf(text: str, evidence_map: dict[str, Any]) -> str:
    """Transform raw [ev-XXX] or composite citations into compact, clickable ReportLab HTML/XML links."""
    if not text:
        return ""

    replacements: dict[str, str] = {}
    counter = 0

    def make_token() -> str:
        nonlocal counter
        token = f"__CITETOKEN_{counter}__"
        counter += 1
        return token

    def replace_bracket_citations(match: re.Match) -> str:
        inner = match.group(1)
        ev_ids = re.findall(r"ev-\d+", inner, flags=re.IGNORECASE)
        if not ev_ids:
            return match.group(0)

        seen: set[str] = set()
        unique_ev_ids: list[str] = []
        for ev_id in ev_ids:
            norm = ev_id.lower()
            if norm not in seen:
                seen.add(norm)
                unique_ev_ids.append(ev_id)

        rendered: list[str] = []
        for ev_id in unique_ev_ids:
            resolved = _resolve_evidence_entry(ev_id, evidence_map)
            if resolved is not None:
                idx, ev = resolved
                url = html.escape(ev.source_url) if ev.source_url and ev.source_url.startswith(("http://", "https://")) else ""
                if url:
                    rendered.append(f'<a href="{url}" color="#2563EB"><b>[{idx}] &#8599;</b></a>')
                else:
                    rendered.append(f'<font color="#2563EB"><b>[{idx}] &#8599;</b></font>')
            else:
                rendered.append(f'<font color="#64748B"><b>[{ev_id.upper()}]</b></font>')
        token = make_token()
        replacements[token] = " ".join(rendered)
        return token

    def replace_single_citation(match: re.Match) -> str:
        ev_id = match.group(1)
        resolved = _resolve_evidence_entry(ev_id, evidence_map)
        if resolved is not None:
            idx, ev = resolved
            url = html.escape(ev.source_url) if ev.source_url and ev.source_url.startswith(("http://", "https://")) else ""
            if url:
                rendered = f'<a href="{url}" color="#2563EB"><b>[{idx}] &#8599;</b></a>'
            else:
                rendered = f'<font color="#2563EB"><b>[{idx}] &#8599;</b></font>'
        else:
            rendered = f'<font color="#64748B"><b>[{ev_id.upper()}]</b></font>'
        token = make_token()
        replacements[token] = rendered
        return token

    # Pass 1: Bracketed citations like [ev-001, ev-003, ev-005] or [ev-001]
    st = re.sub(r"\[\s*([^\]]*\bev-\d+[^\]]*)\s*\]", replace_bracket_citations, text, flags=re.IGNORECASE)
    # Pass 2: Parenthesized citations like (ev-001, ev-003) or (ev-001)
    st = re.sub(r"\(\s*([^)]*\bev-\d+[^)]*)\s*\)", replace_bracket_citations, st, flags=re.IGNORECASE)
    # Pass 3: Standalone unbracketed ev-XXX citations
    st = re.sub(r"(?<![\[\w-])(ev-\d+)(?![\]\w-])", replace_single_citation, st, flags=re.IGNORECASE)

    # HTML escape surrounding text
    escaped = html.escape(st)

    # Restore tokens
    for token, xml_chunk in replacements.items():
        escaped = escaped.replace(token, xml_chunk)

    return escaped


def render_pdf_memo(
    candidate: Candidate,
    analysis: Analysis,
    evidence: list[Evidence],
    output_path: Path | str,
) -> Path:
    """Generate a publication-grade PDF Investment Committee Memo using ReportLab Platypus."""
    out_file = Path(output_path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(out_file),
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=48,
        bottomMargin=48,
    )

    styles = getSampleStyleSheet()

    # Custom typography styles
    style_h1 = ParagraphStyle(
        "PDF_H1",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        textColor=COLOR_SLATE_DARK,
        spaceBefore=14,
        spaceAfter=6,
        keepWithNext=True,
    )

    style_h2 = ParagraphStyle(
        "PDF_H2",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=10.5,
        leading=14,
        textColor=COLOR_SLATE_MID,
        spaceBefore=8,
        spaceAfter=4,
        keepWithNext=True,
    )

    style_body = ParagraphStyle(
        "PDF_Body",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=COLOR_SLATE_MID,
        spaceBefore=3,
        spaceAfter=5,
    )

    style_bullet = ParagraphStyle(
        "PDF_Bullet",
        parent=style_body,
        leftIndent=12,
        firstLineIndent=-8,
        spaceBefore=2,
        spaceAfter=3,
    )

    style_card_title = ParagraphStyle(
        "PDF_CardTitle",
        fontName="Helvetica-Bold",
        fontSize=9.5,
        leading=12,
        textColor=COLOR_SLATE_DARK,
        spaceAfter=3,
    )

    style_card_body = ParagraphStyle(
        "PDF_CardBody",
        fontName="Helvetica",
        fontSize=8.5,
        leading=12,
        textColor=COLOR_SLATE_MID,
    )

    style_source_text = ParagraphStyle(
        "PDF_SourceText",
        fontName="Helvetica",
        fontSize=7.5,
        leading=10,
        textColor=COLOR_SLATE_MID,
    )

    # Build evidence map
    ev_map = _build_evidence_map(evidence)

    flowables: list[Any] = []

    # 1. Header Banner
    if analysis.recommendation == Recommendation.TAKE_A_MEETING:
        rec_bg = COLOR_EMERALD
        rec_label = "TAKE A MEETING"
    elif analysis.recommendation == Recommendation.WATCH:
        rec_bg = COLOR_AMBER
        rec_label = "WATCH"
    else:
        rec_bg = COLOR_ROSE
        rec_label = "PASS"

    title_para = Paragraph(
        f'<font color="#FFFFFF"><b>{_clean_for_xml(candidate.name)}</b></font><br/>'
        f'<font color="#94A3B8" size="8.5">INVESTMENT COMMITTEE MEMO · DEALGRAPH DILIGENCE ENGINE</font>',
        ParagraphStyle("BannerTitle", fontName="Helvetica-Bold", fontSize=16, leading=19),
    )

    score_label = f"Score: {analysis.score:.1f}/100"
    conf_label = f"Confidence: {analysis.confidence:.0%}"
    batch_val = candidate.batch.strip() if candidate.batch else ""
    stage_label = f"Batch: {batch_val}" if batch_val and batch_val.lower() != "general" else "Stage: Pre-Seed / Seed"

    badge_table_data = [
        [
            Paragraph(f'<font color="#FFFFFF"><b>{rec_label}</b></font>', ParagraphStyle("RecBadge", fontName="Helvetica-Bold", fontSize=8.5, alignment=1)),
            Paragraph(f'<font color="#38BDF8"><b>{score_label}</b></font>', ParagraphStyle("ScoreBadge", fontName="Helvetica-Bold", fontSize=8.5, alignment=1)),
            Paragraph(f'<font color="#A7F3D0"><b>{conf_label}</b></font>', ParagraphStyle("ConfBadge", fontName="Helvetica-Bold", fontSize=8.5, alignment=1)),
            Paragraph(f'<font color="#CBD5E1"><b>{stage_label}</b></font>', ParagraphStyle("StageBadge", fontName="Helvetica-Bold", fontSize=8.5, alignment=1)),
        ]
    ]
    badge_table = Table(badge_table_data, colWidths=[130, 115, 130, 165])
    badge_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (0, 0), rec_bg),
            ("BACKGROUND", (1, 0), (1, 0), COLOR_SLATE_MID),
            ("BACKGROUND", (2, 0), (2, 0), COLOR_SLATE_MID),
            ("BACKGROUND", (3, 0), (3, 0), COLOR_SLATE_MID),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ])
    )

    banner_data = [
        [title_para],
        [badge_table],
    ]
    banner_table = Table(banner_data, colWidths=[540])
    banner_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), COLOR_SLATE_DARK),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING", (0, 0), (-1, -1), 14),
            ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ])
    )
    flowables.append(banner_table)
    flowables.append(Spacer(1, 8))

    # 2. Metadata Grid
    website_display = _clean_for_xml(candidate.website) or "N/A"
    batch_display = _clean_for_xml(candidate.batch) or "General"
    sector_display = _clean_for_xml(candidate.industry) or "Technology"
    team_display = str(candidate.team_size) if candidate.team_size is not None else "Undisclosed"
    hiring_display = "Actively Hiring" if candidate.is_hiring else "Not Specified"
    today_str = datetime.now(timezone.utc).strftime("%B %d, %Y")

    if candidate.website and candidate.website.startswith(("http://", "https://")):
        web_url = html.escape(candidate.website)
        web_field = f'<a href="{web_url}" color="#2563EB"><u>{website_display}</u></a>'
    else:
        web_field = f'<font color="#2563EB">{website_display}</font>'

    meta_data = [
        [
            Paragraph('<b>Website:</b> ' + web_field, style_body),
            Paragraph("<b>Batch:</b> " + batch_display, style_body),
            Paragraph("<b>Sector:</b> " + sector_display, style_body),
        ],
        [
            Paragraph("<b>Team Size:</b> " + team_display, style_body),
            Paragraph("<b>Hiring:</b> " + hiring_display, style_body),
            Paragraph("<b>Evaluation Date:</b> " + today_str, style_body),
        ],
    ]
    meta_table = Table(meta_data, colWidths=[180, 180, 180])
    meta_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), COLOR_SLATE_LIGHT),
            ("BOX", (0, 0), (-1, -1), 0.5, COLOR_SLATE_BORDER),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, COLOR_SLATE_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ])
    )
    flowables.append(meta_table)
    flowables.append(Spacer(1, 8))

    # 3. 4-Pillar Diligence Scorecard
    flowables.append(Paragraph("4-Pillar Diligence Scorecard", style_h2))

    scorecard_data = [
        [
            Paragraph('<font color="#FFFFFF"><b>Diligence Pillar</b></font>', style_card_title),
            Paragraph('<font color="#FFFFFF"><b>Key Assessment & Signals</b></font>', style_card_title),
            Paragraph('<font color="#FFFFFF"><b>Evidence</b></font>', style_card_title),
        ],
        [
            Paragraph("<b>Commercial / TAM</b>", style_body),
            Paragraph(_transform_citations_for_pdf(analysis.market[:220] or candidate.one_liner, ev_map), style_body),
            Paragraph(f"{sum(1 for e in evidence if any(k in f'{e.claim} {e.excerpt}'.lower() for k in PILLAR_KEYWORDS[DiligencePillar.COMMERCIAL_TAM.value]))} item(s)", style_body),
        ],
        [
            Paragraph("<b>Unit Economics</b>", style_body),
            Paragraph(_transform_citations_for_pdf(analysis.financials.pricing or analysis.financials.revenue or "Pre-revenue business model", ev_map), style_body),
            Paragraph(f"{sum(1 for e in evidence if any(k in f'{e.claim} {e.excerpt}'.lower() for k in PILLAR_KEYWORDS[DiligencePillar.UNIT_ECONOMICS.value]))} item(s)", style_body),
        ],
        [
            Paragraph("<b>Tech / IP Defensibility</b>", style_body),
            Paragraph(_transform_citations_for_pdf(analysis.product[:220] or candidate.description, ev_map), style_body),
            Paragraph(f"{sum(1 for e in evidence if any(k in f'{e.claim} {e.excerpt}'.lower() for k in PILLAR_KEYWORDS[DiligencePillar.TECH_IP.value]))} item(s)", style_body),
        ],
        [
            Paragraph("<b>Risk / ESG</b>", style_body),
            Paragraph(_transform_citations_for_pdf(analysis.risks[0] if analysis.risks else "Manageable platform risk", ev_map), style_body),
            Paragraph(f"{sum(1 for e in evidence if any(k in f'{e.claim} {e.excerpt}'.lower() for k in PILLAR_KEYWORDS[DiligencePillar.RISK_ESG.value]))} item(s)", style_body),
        ],
    ]
    scorecard_table = Table(scorecard_data, colWidths=[130, 330, 80])
    scorecard_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), COLOR_SLATE_MID),
            ("BOX", (0, 0), (-1, -1), 0.5, COLOR_SLATE_BORDER),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, COLOR_SLATE_BORDER),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [COLOR_WHITE, COLOR_SLATE_LIGHT]),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ])
    )
    flowables.append(scorecard_table)
    flowables.append(Spacer(1, 8))

    # 4. Crown Jewel & Inverse Case Callout Cards
    crown_jewel_text = analysis.thesis if analysis.thesis else f"Defensible positioning in {candidate.industry or 'market'}."
    crown_card_data = [
        [
            Paragraph('<font color="#2563EB"><b>💎 CROWN JEWEL ASSET</b></font>', style_card_title),
        ],
        [
            Paragraph(_transform_citations_for_pdf(crown_jewel_text, ev_map), style_card_body),
        ],
    ]
    crown_table = Table(crown_card_data, colWidths=[540])
    crown_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), COLOR_COBALT_LIGHT),
            ("BOX", (0, 0), (-1, -1), 0.5, COLOR_COBALT),
            ("LINEBEFORE", (0, 0), (0, -1), 3.0, COLOR_COBALT),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ])
    )
    flowables.append(crown_table)
    flowables.append(Spacer(1, 6))

    inverse_text = analysis.risks[0] if analysis.risks else "Potential downside from market saturation and execution friction."
    inverse_card_data = [
        [
            Paragraph('<font color="#DC2626"><b>⚠️ THE INVERSE CASE (Failure Mode & Tripwires)</b></font>', style_card_title),
        ],
        [
            Paragraph(_transform_citations_for_pdf(inverse_text, ev_map), style_card_body),
        ],
    ]
    inverse_table = Table(inverse_card_data, colWidths=[540])
    inverse_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), COLOR_ROSE_LIGHT),
            ("BOX", (0, 0), (-1, -1), 0.5, COLOR_ROSE),
            ("LINEBEFORE", (0, 0), (0, -1), 3.0, COLOR_ROSE),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ])
    )
    flowables.append(inverse_table)
    flowables.append(Spacer(1, 8))

    # 5. Narrative Sections
    flowables.append(Paragraph("1. Executive Summary & Investment Thesis", style_h1))
    flowables.append(Paragraph(_transform_citations_for_pdf(analysis.summary, ev_map), style_body))
    flowables.append(Paragraph("Investment Thesis", style_h2))
    flowables.append(Paragraph(_transform_citations_for_pdf(analysis.thesis, ev_map), style_body))

    flowables.append(Paragraph("2. Team & Founder Capability", style_h1))
    flowables.append(Paragraph(_transform_citations_for_pdf(analysis.team, ev_map), style_body))

    flowables.append(Paragraph("3. Product Architecture & TRL", style_h1))
    flowables.append(Paragraph(_transform_citations_for_pdf(analysis.product, ev_map), style_body))

    flowables.append(Paragraph("4. Market Dynamics & Why Now", style_h1))
    flowables.append(Paragraph(_transform_citations_for_pdf(analysis.market, ev_map), style_body))
    flowables.append(Paragraph("Why Now Catalyst", style_h2))
    flowables.append(Paragraph(_transform_citations_for_pdf(analysis.why_now, ev_map), style_body))

    # 6. Financials
    flowables.append(Paragraph("5. Financials & Unit Economics", style_h1))
    financial_data = [
        [
            Paragraph("<b>Revenue / ARR:</b> " + _transform_citations_for_pdf(analysis.financials.revenue or "Undisclosed", ev_map), style_body),
            Paragraph("<b>Burn Rate:</b> " + _transform_citations_for_pdf(analysis.financials.burn or "Undisclosed", ev_map), style_body),
        ],
        [
            Paragraph("<b>Runway:</b> " + _transform_citations_for_pdf(analysis.financials.runway or "Undisclosed", ev_map), style_body),
            Paragraph("<b>Funding:</b> " + _transform_citations_for_pdf(analysis.financials.funding or "Undisclosed", ev_map), style_body),
        ],
        [
            Paragraph("<b>Pricing:</b> " + _transform_citations_for_pdf(analysis.financials.pricing or "Undisclosed", ev_map), style_body),
            Paragraph("", style_body),
        ],
    ]
    fin_table = Table(financial_data, colWidths=[270, 270])
    fin_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), COLOR_SLATE_LIGHT),
            ("BOX", (0, 0), (-1, -1), 0.5, COLOR_SLATE_BORDER),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, COLOR_SLATE_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ])
    )
    flowables.append(fin_table)

    # 7. Risks & Questions
    flowables.append(Paragraph("6. Critical Risks & Diligence Questions", style_h1))
    flowables.append(Paragraph("Key Risks & Tripwires", style_h2))
    for r in analysis.risks:
        flowables.append(Paragraph(f"• {_transform_citations_for_pdf(r, ev_map)}", style_bullet))

    if analysis.open_questions:
        flowables.append(Paragraph("Open Diligence Questions", style_h2))
        for q in analysis.open_questions:
            flowables.append(Paragraph(f"• {_transform_citations_for_pdf(q, ev_map)}", style_bullet))

    # 8. Triggers
    flowables.append(Paragraph('7. Triggers ("What Would Change Our Mind")', style_h1))
    for c in analysis.changes_mind:
        flowables.append(Paragraph(f"• {_transform_citations_for_pdf(c, ev_map)}", style_bullet))

    # 9. Auditable Sources Table
    flowables.append(Spacer(1, 10))
    flowables.append(Paragraph("8. Auditable Sources & References", style_h1))

    sources_data = [
        [
            Paragraph('<font color="#FFFFFF"><b>#</b></font>', style_source_text),
            Paragraph('<font color="#FFFFFF"><b>Trust Tag</b></font>', style_source_text),
            Paragraph('<font color="#FFFFFF"><b>Source & Publisher</b></font>', style_source_text),
            Paragraph('<font color="#FFFFFF"><b>Category</b></font>', style_source_text),
            Paragraph('<font color="#FFFFFF"><b>Key Excerpt</b></font>', style_source_text),
        ]
    ]

    for idx, item in enumerate(evidence, start=1):
        if item.status == CitationTag.VERIFIED:
            tag_color = "#059669"
            tag_label = "VERIFIED"
        elif item.status == CitationTag.TRUSTED:
            tag_color = "#2563EB"
            tag_label = "TRUSTED"
        else:
            tag_color = "#D97706"
            tag_label = "CLAIMED"

        num_para = Paragraph(f'<font color="#2563EB"><b>[{idx}]</b></font>', style_source_text)
        tag_para = Paragraph(f'<font color="{tag_color}"><b>{tag_label}</b></font>', style_source_text)

        raw_title = item.source_title.strip() or item.claim.strip() or f"Source {idx}"
        clean_title = re.sub(r"\s*[↗&#8599;]+\s*$", "", raw_title).strip()
        source_title_clean = _clean_for_xml(clean_title)
        if item.source_url and item.source_url.startswith(("http://", "https://")):
            url_clean = html.escape(item.source_url)
            link_para = Paragraph(f'<a href="{url_clean}" color="#2563EB"><b>{source_title_clean} &#8599;</b></a>', style_source_text)
        else:
            link_para = Paragraph(f"<b>{source_title_clean}</b>", style_source_text)

        category = _clean_for_xml(_format_source_category(item, candidate))
        category_para = Paragraph(f"<b>{category}</b>", style_source_text)

        snippet_clean = _clean_for_xml(re.sub(r"\s+", " ", item.excerpt).strip())
        if len(snippet_clean) > 200:
            snippet_clean = snippet_clean[:197].rsplit(" ", 1)[0] + "..."
        snippet_para = Paragraph(f'<i>"{snippet_clean}"</i>', style_source_text)

        sources_data.append([num_para, tag_para, link_para, category_para, snippet_para])

    sources_table = Table(sources_data, colWidths=[28, 56, 150, 96, 210])
    sources_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), COLOR_SLATE_MID),
            ("BOX", (0, 0), (-1, -1), 0.5, COLOR_SLATE_BORDER),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, COLOR_SLATE_BORDER),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [COLOR_WHITE, COLOR_SLATE_LIGHT]),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ])
    )
    flowables.append(sources_table)

    doc.build(flowables, canvasmaker=NumberedCanvas)
    LOGGER.info("rendered pdf memo candidate=%s path=%s", candidate.slug, out_file)
    return out_file
