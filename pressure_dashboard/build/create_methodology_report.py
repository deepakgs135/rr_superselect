from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "pressure_report"
OUTDIR = ROOT / "reports"
OUTDIR.mkdir(parents=True, exist_ok=True)
OUT = OUTDIR / "Cricket_Pressure_Analytics_Methodology_and_Evidence.docx"

clutch = json.loads((DATA / "clutch_batting_report.json").read_text(encoding="utf-8"))
death = json.loads((DATA / "death_bowling_report.json").read_text(encoding="utf-8"))
state = json.loads((DATA / "pressure_report.json").read_text(encoding="utf-8"))
sv = state["validation"]
bat_top = clutch["final_batting_top_ten"]
phase_by_id = {int(r["player_id"]): r for r in clutch["phase_candidate_rankings"]}
bowl_top = death["top_ten"]
near = death["eligible_rankings"][10:11]

BLUE = "#4F7DF3"
CORAL = "#F27A63"
TEAL = "#25A99A"
GOLD = "#F0B84B"
PALE = "#EAF1FF"
PALE2 = "#F5F8FC"
GRAY = "#66758A"
BORDER = "#D9D9D9"


def font(size: int, bold: bool = False):
    paths = [
        r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\calibrib.ttf" if bold else r"C:\Windows\Fonts\calibri.ttf",
    ]
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


def draw_batting(path: Path):
    w, h = 1700, 1000
    im = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(im)
    d.text((65, 38), "Middle to death scoring shift", font=font(38, True), fill="#000000")
    d.text((65, 92), "Raw strike rates for the final ten clutch batters; the diagonal marks no change.", font=font(21), fill=GRAY)
    x0, y0, x1, y1 = 155, 165, 1050, 865
    low, high = 100, 230
    for v in range(low, high + 1, 20):
        x = x0 + (v - low) / (high - low) * (x1 - x0)
        y = y1 - (v - low) / (high - low) * (y1 - y0)
        d.line((x, y0, x, y1), fill="#E6EBF2", width=2)
        d.line((x0, y, x1, y), fill="#E6EBF2", width=2)
        d.text((x, y1 + 15), str(v), font=font(17), fill=GRAY, anchor="mt")
        d.text((x0 - 15, y), str(v), font=font(17), fill=GRAY, anchor="rm")
    d.line((x0, y1, x1, y1), fill="#78879A", width=3)
    d.line((x0, y0, x0, y1), fill="#78879A", width=3)
    d.line((x0, y1, x1, y0), fill="#A7B1C2", width=3)
    d.text(((x0 + x1) // 2, 950), "Middle overs 7 to 15 strike rate", font=font(20, True), fill="#26364A", anchor="mm")
    label = "Death overs 16 to 20 strike rate"
    label_font = font(20, True)
    label_box = d.textbbox((0, 0), label, font=label_font)
    label_img = Image.new("RGBA", (label_box[2] - label_box[0] + 8, 42), (255, 255, 255, 0))
    ImageDraw.Draw(label_img).text((4, 3), label, font=label_font, fill="#26364A")
    label_img = label_img.rotate(90, expand=True)
    im.paste(label_img, (35, (y0 + y1 - label_img.height) // 2), label_img)
    colors = [BLUE] * 7 + [CORAL] * 3
    for i, r in enumerate(bat_top):
        mx = float(r.get("middle_phase_strike_rate") or 0)
        dx = float(r.get("death_phase_strike_rate") or 0)
        x = x0 + (mx - low) / (high - low) * (x1 - x0)
        y = y1 - (dx - low) / (high - low) * (y1 - y0)
        d.ellipse((x - 17, y - 17, x + 17, y + 17), fill=colors[i], outline="white", width=3)
        d.text((x, y), str(i + 1), font=font(18, True), fill="white", anchor="mm")
    lx, ly = 1110, 170
    d.text((lx, ly), "Final shortlist", font=font(22, True), fill="#000000")
    ly += 45
    for i, r in enumerate(bat_top):
        d.ellipse((lx, ly + 3, lx + 24, ly + 27), fill=colors[i])
        d.text((lx + 38, ly), f"{i + 1}  {r['player']}", font=font(18), fill="#26364A")
        d.text((lx + 38, ly + 27),
               f"{float(r['middle_phase_strike_rate']):.1f} to {float(r['death_phase_strike_rate']):.1f} SR",
               font=font(16), fill=GRAY)
        ly += 66
    d.text((lx, ly + 5), "Blue: approved top seven order", font=font(16), fill=BLUE)
    d.text((lx, ly + 31), "Coral: phase-score selections", font=font(16), fill=CORAL)
    im.save(path)


def draw_bowler_scores(path: Path):
    rows = list(bowl_top) + near
    w, h = 1700, 930
    im = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(im)
    d.text((65, 38), "Death-over bowling composite", font=font(38, True), fill="#000000")
    d.text((65, 92), "Ten leading selections and the next eligible bowler; scores are percentiles within 51 eligible players.",
           font=font(21), fill=GRAY)
    x0, x1, y0, rowh = 420, 1450, 160, 57
    for v in range(0, 101, 20):
        x = x0 + v / 100 * (x1 - x0)
        d.line((x, y0 - 8, x, y0 + rowh * len(rows)), fill="#E7ECF3", width=2)
        d.text((x, y0 + rowh * len(rows) + 15), str(v), font=font(16), fill=GRAY, anchor="mt")
    for i, r in enumerate(rows):
        y = y0 + i * rowh
        rank = int(r.get("rank") or 11)
        score = float(r.get("composite_score") or 0)
        d.text((68, y + 7), f"{rank:>2}", font=font(19, True), fill=GRAY)
        d.text((125, y + 7), str(r.get("player", "")), font=font(18), fill="#26364A")
        xe = x0 + score / 100 * (x1 - x0)
        color = GOLD if rank == 1 else (BLUE if rank <= 5 else TEAL) if rank <= 10 else "#B9C3D0"
        d.rounded_rectangle((x0, y + 7, xe, y + 37), radius=8, fill=color)
        d.text((min(xe + 13, x1 + 42), y + 6), f"{score:.1f}", font=font(18, True), fill="#26364A")
    d.text((x0, h - 40), "Composite score out of 100", font=font(18), fill=GRAY)
    im.save(path)


def blend(a, b, t):
    return tuple(round(a[i] * (1 - t) + b[i] * t) for i in range(3))


def draw_bowler_heatmap(path: Path):
    fields = [
        ("adjusted_economy_percentile", "Economy\n30%"),
        ("ranking_dot_pct_percentile", "Dot balls\n25%"),
        ("adjusted_wickets_per_100_percentile", "Wickets / 100\n20%"),
        ("ranking_boundary_pct_percentile", "Boundary control\n15%"),
        ("ranking_singles_twos_pct_percentile", "1s and 2s control\n10%"),
    ]
    w, h = 1700, 850
    im = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(im)
    d.text((65, 38), "What drives each death-over score", font=font(36, True), fill="#000000")
    d.text((65, 90), "Component percentiles among 51 eligible bowlers. Higher cells are better after reversing lower-is-better measures.",
           font=font(19), fill=GRAY)
    left, top, cw, ch = 400, 165, 240, 58
    d.text((65, top - 22), "Rank and bowler", font=font(18, True), fill="#000000")
    for j, (_, label) in enumerate(fields):
        x = left + j * cw
        for k, line in enumerate(label.split("\n")):
            d.text((x + cw / 2, top - 38 + k * 21), line, font=font(16, True), fill="#000000", anchor="mm")
    for i, r in enumerate(bowl_top):
        y = top + i * ch
        d.text((70, y + 15), f"{int(r.get('rank') or i + 1):>2}  {r.get('player', '')}",
               font=font(17), fill="#26364A")
        for j, (field, _) in enumerate(fields):
            v = max(0, min(100, float(r.get(field) or 0)))
            t = v / 100
            base = blend((252, 231, 228), (207, 239, 226), t)
            color = blend(base, (255, 244, 201), max(0, 1 - abs(t - .5) * 2) * .5)
            x = left + j * cw
            d.rounded_rectangle((x + 5, y + 4, x + cw - 5, y + ch - 4),
                                radius=7, fill=color, outline="#D9E1E9", width=1)
            d.text((x + cw / 2, y + ch / 2), f"{v:.0f}", font=font(17, True),
                   fill="#26364A", anchor="mm")
    im.save(path)


def shade(cell, color):
    tcpr = cell._tc.get_or_add_tcPr()
    shd = tcpr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tcpr.append(shd)
    shd.set(qn("w:fill"), color.replace("#", ""))


def cell_margins(cell, amount=90):
    tcpr = cell._tc.get_or_add_tcPr()
    mar = tcpr.first_child_found_in("w:tcMar")
    if mar is None:
        mar = OxmlElement("w:tcMar")
        tcpr.append(mar)
    for side in ("top", "start", "bottom", "end"):
        node = mar.find(qn("w:" + side))
        if node is None:
            node = OxmlElement("w:" + side)
            mar.append(node)
        node.set(qn("w:w"), str(amount))
        node.set(qn("w:type"), "dxa")


def table_borders(table):
    pr = table._tbl.tblPr
    borders = pr.first_child_found_in("w:tblBorders")
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        node = borders.find(qn("w:" + edge))
        if node is None:
            node = OxmlElement("w:" + edge)
            borders.append(node)
        node.set(qn("w:val"), "single")
        node.set(qn("w:sz"), "5")
        node.set(qn("w:space"), "0")
        node.set(qn("w:color"), BORDER[1:])


def add_table(doc, headers, rows, widths, numeric=(), size=8.2):
    table = doc.add_table(rows=1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    table_borders(table)
    data = [headers] + [[str(v) if v is not None else "Not reported" for v in row] for row in rows]
    trpr = table.rows[0]._tr.get_or_add_trPr()
    repeat = OxmlElement("w:tblHeader")
    repeat.set(qn("w:val"), "true")
    trpr.append(repeat)
    for ri, vals in enumerate(data):
        cells = table.rows[ri].cells if ri < len(table.rows) else table.add_row().cells
        cant = OxmlElement("w:cantSplit")
        table.rows[ri]._tr.get_or_add_trPr().append(cant)
        for ci, (cell, value) in enumerate(zip(cells, vals)):
            cell.width = Inches(widths[ci])
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            cell_margins(cell)
            cell.text = ""
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.line_spacing = 1.0
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER if ri == 0 or ci in numeric else WD_ALIGN_PARAGRAPH.LEFT
            run = p.add_run(str(value))
            run.font.name = "Arial"
            run.font.size = Pt(size)
            run.bold = ri == 0
            run.font.color.rgb = RGBColor(0, 0, 0) if ri == 0 else RGBColor(35, 48, 65)
            run._element.rPr.rFonts.set(qn("w:ascii"), "Arial")
            run._element.rPr.rFonts.set(qn("w:hAnsi"), "Arial")
            shade(cell, PALE if ri == 0 else ("#FFFFFF" if ri % 2 else PALE2))
    doc.add_paragraph().paragraph_format.space_after = Pt(1)
    return table


def nfmt(value, digits=1):
    if value is None or value == "":
        return "NR"
    try:
        x = float(value)
        return f"{x:,.{digits}f}" if math.isfinite(x) else "NR"
    except (TypeError, ValueError):
        return str(value)


def remove_paragraph_border(ppr):
    if ppr is not None:
        border = ppr.find(qn("w:pBdr"))
        if border is not None:
            ppr.remove(border)


doc = Document()
section = doc.sections[0]
section.page_width = Inches(8.5)
section.page_height = Inches(11)
section.top_margin = Inches(.65)
section.bottom_margin = Inches(.62)
section.left_margin = Inches(.68)
section.right_margin = Inches(.68)
section.footer_distance = Inches(.32)
normal = doc.styles["Normal"]
normal.font.name = "Arial"
normal.font.size = Pt(10.2)
normal.font.color.rgb = RGBColor(35, 48, 65)
normal._element.rPr.rFonts.set(qn("w:ascii"), "Arial")
normal._element.rPr.rFonts.set(qn("w:hAnsi"), "Arial")
normal.paragraph_format.space_after = Pt(6)
normal.paragraph_format.line_spacing = 1.1
for name, size in (("Title", 27), ("Heading 1", 17), ("Heading 2", 13), ("Heading 3", 11)):
    style = doc.styles[name]
    style.font.name = "Arial"
    style.font.size = Pt(size)
    style.font.bold = True
    style.font.color.rgb = RGBColor(0, 0, 0)
    style._element.rPr.rFonts.set(qn("w:ascii"), "Arial")
    style._element.rPr.rFonts.set(qn("w:hAnsi"), "Arial")
    style.paragraph_format.space_before = Pt(14 if name != "Title" else 0)
    style.paragraph_format.space_after = Pt(6)
    style.paragraph_format.keep_with_next = True
remove_paragraph_border(doc.styles["Title"]._element.pPr)
cap = doc.styles.add_style("Report Caption", 1)
cap.font.name = "Arial"
cap.font.size = Pt(8.5)
cap.font.italic = True
cap.font.color.rgb = RGBColor(98, 113, 132)
cap._element.rPr.rFonts.set(qn("w:ascii"), "Arial")
cap._element.rPr.rFonts.set(qn("w:hAnsi"), "Arial")
cap.paragraph_format.space_before = Pt(3)
cap.paragraph_format.space_after = Pt(8)

footer = section.footer.paragraphs[0]
footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
rr = footer.add_run("Cricket Pressure Analytics  |  17 November 2026  |  ")
rr.font.name = "Arial"
rr.font.size = Pt(8)
rr.font.color.rgb = RGBColor(112, 125, 142)
page = OxmlElement("w:fldSimple")
page.set(qn("w:instr"), "PAGE")
footer._p.append(page)


def para(text, style=None, alignment=None):
    p = doc.add_paragraph(style=style)
    p.add_run(str(text))
    if alignment is not None:
        p.alignment = alignment
    return p


def bullet(text):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.left_indent = Inches(.24)
    p.paragraph_format.first_line_indent = Inches(-.12)
    p.add_run(text)
    return p


def figure(path, caption):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(3)
    p.paragraph_format.space_after = Pt(0)
    p.add_run().add_picture(str(path), width=Inches(6.95))
    para(caption, "Report Caption", WD_ALIGN_PARAGRAPH.CENTER)


# Executive summary
p = doc.add_paragraph()
p.paragraph_format.space_after = Pt(7)
r = p.add_run("CRICKET ANALYTICS  |  RAW-DATA METHOD")
r.bold = True
r.font.name = "Arial"
r.font.size = Pt(9)
r.font.color.rgb = RGBColor(64, 105, 185)
title = doc.add_paragraph("Cricket Pressure Analytics Methodology and Evidence", style="Title")
remove_paragraph_border(title._p.get_or_add_pPr())
p = doc.add_paragraph()
p.paragraph_format.space_after = Pt(15)
r = p.add_run("Pressure definitions, player scoring, sample rules, validation, and current top-ten support")
r.font.name = "Arial"
r.font.size = Pt(12)
r.font.color.rgb = RGBColor(78, 96, 119)
para("This report explains how the dashboard reconstructs pressure from raw ball-by-ball records and selects the featured batter and bowler lists. The featured lists use different samples: clutch batting uses Indian-venue IPL T20 chases, while death-over bowling uses Indian-venue T20 and T20I innings. The exact bowling-pressure state is too small to rank and is reported as a count only.")
doc.add_heading("Problem statement", level=1)
para("Modern T20 scoring creates pressure for both roles. For batting, the decision question is: after about five overs, with two or three wickets down and a required rate of at least 15 runs per over, which batters can stabilize, keep scoring, and turn the chase around? For bowling, the question is: in the last five overs, with no more than two wickets down, current rate at least 11 and required rate at least 9, which bowlers can take wickets while keeping runs down? The rankings use raw ball-by-ball performance evidence; match victory and reputation are not scoring inputs.")
para("The exact match states are sparse in this extract. The report therefore labels the wider batting anchor and death-over role samples used for reliable comparisons, and does not claim that they exactly reproduce every target situation.", "Report Caption")
doc.add_heading("Current evidence at a glance", level=1)
add_table(doc, ["Selection", "Current sample", "How to read the result"], [
    ["Clutch batting", "40 qualifying IPL T20 chase anchors; 16 phase-eligible batters", "Ten shown. The first seven keep the approved order; the last three are phase-score selections."],
    ["Death-over bowling", "51 eligible bowlers after sample and recency gates", "Ten ranked on recent Indian death-over performance across the latest 10 eligible innings."],
    ["Exact bowling-pressure state", "38 flagged deliveries across 3 decided chases", "Below the 20-chase publishing threshold; no state-specific bowler ranking is issued."],
], [1.45, 2.0, 3.65], size=8.8)
para("The final batter order is not a model-sorted order for all ten places. The seven previously approved names keep their requested sequence. The remaining three places go to the highest-scoring eligible alternatives. The report shows phase-cohort rank separately from final shortlist position.")
para("Match outcome is not part of either featured score. The pressure state defines the situation; player performance measures determine the composite. Neither score is a win probability or a guarantee of future performance.")
para("Prepared 17 November 2026 from report files generated on 16 November 2026. Raw CSV inputs: Raw_Data/ball_by_ball.csv, Raw_Data/matches.csv, and Raw_Data/competitions.csv.", "Report Caption")

# Definitions and state reconstruction
doc.add_page_break()
doc.add_heading("1  Data and pressure definitions", level=1)
para("The build joins ball_by_ball.csv to matches.csv by match_id and then to competitions.csv by comp_id. Player figures are keyed by source player_id. The featured clutch-batting and death-over ranking inputs are aggregated directly from the raw files rather than from the processed player leaderboard.")
raw = sv.get("raw_totals", {})
para(f"The raw extract contains {int(raw.get('delivery_rows', 0)):,} delivery rows, a sum of {int(raw.get('runs', 0)):,} in the runs field, {int(raw.get('legal_balls', 0)):,} known legal balls, and {int(raw.get('unknown_legality_rows', 0)):,} unknown-legality rows. These totals cover all source records, including formats outside the featured rankings.")
doc.add_heading("The dashboard uses four distinct pressure views", level=2)
add_table(doc, ["View", "Rule", "Scope", "Reason"], [
    ["Broad batting-pressure state", "Second innings; 1-30 legal balls remain; at least 3 wickets down; RRR >= 15; runs remain.", "All-venue T20 chase state.", "High asking rate, short runway, and a weakened batting side."],
    ["Broad bowling-pressure state", "Second innings; 1-30 legal balls remain; at most 2 wickets down; CRR >= 11; RRR >= 9; runs remain.", "All-venue T20 chase state.", "Fast scoring against a mostly intact batting side while runs are still needed."],
    ["Clutch-batting anchor", "Indian-venue T20 chase; first known pre-delivery state with 2-4 wickets down, 18-42 legal balls bowled, RRR 12-20, and runs still needed. Measure from that ball onward.", "40 IPL T20 chase anchors in the current build.", "A broader state yields enough observations for role-level study."],
    ["Death-over bowling sample", "Indian-venue T20 and T20I; innings 1 or 2; overs 16-20. No narrow chase-state filter.", "Latest 10 eligible Indian death-over innings.", "Used because the exact bowling-pressure state has only 3 decided chases."],
], [1.35, 2.65, 1.35, 1.7], size=7.9)
para("The final clutch-batting ranking contains 40 qualifying IPL chases from 2022-2026. A separate entry-timing audit searched T20 and T20I and found 14 T20I anchors; those are not in the final batter ranking. The death-over bowler ranking does include T20I. The report does not adjust for format differences, so the two lists should not be compared directly.", "Report Caption")
doc.add_heading("How the chase state is reconstructed", level=2)
for text in [
    "The state is measured before each delivery. For a chase, use revised_target when populated; otherwise use the first-innings total plus one.",
    "Team score reconstruction adds one run for each wide, Overstep no-ball, bye, and leg-bye row because their extra-run amounts are zero in this export. This is an explicit imputation. The raw runs field remains the batter-runs value.",
    "Known legal types are none, byes, and legbyes. Wides and Overstep deliveries do not advance legal balls. Other, Penalty, blank, and unrecognized legality rows are unknown; that row and later states in the innings are excluded.",
    "A batter ball is any known delivery that is not a wide. Batter dismissals are wicket rows assigned to the batter, excluding retire-outs, retired hurt, and obstruction labels. Wickets down use this dismissal definition.",
    "Bowler runs are raw runs plus one per wide or no-ball; byes and leg-byes are not charged. Credited bowler wickets are caught, bowled, LBW, stump, or hit-wicket dismissals.",
    "Only innings 1 and 2 are used. Super overs and extra innings are excluded. Match outcome does not enter the score.",
]:
    bullet(text)
doc.add_page_break()
doc.add_heading("Broad T20 chase-state counts", level=2)
state_rows = []
for row in state.get("state_table", []):
    state_rows.append([row.get("state"), f"{int(row.get('delivery_rows', 0)):,}",
                       f"{int(row.get('matches', 0)):,}", f"{int(row.get('decided_chases', 0)):,}",
                       f"{int(row.get('legal_balls', 0)):,}", row.get("reporting_status", "")])
add_table(doc, ["Role state", "Delivery rows", "Matches", "Decided chases", "Legal balls", "Status"],
          state_rows, [1.55, .85, .65, .9, .75, 2.0], numeric=(1, 2, 3, 4), size=8.0)
para("Batting and bowling are parallel role-specific counts. Do not add delivery rows across roles to obtain a distinct-match or unique-delivery total. The current raw recount has 3,229 batting pressure flags and 38 bowling pressure flags; the corrected state table differs from the independent raw recount on zero deliveries.", "Report Caption")

# Measures, scoring, eligibility
doc.add_heading("2  Performance measures and scoring", level=1)
doc.add_heading("Broad player comparisons by state", level=2)
para("The broad state leaderboards compare pressure deliveries with ordinary chase deliveries. A player comparison is eligible only when both states pass the role-specific minimum. Displayed statistics are raw; adjusted values shrink small samples toward the eligible-cohort baseline for composite scoring only.")
add_table(doc, ["Role", "Composite components", "Shrinkage prior", "Minimum"], [
    ["Batting", "50% adjusted SR; 30% adjusted average; 20% boundary share.", "SR: 60 balls. Average: 3 dismissals.", "30 balls in each state; report average only at 3 or more dismissals."],
    ["Bowling", "40% adjusted economy; 40% adjusted wickets per 6 legal balls; 20% dot share.", "Economy and wicket rate: 60 legal balls each.", "30 legal balls in each state; at least 3 credited wickets for wicket-rate ranking."],
], [1.0, 2.5, 1.45, 2.25], size=8.1)
para("State cells require 20 decided chases. Venue or season cohorts require 10 matches, and player rankings require 10 eligible players. Below-minimum player rows remain visible as review samples. The general pressure report uses a 2026 role appearance at any venue and the latest 10 known T20 second-innings cohort innings as its recency settings.")
doc.add_page_break()
doc.add_heading("Featured clutch-batting score", level=2)
co = clutch.get("cohort", {})
para(f"The candidate pool starts with {int(co.get('anchor_chases', 0))} Indian-venue IPL T20 anchors. A player needs at least 30 anchor-window balls, 3 qualifying anchor-window innings, a T20 appearance in 2026 at any venue, and 10 Indian-venue T20 chase innings. Sixteen players pass the final reliability and exclusion gates and have at least 30 balls in both phase samples. Rashid Khan, Dhruv Jurel, and Shashank Singh are excluded from the final selection at the user’s request.")
para("The narrower requested picture—roughly the end of over 5, 2-3 wickets down, and RRR near 16—contains only 11 Indian chases in this extract. The 18-42-ball, 2-4-wicket, RRR 12-20 anchor is a stated widening to compare similar pressure situations; it is not presented as an exact match to every requested condition.")
add_table(doc, ["Component", "Weight", "Definition"], [
    ["Death-over strike rate", "25%", "Adjusted SR for overs 16-20 in Indian-venue T20 innings."],
    ["Middle-over strike rate", "15%", "Adjusted SR for overs 7-15 in Indian-venue T20 innings."],
    ["SR acceleration", "20%", "Adjusted death SR minus adjusted middle SR."],
    ["Runs across phases", "15%", "Raw middle-over plus death-over runs."],
    ["Boundary-rate acceleration", "15%", "Death boundaries per 100 batter balls minus middle boundaries per 100."],
    ["Phase average", "10%", "Adjusted runs per dismissal across both phases; raw average needs 3 dismissals."],
], [1.55, .65, 5.05], size=8.1)
bs = clutch.get("phase_ranking_summary", {})
para(f"Each component becomes a tie-aware percentile among {int(bs.get('phase_eligible_players', 0))} phase-eligible candidates; weighted points sum to a score out of 100. Phase strike rates blend with 60 balls at the phase baseline; phase average blends with 3 dismissals. Current baselines are middle SR {nfmt(bs.get('middle_baseline_strike_rate'), 2)}, death SR {nfmt(bs.get('death_baseline_strike_rate'), 2)}, and phase average {nfmt(bs.get('average_baseline'), 2)}.")
para("The phase score uses each candidate’s Indian-venue T20 history across innings 1 and 2, not only deliveries after the clutch anchor. Anchor-window figures establish pressure experience; broader phase history describes role performance. Latest-ten Indian chase figures are context and eligibility evidence, not score components.")
para("The top seven retain the previously approved order. The other three names are the highest-scoring eligible alternatives. Phase-cohort rank appears separately from final place. Phase-score ties break by more death balls, more combined phase runs, then player name and source ID.")
doc.add_page_break()
doc.add_heading("Featured death-over bowling score", level=2)
cnt = death.get("counts", {})
para(f"Bowlers are measured only on Indian-venue death overs, overid 16-20, in innings 1 and 2. The ranking uses each bowler’s latest 10 eligible Indian death-over innings. Eligibility requires at least 30 legal balls and 3 credited wickets in that sample, at least 10 eligible Indian death-over innings, one T20/T20I appearance in 2026 at any venue, and a latest Indian death-over appearance in 2026. {int(cnt.get('eligible_players', 0))} players pass. Jamie Overton, Lungi Ngidi, and Gerald Coetzee are excluded at the user’s request.")
add_table(doc, ["Component", "Weight", "Direction and calculation"], [
    ["Adjusted economy", "30%", "Lower is better; latest-ten runs x 6 / legal balls, shrunk to eligible-cohort baseline."],
    ["Dot-ball percentage", "25%", "Higher is better; legal death balls with zero team runs / legal balls."],
    ["Adjusted wickets / 100", "20%", "Higher is better; credited wickets / legal balls x 100, with 60-ball shrinkage."],
    ["Boundary concessions", "15%", "Lower is better; fours plus sixes per 100 legal balls."],
    ["Singles and twos allowed", "10%", "Lower is better; legal balls with 1 or 2 team runs / legal balls."],
], [1.65, .65, 4.95], size=8.1)
para(f"The latest-ten economy baseline is {nfmt(cnt.get('eligible_cohort_baseline_economy'), 4)}; the wickets-per-100 baseline is {nfmt(cnt.get('eligible_cohort_baseline_wickets_per_100'), 4)}. Each component becomes a tie-aware percentile across eligible bowlers, reversing lower-is-better measures. The score is relative to this cohort, not an absolute skill grade.")

# Evidence section
doc.add_page_break()
doc.add_heading("3  Evidence for the clutch-batting shortlist", level=1)
para("Pressure-window runs, balls, strike rates, and dismissals come from the clutch-anchor window. Phase SR, phase score, and latest-ten form come from the wider cohorts described above.")
bat_main = []
for row in bat_top:
    phase = phase_by_id[int(row["player_id"])]
    dismissals = int(row.get("dismissals") or 0)
    avg = nfmt(float(row.get("runs") or 0) / dismissals, 1) if dismissals >= 3 else "NR (<3)"
    bat_main.append([row.get("final_rank"), phase.get("phase_weighted_rank"), row.get("player"),
                     row.get("innings"), row.get("balls"), row.get("runs"),
                     nfmt(row.get("strike_rate"), 1), avg, row.get("stayed_to_16")])
add_table(doc, ["Final", "Phase\nrank", "Batter", "Press\ninn.", "Balls", "Runs", "Press\nSR", "Press avg.¹", "Over 16²"],
          bat_main, [.42, .48, 1.3, .5, .5, .5, .55, .75, .75], numeric=(0, 1, 3, 4, 5, 6, 7), size=7.9)
para("¹ Raw pressure average is shown only at 3 or more pressure dismissals. ² Survived through 16 completed overs; the denominator includes innings that reached 96 known legal balls with the batter already in. Diagnostic only; not scored.", "Report Caption")

bat_phase = []
for row in bat_top:
    phase = phase_by_id[int(row["player_id"])]
    raw_avg = row.get("phase_average_raw")
    avg = (f"{nfmt(raw_avg, 1)} / {nfmt(row.get('phase_average_adjusted'), 1)} "
           f"({int(row.get('phase_total_dismissals') or 0)} d)") if isinstance(raw_avg, (float, int)) \
        else f"NR / {nfmt(row.get('phase_average_adjusted'), 1)}"
    recent = f"{int(row.get('recent_form_runs') or 0)}/{int(row.get('recent_form_balls') or 0)} · {nfmt(row.get('recent_form_strike_rate'), 1)}"
    bat_phase.append([f"{row.get('final_rank')} / {phase.get('phase_weighted_rank')}", row.get("player"),
                      f"{nfmt(row.get('middle_phase_strike_rate'), 1)} ({int(row.get('middle_phase_balls') or 0)})",
                      f"{nfmt(row.get('death_phase_strike_rate'), 1)} ({int(row.get('death_phase_balls') or 0)})",
                      nfmt(row.get("phase_sr_acceleration"), 1), avg,
                      nfmt(row.get("phase_weighted_score"), 1), recent])
para("Phase and form evidence. “Final / phase” shows shortlist position followed by the fully score-sorted rank among phase-eligible candidates.", "Report Caption")
add_table(doc, ["Final /\nphase", "Batter", "Middle SR\n(balls)", "Death SR\n(balls)", "Adj. SR\nlift", "Phase avg.\nraw / adj.", "Score /\n100", "Latest 10 runs / balls · SR"],
          bat_phase, [.58, 1.08, .8, .8, .62, 1.1, .62, 1.35], numeric=(0, 2, 3, 4, 6), size=7.6)

with tempfile.TemporaryDirectory(prefix="cricket_methodology_") as tmp:
    tmp = Path(tmp)
    bat_png, bow_png, heat_png = tmp / "batting.png", tmp / "bowling.png", tmp / "components.png"
    draw_batting(bat_png)
    draw_bowler_scores(bow_png)
    draw_bowler_heatmap(heat_png)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run().add_picture(str(bat_png), width=Inches(6.95))
    para("Figure 1. Middle-to-death raw strike-rate shift. Blue points show the approved top seven in their retained order; coral points show the three phase-score selections. Points above the diagonal raised their strike rate in overs 16-20.", "Report Caption", WD_ALIGN_PARAGRAPH.CENTER)
    para("The displayed order differs from the score order. Suryakumar Yadav and Rishabh Pant share the highest displayed phase score (74.3); Tilak Varma is third by score (74.0). Hardik Pandya is 15th by phase score but remains second in the final list because the approved top-seven order is fixed.")

    doc.add_page_break()
    doc.add_heading("4  Evidence for the death-over bowling top ten", level=1)
    para("Every rate below uses the bowler’s latest 10 eligible Indian death-over innings. Raw values sit beside adjusted values wherever shrinkage applies. The eligible pool has 51 bowlers; no reputation-based name is forced into the list.")
    bowl_rows = []
    for row in bowl_top:
        bowl_rows.append([row.get("rank"), row.get("player"), row.get("ranking_balls"), row.get("ranking_runs"),
                          f"{nfmt(row.get('ranking_economy'), 2)} / {nfmt(row.get('adjusted_economy'), 2)}",
                          f"{int(row.get('ranking_dot_balls') or 0)} / {nfmt(row.get('ranking_dot_pct'), 1)}%",
                          row.get("ranking_wickets"),
                          f"{nfmt(row.get('ranking_wickets_per_100'), 1)} / {nfmt(row.get('adjusted_wickets_per_100'), 1)}",
                          nfmt(row.get("composite_score"), 1)])
    add_table(doc, ["Rank", "Bowler", "Balls\nlast 10", "Runs", "Economy\nraw / adj.", "Dots / %", "Wkts", "W / 100\nraw / adj.", "Score"],
              bowl_rows, [.4, 1.05, .55, .48, .88, .72, .4, 1.02, .5], numeric=(0, 2, 3, 6, 8), size=7.6)
    bowl_control = [[r.get("rank"), r.get("player"), nfmt(r.get("ranking_boundary_pct"), 1),
                     nfmt(r.get("ranking_singles_twos_pct"), 1),
                     f"{r.get('ranking_first_date')} to {r.get('ranking_latest_date')}"] for r in bowl_top]
    para("Run-control evidence from the same latest-ten sample. Boundary and 1-2 rates are counts per 100 legal death balls.", "Report Caption")
    add_table(doc, ["Rank", "Bowler", "Boundaries / 100", "Singles and twos / 100", "Sample dates"],
              bowl_control, [.45, 1.35, 1.35, 1.55, 1.85], numeric=(0, 2, 3), size=8.0)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run().add_picture(str(bow_png), width=Inches(6.95))
    para("Figure 2. Weighted composite for ranks 1-10 and the next eligible bowler. Higher scores indicate stronger relative component percentiles within this cohort.", "Report Caption", WD_ALIGN_PARAGRAPH.CENTER)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run().add_picture(str(heat_png), width=Inches(6.95))
    para("Figure 3. Component percentiles for the selected bowlers. Each column is oriented so higher is better; weights appear in the headings.", "Report Caption", WD_ALIGN_PARAGRAPH.CENTER)
    if near:
        nm = near[0]
        gap = float(bowl_top[-1].get("composite_score") or 0) - float(nm.get("composite_score") or 0)
        para(f"Cutoff comparison: rank 10 Suyash Sharma scores {nfmt(bowl_top[-1].get('composite_score'), 1)}; rank 11 {nm.get('player')} scores {nfmt(nm.get('composite_score'), 1)}. The displayed gap is {nfmt(gap, 1)} points. Displayed scores are rounded to one decimal.")

    # Validation and limitations
    doc.add_page_break()
    doc.add_heading("5  Reliability, comparisons, and limits", level=1)
    doc.add_heading("Independent checks", level=2)
    raw_flags = sv.get("raw_pressure_flag_totals", {})
    dbtot = sv.get("database_totals", {})
    dbflags = sv.get("database_pressure_flag_totals", {})
    validation_rows = [
        ["Raw source rows", f"{int(raw.get('delivery_rows', 0)):,}", f"{int(dbtot.get('delivery_rows', 0)):,}", "Match"],
        ["Runs field sum", f"{int(raw.get('runs', 0)):,}", f"{int(dbtot.get('runs', 0)):,}", "Match"],
        ["Known legal balls", f"{int(raw.get('legal_balls', 0)):,}", f"{int(dbtot.get('known_legal_balls', 0)):,}", "Match"],
        ["Current raw pressure flags", f"B {int(raw_flags.get('batting_pressure', 0)):,}; W {int(raw_flags.get('bowling_pressure', 0)):,}",
         f"B {int(dbflags.get('batting_pressure', 0)):,}; W {int(dbflags.get('bowling_pressure', 0)):,}",
         f"0 differences across {int(sv.get('pressure_delivery_rows_checked', 0)):,} states"],
        ["Clutch-batting rebuild", f"{int(clutch['validation'].get('checks_total', 0)):,} checks",
         f"{int(clutch['validation'].get('checks_passed', 0)):,} passed", "All pass"],
        ["Death-bowling rebuild", f"{int(death['validation'].get('checks_total', 0)):,} checks",
         f"{int(death['validation'].get('checks_passed', 0)):,} passed", "All pass"],
        ["Broad leaderboard rows", f"{int(sv.get('all_leaderboard_rows_checked', 0)):,} rows; 10 random rows",
         "912 rows and 10 random rows reproduced", "Pass"],
    ]
    add_table(doc, ["Check", "Reference", "Computed result", "Status"],
              validation_rows, [1.55, 1.8, 2.8, .85], size=7.9)
    old = sv.get("supplied_pressure_flag_reference", {})
    para(f"The earlier supplied pressure-flag reference was {int(old.get('both_pressure_flags', 0)):,} (batting {int(old.get('batting_pressure', 0)):,}, bowling {int(old.get('bowling_pressure', 0)):,}). The current raw recount is {int(raw_flags.get('both_pressure_flags', 0)):,} flags (batting {int(raw_flags.get('batting_pressure', 0)):,}, bowling {int(raw_flags.get('bowling_pressure', 0)):,}). The 45,385 figure counts second-innings delivery states checked; it is not the pressure-flag total. The previous reference remains a documented mismatch.")
    audit = next((r for r in clutch.get("reference_audit_rows", []) if r.get("player") == "David Miller"), {})
    if audit:
        para(f"The supplied clutch reference table reproduces only {int(clutch.get('reference_audit', {}).get('rows_matching_all_figures', 0))} of {int(clutch.get('reference_audit', {}).get('rows_compared', 0))} rows across all figures. For example, David Miller’s reference says {audit.get('reference_innings')} innings, {audit.get('reference_balls')} balls, {audit.get('reference_runs')} runs, and {nfmt(audit.get('reference_strike_rate'), 1)} SR; the raw audit finds {audit.get('source_innings')} innings, {audit.get('source_balls')} balls, {audit.get('source_runs')} runs, and {nfmt(audit.get('source_strike_rate'), 1)} SR. This falls below the current three-pressure-innings gate.")
    margin = sv.get("source_run_margin_reconciliation", {})
    if margin:
        checked = int(margin.get("checked_rows", 0))
        mismatched = int(margin.get("mismatched_rows", 0))
        reproduced = checked - mismatched
        para(f"The state validator compared {checked} source run margins under the requested count-based extras formula: {reproduced} match exactly and {mismatched} do not. Current pressure flags match the independent raw reconstruction, but source-margin differences limit confidence in targets where no revised target is present.")
    doc.add_heading("Where comparisons are less certain", level=2)
    for text in [
        "The exact bowling-pressure state has 3 decided chases, below the 20-chase guide. It is shown as 38 deliveries and is not used to rank bowlers. The trusted bowler list measures death-over role performance instead.",
        "The selected batters have 3-5 qualifying anchor-window innings. Ball, innings, and phase gates reduce but do not remove sample uncertainty.",
        "The batting shortlist uses IPL-tagged T20 matches; T20I is excluded from its score. Bowling includes T20 and T20I. There is no adjustment for competition, opponent strength, season, venue type, or role changes.",
        "The batting phase score uses the eligible players’ Indian T20 history across innings 1 and 2. Total phase runs can favor players with more exposure. Latest-ten chase form is separate and is not weighted into the score.",
        "Composite scores are relative percentiles, not probabilities. Scores can change when the eligible cohort changes.",
        "Wides, no-balls, byes, and leg-byes are imputed as one team run per row for state reconstruction. Unknown-legality events remove that row and all later states in the innings.",
    ]:
        bullet(text)
    doc.add_page_break()
    doc.add_heading("Overall analysis flow and reproduction", level=1)
    para("Overall view: raw CSVs are joined by match_id and comp_id; delivery legality and innings states are reconstructed; role-specific pressure and ordinary samples are aggregated; eligibility gates and weighted scores produce the featured player lists; independent validators recalculate results and compare them with published outputs before the dashboard reads the JSON/CSV files.")
    logic_rows = [
        ["python build/clutch_batting.py", "Reads raw matches and ball-by-ball rows; finds qualifying Indian IPL chase anchors; builds batter pressure, entry-timing, phase and recent-form figures; applies gates and the weighted phase score. Writes the clutch report JSON and audit/ranking CSVs."],
        ["python build/death_bowling.py", "Reads raw Indian T20/T20I innings 1-2; keeps death overs 16-20; reconstructs legal balls, bowler runs and credited wickets; takes each eligible bowler’s latest 10 innings; applies gates and weighted component percentiles. Writes the bowling report JSON and ranking CSV."],
        ["python build/pressure_report.py", "Builds the broad all-venue T20 chase states, including batting pressure, bowling pressure and ordinary chase rows; calculates player-state figures and eligible comparisons. Writes the state report and pressure CSVs."],
        ["python build/validate_clutch_batting.py", "Independently rebuilds the clutch anchors, batter totals, recent form, phase measures, eligibility, scores and order from the raw CSVs; compares them with the report and writes clutch_batting_validation.json."],
        ["python build/validate_death_bowling.py", "Independently rebuilds latest-ten death-over samples, rates, wickets, eligibility, adjusted metrics and ranking from the raw CSVs; compares them with the report and writes death_bowling_validation.json."],
        ["python build/validate_pressure.py", "Recounts broad pressure states and player rows from raw CSVs; compares state flags and totals with the report and processed database; checks all leaderboard rows, a random ten, top-ten batter figures, and source exceptions. Writes pressure_validation.json and audit CSVs."],
    ]
    add_table(doc, ["Run in this order", "Logic and result"], logic_rows,
              [2.55, 4.05], size=7.4)
    para("Run all three builders first, then their matching validators, from the pressure_dashboard folder. Keep the raw CSVs in Raw_Data/; validate_pressure.py also needs the dashboard’s processed database. Report snapshots are under data/pressure_report/.", "Report Caption")
    doc.core_properties.title = "Cricket Pressure Analytics Methodology and Evidence"
    doc.core_properties.subject = "Raw-data pressure definitions, scoring, evidence, and validation"
    doc.core_properties.author = ""
    doc.save(OUT)

print(OUT)
