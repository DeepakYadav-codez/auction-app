"""Excel / PDF / file-import helpers. Pure Python: app.py passes in plain dicts."""
import csv
import io
from xml.sax.saxutils import escape

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

HEAD_FILL = PatternFill("solid", fgColor="12382F")
HEAD_FONT = Font(bold=True, color="FFFFFF")
SECTION_FILL = PatternFill("solid", fgColor="DCE8E2")


# ----------------------------------------------------------------- Excel
def _put(ws, row, col, value):
    c = ws.cell(row=row, column=col, value=value)
    if isinstance(value, str) and value.startswith("="):
        c.data_type = "s"          # never let a name become a formula
    return c


def _title(text):
    bad = '[]:*?/\\'
    return "".join("-" if ch in bad else ch for ch in text)[:31]


def _autosize(ws, minimum=8, maximum=48):
    widths = {}
    for row in ws.iter_rows():
        for c in row:
            if c.value is not None:
                widths[c.column] = max(widths.get(c.column, 0), len(str(c.value)))
    for col, w in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = max(minimum, min(maximum, w + 2))


def _sheet(wb, title, header, rows, first=False):
    ws = wb.active if first else wb.create_sheet()
    ws.title = _title(title)
    for i, h in enumerate(header, 1):
        c = _put(ws, 1, i, h)
        c.font, c.fill = HEAD_FONT, HEAD_FILL
    for r, row in enumerate(rows, 2):
        for i, v in enumerate(row, 1):
            _put(ws, r, i, v)
    ws.freeze_panes = "A2"
    _autosize(ws)
    return ws


def _scorecard_sheet(wb, m, first=False):
    ws = wb.active if first else wb.create_sheet()
    ws.title = _title(f"M{m['id']} Scorecard")
    r = 1
    _put(ws, r, 1, m["title"]).font = Font(bold=True, size=14)
    r += 1
    _put(ws, r, 1, f"{m['overs']} overs a side - {m['status']}")
    if m["result"]:
        r += 1
        _put(ws, r, 1, m["result"]).font = Font(bold=True, color="1A7F4B")
    r += 2
    for c in m["cards"]:
        head = f"{c['bat']} - innings {c['number']}: {c['runs']}/{c['wickets']} ({c['overs']} ov, RR {c['run_rate']})"
        for col in range(1, 8):
            ws.cell(row=r, column=col).fill = SECTION_FILL
        _put(ws, r, 1, head).font = Font(bold=True)
        r += 1
        for i, h in enumerate(["Batter", "How out", "R", "B", "4s", "6s", "SR"], 1):
            x = _put(ws, r, i, h)
            x.font, x.fill = HEAD_FONT, HEAD_FILL
        r += 1
        for b in c["batting"]:
            for i, v in enumerate([b["name"], b["out"], b["runs"], b["balls"], b["fours"], b["sixes"], b["sr"]], 1):
                _put(ws, r, i, v)
            r += 1
        e = c["extras"]
        _put(ws, r, 1, "Extras")
        _put(ws, r, 2, f"wd {e['wd']}, nb {e['nb']}, b {e['b']}, lb {e['lb']}")
        _put(ws, r, 3, e["total"])
        r += 1
        _put(ws, r, 1, "Total").font = Font(bold=True)
        _put(ws, r, 2, f"{c['wickets']} wickets, {c['overs']} overs")
        _put(ws, r, 3, c["runs"]).font = Font(bold=True)
        r += 1
        if c["did_not_bat"]:
            _put(ws, r, 1, "Did not bat")
            _put(ws, r, 2, ", ".join(c["did_not_bat"]))
            r += 1
        if c["fow"]:
            _put(ws, r, 1, "Fall of wickets")
            _put(ws, r, 2, " | ".join(c["fow"]))
            r += 1
        r += 1
        for i, h in enumerate([f"{c['bowl']} bowling", "O", "M", "R", "W", "Econ"], 1):
            x = _put(ws, r, i, h)
            x.font, x.fill = HEAD_FONT, HEAD_FILL
        r += 1
        for b in c["bowling"]:
            for i, v in enumerate([b["name"], b["overs"], b["maidens"], b["runs"], b["wkts"], b["econ"]], 1):
                _put(ws, r, i, v)
            r += 1
        r += 2
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 34
    for col in "CDEFG":
        ws.column_dimensions[col].width = 9


def _ball_rows(matches):
    rows = []
    for m in matches:
        for b in m["balls"]:
            rows.append([m["title"], b["innings"], b["over"], b["bowler"], b["batter"], b["non_striker"],
                         b["runs_bat"], b["extra"], b["total"], b["wicket"], b["text"]])
    return rows


BALL_HEAD = ["Match", "Innings", "Over.Ball", "Bowler", "Batter", "Non-striker",
             "Runs off bat", "Extra", "Total runs", "Wicket", "Commentary"]


def build_workbook(auction=None, matches=(), batting=None, bowling=None, unit="L"):
    wb = Workbook()
    first = True
    if auction is not None:
        _sheet(wb, "Teams", ["Team", f"Budget ({unit})", f"Spent ({unit})", f"Left ({unit})", "Players"],
               [[t["name"], t["budget"], t["spent"], t["remaining"], len(t["players"])] for t in auction["teams"]],
               first=first)
        first = False
        squad = []
        for t in auction["teams"]:
            for p in t["players"]:
                squad.append([t["name"], p["name"], p["role"], p["base"], p["price"]])
        _sheet(wb, "Squads", ["Team", "Player", "Role", f"Base ({unit})", f"Sold for ({unit})"], squad)
        _sheet(wb, "Unsold & Available", ["Player", "Role", f"Base ({unit})", "Status"],
               [[p["name"], p["role"], p["base"], p["status"]] for p in auction["pool"]])
    if auction is not None and matches:
        rows = []
        for m in matches:
            inn = [f"{c['bat']} {c['runs']}/{c['wickets']} ({c['overs']} ov)" for c in m["cards"]]
            rows.append([m["id"], m["title"], m["overs"], m["status"], m["result"]] + inn + [""] * (2 - len(inn)))
        _sheet(wb, "Matches", ["#", "Match", "Overs", "Status", "Result", "Innings 1", "Innings 2"], rows)
    for m in matches:
        _scorecard_sheet(wb, m, first=first)
        first = False
    if batting is not None:
        _sheet(wb, "Top batters", ["Player", "Team", "Inns", "Runs", "Balls", "4s", "6s", "High", "Avg", "SR"],
               [[d["name"], d["team"], d["inns"], d["runs"], d["balls"], d["fours"], d["sixes"], d["hs"],
                 d["avg"], d["sr"]] for d in batting], first=first)
        first = False
        _sheet(wb, "Top bowlers", ["Player", "Team", "Overs", "Maidens", "Runs", "Wickets", "Econ"],
               [[d["name"], d["team"], d["overs"], d["maidens"], d["runs"], d["wkts"], d["econ"]]
                for d in bowling])
    ball_rows = _ball_rows(matches)
    if ball_rows:
        _sheet(wb, "Ball by ball", BALL_HEAD, ball_rows, first=first)
        first = False
    if first:
        _sheet(wb, "Empty", ["Nothing to export yet"], [], first=True)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ------------------------------------------------------------------- PDF
def _styles():
    ss = getSampleStyleSheet()
    return dict(
        title=ParagraphStyle("t", parent=ss["Title"], fontSize=22, alignment=0, spaceAfter=2),
        h=ParagraphStyle("h", parent=ss["Heading2"], fontSize=13, spaceBefore=14, spaceAfter=5),
        n=ParagraphStyle("n", parent=ss["BodyText"], fontSize=9, leading=11),
        small=ParagraphStyle("s", parent=ss["BodyText"], fontSize=8.5, leading=11, textColor=colors.HexColor("#555555")),
        res=ParagraphStyle("r", parent=ss["BodyText"], fontSize=13, leading=16, spaceBefore=4, spaceAfter=4,
                           textColor=colors.HexColor("#1a7f4b"), fontName="Helvetica-Bold"),
    )


def _p(text, style):
    return Paragraph(escape(str(text)), style)


def _tbl(rows, widths, right=(), bold_last=0):
    t = Table(rows, colWidths=[w * mm for w in widths], repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#12382F")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F1F5F3")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#C9D3CE")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for c in right:
        style.append(("ALIGN", (c, 0), (c, -1), "RIGHT"))
    for i in range(bold_last):
        style.append(("FONTNAME", (0, -1 - i), (-1, -1 - i), "Helvetica-Bold"))
    t.setStyle(TableStyle(style))
    return t


def _doc(buf, title):
    return SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                             topMargin=14 * mm, bottomMargin=14 * mm, title=title)


def scorecard_pdf(m):
    st = _styles()
    buf = io.BytesIO()
    story = [_p(m["title"], st["title"]), _p(f"{m['overs']} overs a side - {m['status']}", st["small"])]
    if m["result"]:
        story.append(_p(m["result"], st["res"]))
    for c in m["cards"]:
        story.append(_p(f"{c['bat']} - innings {c['number']}:  {c['runs']}/{c['wickets']}  "
                        f"({c['overs']} ov, RR {c['run_rate']})", st["h"]))
        rows = [["Batter", "How out", "R", "B", "4s", "6s", "SR"]]
        for b in c["batting"]:
            rows.append([_p(b["name"], st["n"]), _p(b["out"], st["n"]), b["runs"], b["balls"],
                         b["fours"], b["sixes"], b["sr"]])
        e = c["extras"]
        rows.append(["Extras", _p(f"wd {e['wd']}, nb {e['nb']}, b {e['b']}, lb {e['lb']}", st["n"]), e["total"], "", "", "", ""])
        rows.append(["Total", f"{c['wickets']} wkts, {c['overs']} ov", c["runs"], "", "", "", ""])
        story.append(_tbl(rows, [38, 62, 15, 15, 14, 14, 18], right=(2, 3, 4, 5, 6), bold_last=1))
        if c["did_not_bat"]:
            story.append(Spacer(1, 3))
            story.append(_p("Did not bat: " + ", ".join(c["did_not_bat"]), st["small"]))
        if c["fow"]:
            story.append(_p("Fall of wickets: " + " | ".join(c["fow"]), st["small"]))
        story.append(Spacer(1, 8))
        rows = [[f"{c['bowl']} bowling", "O", "M", "R", "W", "Econ"]]
        for b in c["bowling"]:
            rows.append([_p(b["name"], st["n"]), b["overs"], b["maidens"], b["runs"], b["wkts"], b["econ"]])
        if len(rows) == 1:
            rows.append(["No balls bowled", "", "", "", "", ""])
        story.append(_tbl(rows, [70, 20, 20, 22, 20, 24], right=(1, 2, 3, 4, 5)))
    _doc(buf, m["title"]).build(story)
    return buf.getvalue()


def auction_pdf(auction, unit="L"):
    st = _styles()
    buf = io.BytesIO()
    sold = sum(len(t["players"]) for t in auction["teams"])
    spent = round(sum(t["spent"] for t in auction["teams"]), 2)
    story = [_p("Auction result", st["title"]),
             _p(f"{len(auction['teams'])} teams - {sold} players sold - {spent}{unit} spent in total", st["small"])]
    for t in auction["teams"]:
        story.append(_p(f"{t['name']}", st["h"]))
        story.append(_p(f"Budget {t['budget']}{unit}  |  Spent {t['spent']}{unit}  |  Left {t['remaining']}{unit}  |  "
                        f"{len(t['players'])} players", st["small"]))
        story.append(Spacer(1, 3))
        rows = [["#", "Player", "Role", f"Price ({unit})"]]
        for i, p in enumerate(sorted(t["players"], key=lambda x: -(x["price"] or 0)), 1):
            rows.append([i, _p(p["name"], st["n"]), _p(p["role"], st["n"]), p["price"]])
        if len(rows) == 1:
            rows.append(["", "No players bought", "", ""])
        story.append(_tbl(rows, [12, 78, 52, 30], right=(0, 3)))
    if auction["pool"]:
        story.append(_p("Unsold and still available", st["h"]))
        rows = [["Player", "Role", f"Base ({unit})", "Status"]]
        for p in auction["pool"]:
            rows.append([_p(p["name"], st["n"]), _p(p["role"], st["n"]), p["base"], p["status"]])
        story.append(_tbl(rows, [70, 50, 26, 26], right=(2,)))
    _doc(buf, "Auction result").build(story)
    return buf.getvalue()


# --------------------------------------------------------- file import
def _norm(h):
    return str(h or "").strip().lower().replace("_", " ")


def parse_player_file(filename, raw):
    """Read a .csv or .xlsx of players. Returns a list of dicts: name, role, base."""
    if filename.lower().endswith(".xlsx"):
        wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        data = [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]
    else:
        text = raw.decode("utf-8-sig", errors="replace")
        data = list(csv.reader(io.StringIO(text)))
    if not data:
        return []
    head = [_norm(h) for h in data[0]]

    def col(options):
        for i, h in enumerate(head):
            if h in options:
                return i
        return None

    ni = col({"name", "player", "player name"})
    ri = col({"role", "type", "category"})
    bi = col({"base", "base price", "baseprice", "price"})
    if ni is None or bi is None:
        raise ValueError("The first row must have the columns: name, role, base_price.")
    out = []
    for row in data[1:]:
        if not any(row):
            continue

        def get(i):
            return row[i] if i is not None and i < len(row) else None
        out.append(dict(name=str(get(ni) or "").strip(), role=str(get(ri) or "").strip(), base=get(bi)))
    return out
