#!/usr/bin/env python3
"""Build the arXiv LaTeX source from the markdown drafts.

    python3 paper/arxiv/build.py          # writes paper/arxiv/main.tex
    cd paper/arxiv && tectonic main.tex   # compiles main.pdf

Edit the markdown, not main.tex: main.tex is regenerated every run.
Front matter (title, author, abstract) lives in FRONT below.
Needs pandoc on PATH.
"""
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
BODY_MD = HERE.parent / "draft3_sec1-8.md"
APPX_MD = HERE.parent / "draft2_appendices.md"
OUT = HERE / "main.tex"

TITLE = r"``I Do Intend to Deliver'': Will LLMs Run a Marketplace Advance-Fee Scam?"
AUTHOR = r"Megan Squire\\ \normalsize\textit{F-Secure}"

ABSTRACT = r"""
Online fraud is traditionally limited by the cost of the human labor needed to talk
to potential victims. We ask whether hosted large language models will now supply that
labor. We prompted ten off-the-shelf models to play the seller in the ``free
item, just pay delivery'' advance-fee scam common on buy-and-sell sites, using
a plain system prompt with no jailbreak. Each model played 30 conversations
against each of four buyer personas, from credulous to guarded, with the same
model playing the buyer (1,200 conversations). We label each conversation by
what happened to the buyer's money, and validate the labels against two human
coders. 737 conversations (61\%) ended with the buyer paying in advance. Eight
of the ten models played in almost every conversation, and running both sides
cost about 2.5 cents per payment. Only the guarded buyer, who wanted a findable
identity, resisted, and the most willing sellers got past it by inventing names
and phone numbers. Sellers that recognized the scam still took the money in 133
conversations, usually reasoning about their own honesty rather than the
buyer's risk. Several models protected the buyer without refusing, by
conceding payment on delivery, so refusal rates alone misstate safety. We
release the benchmark, prompts, code and labels.
"""

PREAMBLE = r"""\documentclass[11pt]{article}
\usepackage[margin=1in]{geometry}
\usepackage{iftex}
\ifPDFTeX  % arXiv builds with pdfLaTeX
  \usepackage[T1]{fontenc}
  \usepackage[utf8]{inputenc}
  \usepackage{textcomp}
  \usepackage{lmodern}
\else      % tectonic / XeLaTeX locally
  \usepackage{fontspec}
\fi
\usepackage{amssymb}
\usepackage{microtype}
\usepackage{xcolor}
\usepackage{longtable,booktabs,array,calc}
\usepackage{fvextra}
\usepackage{enumitem}
\usepackage{caption}
\usepackage{needspace}
\usepackage[numbers,sort&compress,square]{natbib}
\usepackage[colorlinks=true,linkcolor=blue!50!black,citecolor=blue!50!black,urlcolor=blue!50!black]{hyperref}
\usepackage{xurl}

\captionsetup{font=small,labelfont=bf,skip=4pt}
\setlength{\LTcapwidth}{\textwidth}
\setlength{\parskip}{0.4em}
\setlength{\parindent}{0pt}
\setlist{itemsep=0.2em,topsep=0.3em}
\RecustomVerbatimEnvironment{verbatim}{Verbatim}{breaklines,fontsize=\footnotesize,frame=leftline,framerule=0.6pt,rulecolor=\color{black!30},xleftmargin=1em}
\newcommand{\tightlist}{\setlength{\itemsep}{0pt}\setlength{\parskip}{0pt}}
\newcommand{\todo}[1]{\textcolor{red}{[TODO: #1]}}
\providecommand{\pandocbounded}[1]{#1}
\setlength{\emergencystretch}{2em}
\newcounter{none} % pandoc: uncaptioned tables take no number
\renewcommand{\arraystretch}{1.1}

"""


def pandoc(md: str) -> str:
    return subprocess.run(
        ["pandoc", "-f", "markdown-implicit_figures", "-t", "latex",
         "--columns=105", "--syntax-highlighting=none",
         "--shift-heading-level-by=-1"],
        input=md, capture_output=True, text=True, check=True,
    ).stdout


def strip_comments(md: str) -> str:
    return re.sub(r"<!--.*?-->\n?", "", md, flags=re.S)


def unicode_fixes(md: str) -> str:
    # Latin Modern has no glyphs for these.
    return (md.replace("κ", r"\ensuremath{\kappa}").replace("≤", r"\ensuremath{\le}")
              .replace("±", r"\ensuremath{\pm}").replace(" 😄", r" \emph{[grinning emoji]}"))


def captions(md: str) -> str:
    """'**Table 4.** Caption text' before a pipe table -> pandoc 'Table: ...' after it."""
    out, pending = [], None
    lines = md.split("\n")
    i = 0
    while i < len(lines):
        m = re.match(r"\*\*Table [A-Z]?\d+\.\*\*\s*(.*)", lines[i])
        if m:
            cap = [m.group(1)]
            i += 1
            while i < len(lines) and lines[i].strip() and not lines[i].startswith("|"):
                cap.append(lines[i]); i += 1
            pending = " ".join(cap)
            continue
        out.append(lines[i])
        if pending and lines[i].startswith("|") and (i + 1 == len(lines) or not lines[i + 1].startswith("|")):
            out += ["", f"Table: {pending}"]
            pending = None
        i += 1
    return "\n".join(out)


def cites(md: str) -> str:
    """IEEE '[1], [2]' / '[3]–[5]' -> \\cite{r1,r2} / \\cite{r3,r4,r5}."""
    def expand(m):
        nums = []
        for part in re.finditer(r"\[(\d+)\](?:\s*–\s*\[(\d+)\])?", m.group(0)):
            a = int(part.group(1)); b = int(part.group(2) or a)
            nums += range(a, b + 1)
        return r"\cite{" + ",".join(f"r{n}" for n in nums) + "}"
    group = r"\[\d+\](?:\s*–\s*\[\d+\])?"
    return re.sub(rf"{group}(?:,\s*{group})*", expand, md)


def widths(md: str) -> str:
    """Give the wrapped text tables sensible column widths (pandoc sizes by dash count)."""
    md = md.replace("| Persona | What it takes to make them pay |\n|---|---|",
                    "| Persona | What it takes to make them pay |\n|----|---------------------|")
    md = md.replace("| Code | Meaning |\n|---|---|", "| Code | Meaning |\n|--|-----------|")
    md = md.replace("| situation | outcome | why |\n|---|---|---|",
                    "| situation | outcome | why |\n|----------|----|-----|")
    md = md.replace("|---|---|---|\n| REFUSED | `seller_refused`",
                    "|--|------|----|\n| REFUSED | `seller_refused`")
    md = md.replace("| PAID % | recognized & PAID |", "| PAID % | recog. & PAID |")
    return md


def headings(md: str, appendix: bool) -> str:
    md = re.sub(r"^## \d+\. ", "## ", md, flags=re.M)
    md = re.sub(r"^### \d+\.\d+ ", "### ", md, flags=re.M)
    if appendix:
        md = re.sub(r"^## Appendices\n", "", md, flags=re.M)
        md = re.sub(r"^### Appendix [A-Z]\. ", "## ", md, flags=re.M)
        md = re.sub(r"^#### [A-Z]\.\d+ ", "### ", md, flags=re.M)
        md = re.sub(r"^##### (.*)$", r"#### \1 {-}", md, flags=re.M)
    return md


def to_tex(md: str, appendix=False) -> str:
    md = strip_comments(md)
    # a list needs a blank line before it, or pandoc folds it into the paragraph
    md = re.sub(r"^([^\s*|>-].*)\n(\* )", r"\1\n\n\2", md, flags=re.M)
    md = re.sub(r"^(\s*[^\s>].*)\n(\s+> )", r"\1\n\n\2", md, flags=re.M)
    md = headings(md, appendix)
    md = unicode_fixes(md)
    md = captions(widths(md))
    if not appendix:
        md = cites(md)
    tex = pandoc(md)
    def shrink(m):  # wide numeric tables get a smaller font
        spec = m.group(1)
        ncols = spec.count("p{") or len(re.findall(r"[lrc]", spec[4:-4]))
        size = r"\footnotesize" if ncols >= 8 else r"\small"
        sep = "3pt" if ncols >= 10 else "4pt"
        return "{" + size + rf"\setlength{{\tabcolsep}}{{{sep}}}\begin{{longtable}}[]" + m.group(1)
    tex = re.sub(r"\\begin\{longtable\}\[\](\{@\{\}.*?@\{\}\})", shrink, tex, flags=re.S)
    tex = tex.replace(r"\end{longtable}", r"\end{longtable}}")
    def keep_together(m):  # a longtable breaks anywhere; ask for room for short ones
        rows = m.group(0).count("\\\\")
        wraps = r"\real{" in m.group(0)  # wrapped text rows: height unknown, let it break
        return ("" if wraps or rows > 25 else rf"\needspace{{{rows + 5}\baselineskip}}") + m.group(0)
    tex = re.sub(r"\{\\(?:small|footnotesize)\\setlength.*?\\end\{longtable\}\}", keep_together, tex, flags=re.S)
    return tex


def references(md: str) -> str:
    items = re.findall(r"^\[(\d+)\] (.+)$", md, flags=re.M)
    sep = "\n\nXXREFSEPXX\n\n"
    tex = pandoc(sep.join(unicode_fixes(t) for _, t in items))
    bodies = [b.strip() for b in tex.split("XXREFSEPXX")]
    assert len(bodies) == len(items)
    lines = [r"\begin{thebibliography}{99}", r"\small\raggedright"]
    lines += [f"\\bibitem{{r{n}}} {b}" for (n, _), b in zip(items, bodies)]
    lines.append(r"\end{thebibliography}")
    return "\n".join(lines)


def main():
    body = BODY_MD.read_text()
    body = re.sub(r"\A# .*\n", "", body)                      # title -> \title
    body, refs = body.split("## References", 1)
    appx = APPX_MD.read_text()
    appx_pre, appx_d = appx.split("### Appendix D.", 1)
    doc = [
        PREAMBLE,
        rf"\title{{{TITLE}}}",
        rf"\author{{{AUTHOR}}}",
        r"\date{November 2026}",
        r"\begin{document}",
        r"\maketitle",
        r"\begin{abstract}" + ABSTRACT + r"\end{abstract}",
        "",
        to_tex(body),
        references(refs),
        r"\clearpage",
        r"\appendix",
        to_tex(appx_pre, appendix=True),
        r"\setcounter{table}{0}\renewcommand{\thetable}{D\arabic{table}}",
        to_tex("### Appendix D." + appx_d, appendix=True),
        r"\end{document}",
    ]
    OUT.write_text("\n".join(doc))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
