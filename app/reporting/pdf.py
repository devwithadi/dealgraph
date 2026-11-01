from __future__ import annotations

import html
import logging
import re
from pathlib import Path
from typing import Any

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    KeepInFrame,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

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


def _cap_text(text: str | None, limit: int = 300) -> str:
    """Fit prose while preferring a complete, still-cited sentence."""
    clean = re.sub(r"\s+", " ", text or "").strip() or "Not disclosed"
    if len(clean) <= limit:
        return clean
    prefix = clean[:limit]
    sentence_end = max(prefix.rfind(". "), prefix.rfind("? "), prefix.rfind("! "))
    if sentence_end >= limit // 2:
        complete = prefix[: sentence_end + 1]
        citation = re.search(r"\[ev-\d+\]", clean, re.IGNORECASE)
        if citation and not re.search(r"\[ev-\d+\]", complete, re.IGNORECASE):
            complete = f"{complete} {citation.group(0)}"
        return complete
    return prefix[: limit - 3].rsplit(" ", 1)[0] + "..."


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
                    rendered.append(f'<a href="{url}" color="#2563EB"><b>[{idx}]</b></a>')
                else:
                    rendered.append(f'<font color="#2563EB"><b>[{idx}]</b></font>')
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
                rendered = f'<a href="{url}" color="#2563EB"><b>[{idx}]</b></a>'
            else:
                rendered = f'<font color="#2563EB"><b>[{idx}]</b></font>'
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
    """Render a compact, evidence-linked memo with a structural one-page limit."""
    out_file = Path(output_path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(out_file), pagesize=letter, leftMargin=36, rightMargin=36,
        topMargin=48, bottomMargin=48,
    )
    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "OnePageBody", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=7.7, leading=9.6, textColor=COLOR_SLATE_MID,
    )
    small = ParagraphStyle(
        "OnePageSmall", parent=body, fontSize=6.8, leading=8.2,
    )
    label = ParagraphStyle(
        "OnePageLabel", parent=body, fontName="Helvetica-Bold",
        fontSize=7.2, leading=8.5, textColor=COLOR_SLATE_DARK,
    )
    evidence_map = _build_evidence_map(evidence)

    def linked(text: str | None, limit: int = 300) -> Paragraph:
        return Paragraph(_transform_citations_for_pdf(_cap_text(text, limit), evidence_map), body)

    if analysis.recommendation == Recommendation.TAKE_A_MEETING:
        call_color, call_text = COLOR_EMERALD, "TAKE A MEETING"
    elif analysis.recommendation == Recommendation.WATCH:
        call_color, call_text = COLOR_AMBER, "WATCH"
    else:
        call_color, call_text = COLOR_ROSE, "PASS"

    title = Paragraph(
        f'<font color="#FFFFFF"><b>{_clean_for_xml(candidate.name)}</b></font><br/>'
        '<font color="#CBD5E1" size="7">DEALGRAPH / SEED INVESTMENT MEMO</font>',
        ParagraphStyle("OnePageTitle", fontName="Helvetica-Bold", fontSize=15, leading=17),
    )
    call = Paragraph(
        f'<font color="#FFFFFF"><b>{call_text}</b></font><br/>'
        f'<font color="#E0F2FE">{analysis.score:.1f}/100</font> &nbsp; '
        f'<font color="#D1FAE5">{analysis.confidence:.0%} confidence</font>',
        ParagraphStyle("OnePageCall", fontName="Helvetica-Bold", fontSize=8.2, leading=13, alignment=2),
    )
    banner = Table([[title, call]], colWidths=[330, 210])
    banner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), COLOR_SLATE_DARK),
        ("BACKGROUND", (1, 0), (1, 0), call_color),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))

    website = _clean_for_xml(candidate.website) or "N/A"
    if candidate.website.startswith(("http://", "https://")):
        website = f'<a href="{html.escape(candidate.website)}" color="#2563EB">{website}</a>'
    metadata = Table([[
        Paragraph(f"<b>Website</b><br/>{website}", small),
        Paragraph(f"<b>Stage / batch</b><br/>{_clean_for_xml(candidate.batch) or 'Pre-Seed / Seed'}", small),
        Paragraph(f"<b>Sector</b><br/>{_clean_for_xml(candidate.industry) or 'Technology'}", small),
        Paragraph(f"<b>Team</b><br/>{candidate.team_size if candidate.team_size is not None else 'Undisclosed'}", small),
    ]], colWidths=[185, 115, 160, 80])
    metadata.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), COLOR_SLATE_LIGHT),
        ("BOX", (0, 0), (-1, -1), .5, COLOR_SLATE_BORDER),
        ("INNERGRID", (0, 0), (-1, -1), .5, COLOR_SLATE_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))

    thesis = Table([
        [Paragraph('<font color="#2563EB"><b>INVESTMENT THESIS</b></font>', label)],
        [linked(analysis.thesis or analysis.summary, 420)],
    ], colWidths=[540])
    thesis.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), COLOR_COBALT_LIGHT),
        ("BOX", (0, 0), (-1, -1), .6, COLOR_COBALT),
        ("LINEBEFORE", (0, 0), (0, -1), 3, COLOR_COBALT),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))

    snapshot = Table([
        [Paragraph("TEAM", label), Paragraph("PRODUCT", label)],
        [linked(analysis.team, 320), linked(analysis.product, 320)],
        [Paragraph("MARKET", label), Paragraph("WHY NOW", label)],
        [linked(analysis.market, 320), linked(analysis.why_now, 320)],
    ], colWidths=[270, 270])
    snapshot.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_SLATE_LIGHT),
        ("BACKGROUND", (0, 2), (-1, 2), COLOR_SLATE_LIGHT),
        ("BOX", (0, 0), (-1, -1), .5, COLOR_SLATE_BORDER),
        ("INNERGRID", (0, 0), (-1, -1), .5, COLOR_SLATE_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))

    dimension_cells: list[Paragraph] = []
    for item in analysis.dimensions[:5]:
        name = str(item.get("name", "dimension")).replace("_", " ").title()
        raw_score = item.get("score", "N/A")
        score_text = f"{raw_score:g}/10" if isinstance(raw_score, (int, float)) else _clean_for_xml(str(raw_score))
        weight = item.get("weight")
        weight_text = f" / {weight:g}% wt" if isinstance(weight, (int, float)) else ""
        dimension_cells.append(Paragraph(f"<b>{_clean_for_xml(name)}</b><br/>{score_text}{weight_text}", small))
    if not dimension_cells:
        dimension_cells = [
            Paragraph(f"<b>{name}</b><br/>N/A", small)
            for name in ("Workflow Pain", "Speed to Value", "Compounding Advantage", "Team Execution", "Market / Distribution")
        ]
    count = len(dimension_cells)
    dimensions = Table(
        [[Paragraph('<font color="#FFFFFF"><b>DIMENSION SCORE BREAKDOWN</b></font>', label)] + [""] * (count - 1), dimension_cells],
        colWidths=[540 / count] * count,
    )
    dimensions.setStyle(TableStyle([
        ("SPAN", (0, 0), (-1, 0)),
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_SLATE_MID),
        ("BOX", (0, 0), (-1, -1), .5, COLOR_SLATE_BORDER),
        ("INNERGRID", (0, 1), (-1, -1), .5, COLOR_SLATE_BORDER),
        ("ALIGN", (0, 1), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))

    def compact_list(items: list[str], fallback: str) -> Paragraph:
        values = items[:3] or [fallback]
        lines = [f"- {_transform_citations_for_pdf(_cap_text(item, 145), evidence_map)}" for item in values]
        return Paragraph("<br/>".join(lines), small)

    decisions = Table([
        [Paragraph('<font color="#DC2626"><b>KEY RISKS</b></font>', label), Paragraph('<font color="#059669"><b>WHAT CHANGES OUR MIND</b></font>', label)],
        [compact_list(analysis.risks, "No critical risk identified"), compact_list(analysis.changes_mind, "More verified traction")],
    ], colWidths=[270, 270])
    decisions.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), COLOR_ROSE_LIGHT),
        ("BACKGROUND", (1, 0), (1, -1), COLOR_EMERALD_LIGHT),
        ("BOX", (0, 0), (-1, -1), .5, COLOR_SLATE_BORDER),
        ("INNERGRID", (0, 0), (-1, -1), .5, COLOR_SLATE_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))

    sources_data = [[
        Paragraph('<font color="#FFFFFF"><b>#</b></font>', small),
        Paragraph('<font color="#FFFFFF"><b>TRUST</b></font>', small),
        Paragraph('<font color="#FFFFFF"><b>SOURCE</b></font>', small),
        Paragraph('<font color="#FFFFFF"><b>SUPPORTING EVIDENCE</b></font>', small),
    ]]
    for idx, item in enumerate(evidence[:3], start=1):
        if item.status == CitationTag.VERIFIED:
            tag_color, tag_text = "#059669", "VERIFIED"
        elif item.status == CitationTag.TRUSTED:
            tag_color, tag_text = "#2563EB", "TRUSTED"
        else:
            tag_color, tag_text = "#D97706", "CLAIMED"
        source_title = _clean_for_xml(_cap_text(item.source_title or item.claim, 70))
        if item.source_url.startswith(("http://", "https://")):
            source_title = f'<a href="{html.escape(item.source_url)}" color="#2563EB"><b>{source_title}</b></a>'
        support = f"{_format_source_category(item, candidate)}: {_cap_text(item.excerpt, 145)}"
        sources_data.append([
            Paragraph(f'<font color="#2563EB"><b>[{idx}]</b></font>', small),
            Paragraph(f'<font color="{tag_color}"><b>{tag_text}</b></font>', small),
            Paragraph(source_title, small),
            Paragraph(_clean_for_xml(support), small),
        ])
    if len(sources_data) == 1:
        sources_data.append([
            Paragraph("-", small), Paragraph("N/A", small),
            Paragraph("No cited sources", small), Paragraph("Evidence unavailable", small),
        ])
    sources = Table(sources_data, colWidths=[28, 58, 170, 284])
    sources.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_SLATE_MID),
        ("BOX", (0, 0), (-1, -1), .5, COLOR_SLATE_BORDER),
        ("INNERGRID", (0, 0), (-1, -1), .5, COLOR_SLATE_BORDER),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [COLOR_WHITE, COLOR_SLATE_LIGHT]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))

    content: list[Any] = []
    for block in (banner, metadata, thesis, snapshot, dimensions, decisions):
        content.extend([block, Spacer(1, 5)])
    content.extend([Paragraph("TOP SOURCES", label), sources])
    page = KeepInFrame(540, doc.height, content, mode="shrink")
    doc.build([page], canvasmaker=NumberedCanvas)
    LOGGER.info("rendered one-page pdf memo candidate=%s path=%s", candidate.slug, out_file)
    return out_file
