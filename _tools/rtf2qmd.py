"""Convert the Sampling Refresher RTF notes into Quarto .qmd pages + extracted figures.

The sources come in two flavors that share one authored design system:
  * clean hand-written RTF (Module 3)
  * Word round-tripped RTF (everything else) -- 10x more verbose, same semantics

Both are handled by one pass because the accent colors resolve to identical RGB
values. Roles are matched on RGB, never on the \\cf index (navy is \\cf1 in the
clean flavor and \\cf19 in the Word flavor).

Run:  python _tools/rtf2qmd.py
"""

import binascii
import os
import re
import struct
import sys

SRC = r"C:\Users\ilmul\Documents\UMICH\Sampling Refresher"
DST = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIGDIR = os.path.join(DST, "figures")

# source file -> (output stem, sidebar order)
FILES = [
    ("Sampling Refresher - Syllabus.rtf", "index", 0),
    ("Module 0 - Foundations.rtf", "00-foundations", 1),
    ("Module 1 - Simple Random Sampling.rtf", "01-simple-random-sampling", 2),
    ("Module 2 - Systematic Sampling.rtf", "02-systematic-sampling", 3),
    ("Module 3 - Stratified Sampling.rtf", "03-stratified-sampling", 4),
    ("Module 4 - Cluster Sampling.rtf", "04-cluster-sampling", 5),
    ("Module 5 - Multistage and PPS.rtf", "05-multistage-pps", 6),
    ("Module 6 - Weighting.rtf", "06-weighting", 7),
    ("Module 7 - Design-Based Analysis and Variance Estimation.rtf", "07-design-based-analysis", 8),
    ("Module 8 - Sample Size and Allocation in Practice.rtf", "08-sample-size-allocation", 9),
    ("Module 9 - Nonprobability Sampling.rtf", "09-nonprobability-sampling", 10),
    ("Module 10 - Power and Sample Size.rtf", "10-power-sample-size", 11),
]

PNG_SIG = b"\x89PNG\r\n\x1a\n"
PNG_END = b"IEND\xaeB`\x82"
HEXCHARS = set(b"0123456789abcdefABCDEF")

# Destinations whose contents never belong in the body text.
SKIP_DEST = set("""
fonttbl colortbl stylesheet listtable listoverridetable rsidtbl generator info
header headerl headerr headerf footer footerl footerr footerf
ftnsep ftnsepc aftnsep aftnsepc pnseclvl1 pnseclvl2 pnseclvl3 pnseclvl4 pnseclvl5
pnseclvl6 pnseclvl7 pnseclvl8 pnseclvl9 nonshppict pntext
themedata colorschememapping latentstyles datastore xmlnstbl docvar
wgrffmtfilter mmathPr panose fldinst fldrslt bkmkstart bkmkend
""".split())

ROLES = {
    (35, 57, 91): "accent",    # navy   - titles, section heads, key lines
    (42, 127, 127): "rule",    # teal   - rules, bullets, tagline
    (112, 112, 112): "muted",  # gray   - figure captions, footers
    (34, 34, 34): "body",      # near-black body text
}


# --------------------------------------------------------------------------
# figures
# --------------------------------------------------------------------------

def extract_pngs(raw):
    """Return [(offset, png_bytes), ...] in document order.

    NOTE: the {\\*\\blipuid <32 hex>} group that Word inserts between \\pngblip
    and the real payload must be skipped WHOLE. Merely tracking brace depth (as
    _tools/extract_figures_from_rtf.py does) lets its 32 hex characters into the
    buffer, prepending 16 junk bytes so the PNG signature check fails and the
    figure is silently dropped -- which is why that script recovers 4 of 56.
    """
    out = []
    for m in re.finditer(re.escape(b"\\pngblip"), raw):
        i = m.end()
        buf = bytearray()
        while i < len(raw):
            c = raw[i]
            if c == 0x7D:                       # }  end of the \pict group
                break
            if c == 0x7B:                       # {  skip the nested group whole
                depth = 1
                i += 1
                while i < len(raw) and depth:
                    if raw[i] == 0x7B:
                        depth += 1
                    elif raw[i] == 0x7D:
                        depth -= 1
                    i += 1
                continue
            if c == 0x5C:                       # \  control word
                i += 1
                while i < len(raw) and chr(raw[i]).isalpha():
                    i += 1
                while i < len(raw) and (chr(raw[i]).isdigit() or raw[i:i + 1] == b"-"):
                    i += 1
                continue
            if c in HEXCHARS:
                buf.append(c)
            i += 1

        if len(buf) % 2:
            buf = buf[:-1]
        try:
            data = binascii.unhexlify(bytes(buf))
        except binascii.Error:
            continue
        if not data.startswith(PNG_SIG) or not data.rstrip().endswith(PNG_END):
            continue
        out.append((m.start(), data))
    return out


# --------------------------------------------------------------------------
# text helpers
# --------------------------------------------------------------------------

MD_SPECIAL = re.compile(r"([\\*_\[\]<>`|#])")


def esc(s):
    """Escape markdown metacharacters.

    These notes are dense with formulas like n_h = n * (N_h / N); left raw, the
    underscores and asterisks turn into emphasis and quietly mangle the math.
    """
    return MD_SPECIAL.sub(r"\\\1", s)


def typography(s):
    s = s.replace(" -- ", " \u2014 ")
    s = s.replace("--", "\u2014")
    s = s.replace("->", "\u2192")
    # "Piece 1  -  What SRS is": a lone hyphen padded by 2+ spaces is an em dash
    s = re.sub(r"\s\s+-\s\s+", " \u2014 ", s)
    # the sources write "--" both padded and unpadded; space them uniformly
    s = re.sub(r" ?\u2014 ?", " \u2014 ", s)
    s = re.sub(r"[ \t]+", " ", s)
    return s


def runs_to_plain(runs, escape=True):
    """Flatten runs, dropping bold/italic. For headings and YAML fields."""
    s = typography("".join(t for t, _b, _i in runs))
    return (esc(s) if escape else s).strip()


def runs_to_md(runs, escape=True):
    """Join runs, applying bold/italic, merging adjacent same-format runs."""
    merged = []
    for text, bold, ital in runs:
        if not text:
            continue
        if merged and merged[-1][1] == bold and merged[-1][2] == ital:
            merged[-1][0] += text
        else:
            merged.append([text, bold, ital])

    parts = []
    for text, bold, ital in merged:
        lead = text[: len(text) - len(text.lstrip())]
        trail = text[len(text.rstrip()):]
        core = text.strip()
        if not core:
            parts.append(text)
            continue
        # typography first: escaping "->" to "-\>" would hide the arrow from it
        core = typography(core)
        if escape:
            core = esc(core)
        if bold and ital:
            core = "***%s***" % core
        elif bold:
            core = "**%s**" % core
        elif ital:
            core = "*%s*" % core
        parts.append(lead + core + trail)
    return re.sub(r"[ \t]+", " ", "".join(parts)).strip()


# --------------------------------------------------------------------------
# parser
# --------------------------------------------------------------------------

class Para:
    __slots__ = ("runs", "pf", "pict", "first_fs", "first_role", "raw")

    def __init__(self, runs, pf, pict, first_fs, first_role, raw):
        self.runs = runs
        self.pf = pf
        self.pict = pict
        self.first_fs = first_fs
        self.first_role = first_role
        self.raw = raw


class RtfParser:
    def __init__(self, raw_bytes):
        self.raw = raw_bytes.decode("latin-1")
        self.rawb = raw_bytes
        self.colors = self._colortbl()
        self.pngs = extract_pngs(raw_bytes)
        self.png_offsets = [o for o, _ in self.pngs]
        self.paras = []

    def _colortbl(self):
        """Map \\cf index -> RGB.

        The leading ';' in {\\colortbl;\\red..} terminates an empty 'auto' entry
        that occupies index 0, so the first real color is index 1. Enumerating
        the ';'-split segments from 0 keeps that alignment.
        """
        j = self.raw.find("colortbl")
        if j < 0:
            return {}
        seg = self.raw[j + len("colortbl"):self.raw.find("}", j)]
        colors = {}
        for idx, e in enumerate(seg.split(";")):
            r = re.search(r"red(\d+)", e)
            g = re.search(r"green(\d+)", e)
            b = re.search(r"blue(\d+)", e)
            if r and g and b:
                colors[idx] = (int(r.group(1)), int(g.group(1)), int(b.group(1)))
        return colors

    def role(self, cf):
        """Resolve a \\cf index to a semantic role by nearest palette color.

        Exact matching is too brittle: Module 2's teal is (42,127,117) while the
        other eleven files use (42,127,127), and that 10-unit drift silently
        demoted its tagline to body text.
        """
        rgb = self.colors.get(cf)
        if rgb is None:
            return "body"
        best, bestd = "body", 10 ** 9
        for ref, name in ROLES.items():
            d = sum((a - b) ** 2 for a, b in zip(rgb, ref))
            if d < bestd:
                best, bestd = name, d
        return best if bestd <= 30 ** 2 else "body"

    # ---- main scan -------------------------------------------------------
    def parse(self):
        raw = self.raw
        n = len(raw)
        i = 0

        newc = lambda: {"fs": 24, "b": 0, "i": 0, "cf": 0, "uc": 1}
        newp = lambda: {"q": "l", "li": 0, "fi": 0, "brdrb": 0, "brdrl": 0,
                        "brdrw": 0, "cbpat": 0, "intbl": 0, "cell": 0, "row": 0}

        ch = newc()
        pf = newp()
        stack = []
        depth = 0
        skip_at = None
        star = False
        pict_idx = 0

        runs = []          # (text, bold, italic) for the current paragraph
        buf = []           # text of the current run
        first = [None, None]   # (fs, role) of the first substantive run
        pict_here = None
        uc_skip = 0

        def flush_run():
            if buf:
                t = "".join(buf)
                if t.strip() and first[0] is None:
                    first[0] = ch["fs"]
                    first[1] = self.role(ch["cf"])
                runs.append((t, ch["b"], ch["i"]))
                del buf[:]

        def end_para(extra=None):
            flush_run()
            self.paras.append(Para(list(runs), dict(pf), pict_here,
                                   first[0], first[1], extra))
            del runs[:]
            first[0] = first[1] = None

        while i < n:
            c = raw[i]

            if c == "{":
                flush_run()
                stack.append((dict(ch), skip_at))
                depth += 1
                star = False
                i += 1
                continue

            if c == "}":
                flush_run()
                if stack:
                    saved, saved_skip = stack.pop()
                    ch = saved
                    skip_at = saved_skip
                depth -= 1
                i += 1
                continue

            if c == "\\":
                m = re.match(r"([a-zA-Z]+)(-?\d+)?[ ]?", raw[i + 1:i + 40])
                if m:
                    w = m.group(1)
                    par = int(m.group(2)) if m.group(2) else None
                    i += 1 + m.end()

                    if star:
                        star = False
                        # {\*\shppict ...} wraps the PNG we want; everything
                        # else marked ignorable really is ignorable.
                        if w != "shppict":
                            skip_at = depth
                        continue

                    if w == "pict":
                        gstart = i
                        d = 1
                        j = i
                        while j < n and d:
                            if raw[j] == "{":
                                d += 1
                            elif raw[j] == "}":
                                d -= 1
                                if d == 0:
                                    break
                            j += 1
                        # Only the \pngblip copy counts; Word also emits a
                        # \wmetafile8 fallback for the same image.
                        if any(gstart <= off < j for off in self.png_offsets):
                            pict_here = pict_idx
                            pict_idx += 1
                        i = j
                        continue

                    if skip_at is not None:
                        continue
                    if w in SKIP_DEST:
                        skip_at = depth
                        continue

                    flush_run()

                    if w == "par":
                        end_para()
                        pict_here = None
                        continue
                    if w == "pard":
                        pf = newp()
                        continue
                    if w == "plain":
                        ch = newc()
                        continue
                    if w in ("ql", "qc", "qr", "qj"):
                        pf["q"] = w[1]
                        continue
                    if w == "li":
                        pf["li"] = par or 0
                        continue
                    if w == "fi":
                        pf["fi"] = par or 0
                        continue
                    if w == "brdrb":
                        pf["brdrb"] = 1
                        continue
                    if w == "brdrl":
                        pf["brdrl"] = 1
                        continue
                    if w == "brdrw":
                        pf["brdrw"] = max(pf["brdrw"], par or 0)
                        continue
                    if w == "cbpat":
                        pf["cbpat"] = par or 0
                        continue
                    if w == "intbl":
                        pf["intbl"] = 1
                        continue
                    if w == "cell":
                        end_para()
                        pf["cell"] = 1
                        self.paras[-1].pf["cell"] = 1
                        self.paras[-1].pf["intbl"] = 1
                        continue
                    if w == "row":
                        end_para()
                        self.paras[-1].pf["row"] = 1
                        self.paras[-1].pf["intbl"] = 1
                        continue
                    if w == "fs":
                        ch["fs"] = par if par is not None else 24
                        continue
                    if w == "b":
                        ch["b"] = 0 if par == 0 else 1
                        continue
                    if w == "i":
                        ch["i"] = 0 if par == 0 else 1
                        continue
                    if w == "cf":
                        ch["cf"] = par or 0
                        continue
                    if w == "uc":
                        ch["uc"] = par if par is not None else 1
                        continue
                    if w == "u":
                        if par is not None:
                            buf.append(chr(par if par > 0 else par + 65536))
                        uc_skip = ch["uc"]
                        continue
                    if w == "bullet":
                        buf.append("\u2022")
                        continue
                    if w in ("tab",):
                        buf.append("\t")
                        continue
                    if w in ("line",):
                        buf.append("\n")
                        continue
                    if w in ("emdash",):
                        buf.append("\u2014")
                        continue
                    if w in ("endash",):
                        buf.append("\u2013")
                        continue
                    if w in ("lquote", "rquote"):
                        buf.append("'")
                        continue
                    if w in ("ldblquote", "rdblquote"):
                        buf.append('"')
                        continue
                    continue

                nxt = raw[i + 1] if i + 1 < n else ""
                if nxt == "'":
                    byte = int(raw[i + 2:i + 4], 16)
                    if uc_skip > 0:
                        uc_skip -= 1
                    elif skip_at is None:
                        buf.append(bytes([byte]).decode("cp1252", "replace"))
                    i += 4
                    continue
                if nxt == "*":
                    star = True
                    i += 2
                    continue
                if skip_at is None:
                    buf.append(nxt)
                i += 2
                continue

            if c in "\r\n":
                i += 1
                continue

            if skip_at is not None:
                i += 1
                continue
            if uc_skip > 0:
                uc_skip -= 1
                i += 1
                continue

            buf.append(c)
            i += 1

        flush_run()
        if runs:
            end_para()
        return self.paras


# --------------------------------------------------------------------------
# paragraph classification -> markdown
# --------------------------------------------------------------------------

def classify(p):
    pf, fs, role = p.pf, p.first_fs or 24, p.first_role or "body"
    bold = any(r[1] for r in p.runs if r[0].strip())
    ital = any(r[2] for r in p.runs if r[0].strip())

    if p.pict is not None:
        return "figure"
    if pf["intbl"]:
        return "cell"
    if pf["q"] == "c":
        if fs >= 40:
            return "title"
        # Tagline and figure caption are both centered italics; the accent color
        # is what separates them -- teal rule for the tagline, gray for captions.
        if ital and role == "rule":
            return "subtitle"
        if ital and role == "muted":
            return "caption"
        if bold and role == "accent":
            return "keyline"
        return "center"
    if pf["brdrl"] or pf["cbpat"] or (pf["brdrb"] and pf["li"] > 0):
        return "callout"
    if pf["brdrb"] and pf["li"] == 0 and bold:
        return "h2"
    if pf["li"] > 0 and pf["fi"] < 0:
        return "listitem"
    if pf["li"] > 0:
        return "indent"
    return "para"


BULLET_RE = re.compile(r"^\s*[\u2022\u00b7\-]\s*\t?\s*")
NUMBER_RE = re.compile(r"^\s*(\d+)[.)]\s*\t?\s*")


def render(paras, stem):
    """Turn classified paragraphs into markdown blocks."""
    blocks = []
    title = subtitle = None
    table = []          # list of rows; each row is a list of cell strings
    cells = []          # cells of the row being built
    cell_buf = []       # paragraphs of the cell being built (cells can hold >1)
    figno = 0
    pending_fig = None   # index into blocks of a figure awaiting its caption

    def flush_table():
        nonlocal table
        if not table:
            return
        width = max(len(r) for r in table)
        rows = [r + [""] * (width - len(r)) for r in table]
        # drop trailing all-empty rows Word leaves behind
        while rows and not any(c.strip() for c in rows[-1]):
            rows.pop()
        if rows:
            head = rows[0]
            body = rows[1:]
            out = ["| " + " | ".join(head) + " |",
                   "|" + "|".join(["---"] * width) + "|"]
            for r in body:
                out.append("| " + " | ".join(r) + " |")
            blocks.append("\n".join(out))
        table = []

    for p in paras:
        kind = classify(p)
        text = runs_to_md(p.runs)

        if kind != "cell" and (table or cells or cell_buf):
            if cell_buf:
                cells.append(" ".join(cell_buf))
                cell_buf = []
            if cells:
                table.append(cells)
                cells = []
            flush_table()

        if kind == "title":
            if title is None:
                title = runs_to_plain(p.runs, escape=False)
            continue
        if kind == "subtitle":
            if subtitle is None:
                subtitle = runs_to_plain(p.runs, escape=False)
            continue

        if kind == "cell":
            # Keep empty cells: a blank corner cell in a header row is real, and
            # dropping it shifts every column left and desyncs the table.
            if text:
                cell_buf.append(text)
            if p.pf["cell"]:
                cells.append(" ".join(cell_buf))
                cell_buf = []
            if p.pf["row"]:
                if cell_buf:
                    cells.append(" ".join(cell_buf))
                    cell_buf = []
                if cells:
                    table.append(cells)
                cells = []
            continue

        if kind == "figure":
            figno += 1
            name = "%s-fig%d.png" % (stem, figno)
            blocks.append("![](figures/%s){fig-align=\"center\"}" % name)
            pending_fig = len(blocks) - 1
            if text:
                blocks.append(text)
            continue

        if kind == "caption":
            if pending_fig is not None and text:
                cap = text.replace("[", "(").replace("]", ")")
                blocks[pending_fig] = blocks[pending_fig].replace("![]", "![%s]" % cap, 1)
                pending_fig = None
                continue
            if text:
                blocks.append("::: {.caption}\n%s\n:::" % text)
            continue

        pending_fig = None

        if not text:
            continue

        if kind == "h2":
            blocks.append("## " + runs_to_plain(p.runs))
        elif kind == "keyline":
            blocks.append("::: {.keyline}\n%s\n:::" % text)
        elif kind == "callout":
            blocks.append("::: {.fieldnote}\n%s\n:::" % text)
        elif kind == "listitem":
            m = NUMBER_RE.match(text)
            if m:
                blocks.append("%s. %s" % (m.group(1), NUMBER_RE.sub("", text, count=1)))
            else:
                blocks.append("- " + BULLET_RE.sub("", text, count=1))
        elif kind == "indent":
            blocks.append("> " + text)
        elif kind == "center":
            blocks.append("::: {.center}\n%s\n:::" % text)
        else:
            blocks.append(text)

    if cell_buf:
        cells.append(" ".join(cell_buf))
    if cells:
        table.append(cells)
    flush_table()
    return title, subtitle, blocks


def join_blocks(blocks):
    """Blank line between blocks, but keep consecutive list items tight."""
    out = []
    prev_list = False
    for b in blocks:
        is_list = bool(re.match(r"^(- |\d+\. )", b))
        if out:
            out.append("\n" if (is_list and prev_list) else "\n\n")
        out.append(b)
        prev_list = is_list
    return "".join(out)


def yaml_escape(s):
    return '"%s"' % s.replace("\\", "").replace('"', "'")


MODULE_STEMS = {int(s.split("-")[0]): s for _f, s, _o in FILES if s[0].isdigit()}


def linkify_index(body):
    """Home page: make the module list clickable, and drop the local-path note.

    The syllabus was written for a folder of Word files, so it points at
    C:\\Users\\... and tells the reader to open RTFs -- both wrong (and the path
    is needlessly personal) on a public site.
    """
    def link(m):
        num = int(m.group(1))
        stem = MODULE_STEMS.get(num)
        return "**[%s](%s.qmd)**" % (m.group(0).strip("*"), stem) if stem else m.group(0)

    body = re.sub(r"^\*\*Module (\d+)[^*\n]*\*\*$", link, body, flags=re.M)

    body = re.sub(
        r"^- \*\*Where files live:\*\*.*$",
        "- **Where these notes live:** this site; the module pages are generated "
        "from the original illustrated notes.",
        body, flags=re.M)
    body = re.sub(
        r"^- \*\*Format:\*\*.*$",
        "- **Format:** every module is a page here, with all figures and tables "
        "carried over from the source notes.",
        body, flags=re.M)
    return body


def main():
    os.makedirs(FIGDIR, exist_ok=True)
    total_figs = 0
    summary = []

    for fname, stem, order in FILES:
        path = os.path.join(SRC, fname)
        if not os.path.exists(path):
            print("MISSING: %s" % fname)
            continue

        raw = open(path, "rb").read()
        parser = RtfParser(raw)
        paras = parser.parse()
        title, subtitle, blocks = render(paras, stem)

        for k, (_off, data) in enumerate(parser.pngs, 1):
            open(os.path.join(FIGDIR, "%s-fig%d.png" % (stem, k)), "wb").write(data)
        total_figs += len(parser.pngs)

        front = ["---"]
        front.append("title: %s" % yaml_escape(title or stem))
        if subtitle:
            front.append("subtitle: %s" % yaml_escape(subtitle))
        front.append("order: %d" % order)
        front.append("---")

        body = join_blocks(blocks)
        if stem == "index":
            body = linkify_index(body)
        text = "\n".join(front) + "\n\n" + body + "\n"
        text = re.sub(r"\n{4,}", "\n\n\n", text)

        out = os.path.join(DST, stem + ".qmd")
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

        n_h2 = len(re.findall(r"^## ", body, re.M))
        n_li = len(re.findall(r"^(?:- |\d+\. )", body, re.M))
        n_tb = len(re.findall(r"^\|---", body, re.M))
        n_tr = len(re.findall(r"^\| ", body, re.M))
        n_co = body.count("::: {.fieldnote}")
        n_kl = body.count("::: {.keyline}")
        summary.append((stem, len(parser.pngs), n_h2, n_li, n_tb, n_tr, n_co, n_kl, len(text)))

    print("%-28s %4s %4s %4s %4s %5s %4s %4s %8s"
          % ("PAGE", "FIG", "H2", "LI", "TBL", "ROWS", "NOTE", "KEY", "BYTES"))
    for s in summary:
        print("%-28s %4d %4d %4d %4d %5d %4d %4d %8d" % s)
    print("TOTAL FIGURES: %d" % total_figs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
