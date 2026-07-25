"""Resume rendering via the existing Jake-LaTeX -> PDF pipeline.

Applies an APPROVED diff to the matching base resume's .tex source and compiles with
pdflatex. If RESUME_RENDER_MODE='manual' (or pdflatex is missing), it writes the
tailored .tex for the user to compile on Overleaf and returns that path instead.

The diff only ever touches: bullet ordering/emphasis in Experience & Projects, the
Technical Skills list, and the one-line Professional Summary. Contact info, education,
and the Astrotech Labs internship are never modified (enforced upstream in the tailor
agent's prompt + validation).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional

from backend import config


def base_tex_path(track: str) -> Path:
    return config.RESUME_GO_TEX if track == "go" else config.RESUME_NODE_TEX


def base_pdf_path(track: str) -> Path:
    return config.RESUME_GO_PDF if track == "go" else config.RESUME_NODE_PDF


# Skeleton used only when neither .tex nor .pdf is available yet, so the tailor agent
# still has a structural anchor. Reflects Section 7 of the spec.
_SKELETON = {
    "go": ("Track: Go Backend Engineer | Distributed Systems | Microservices.\n"
           "Summary: (one line, editable).\n"
           "Skills: Go, goroutines/channels/worker pools, Kubernetes, microservices, ...\n"
           "Experience: Astrotech Labs internship (LOCKED — do not edit).\n"
           "Projects: Distributed Trade Execution Engine; AI Resume Matcher (Go-first framing)."),
    "node": ("Track: Backend Engineer | Go | Distributed Systems (Node-emphasis).\n"
             "Summary: (one line, editable).\n"
             "Skills: Node.js, Express, MongoDB, AWS S3, payment gateway/webhooks, ...\n"
             "Experience: Astrotech Labs internship (LOCKED — do not edit).\n"
             "Projects: AI Resume Matcher (Node-first framing)."),
}


def base_resume_text(track: str) -> str:
    """Best available representation of the base resume for diff proposals.
    Prefers .tex source, then extracted PDF text, then a structural skeleton."""
    tex = base_tex_path(track)
    if tex.exists():
        return tex.read_text(encoding="utf-8", errors="ignore")
    pdf = base_pdf_path(track)
    if pdf.exists():
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(pdf))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception:  # noqa: BLE001
            pass
    return _SKELETON[track]


def base_tex_source(track: str) -> Optional[str]:
    tex = base_tex_path(track)
    return tex.read_text(encoding="utf-8", errors="ignore") if tex.exists() else None


def render(job_id: int, track: str, tailored_tex: Optional[str]) -> dict:
    """Render a tailored resume. Returns {'pdf_path','tex_path','mode','ok','note'}.

    `tailored_tex` is the full LaTeX source produced by applying the approved diff.
    If it's None (no .tex source available), we fall back to copying the base PDF so
    the pipeline still yields a usable artifact, and flag that real tailoring needs
    the .tex source.
    """
    config.ensure_dirs()
    out_tex = config.RESUME_OUTPUT_DIR / f"resume_{track}_job{job_id}.tex"
    out_pdf = config.RESUME_OUTPUT_DIR / f"resume_{track}_job{job_id}.pdf"

    if not tailored_tex:
        base = base_pdf_path(track)
        if base.exists():
            shutil.copy(base, out_pdf)
            return {"pdf_path": str(out_pdf), "tex_path": None, "mode": "base_pdf_copy",
                    "ok": True, "note": f"No {track} .tex source; used base PDF unchanged. "
                                        "Provide RESUME_*_TEX for real tailoring."}
        return {"pdf_path": None, "tex_path": None, "mode": "none", "ok": False,
                "note": f"No base .tex or .pdf found for track '{track}'."}

    out_tex.write_text(tailored_tex, encoding="utf-8")

    pdflatex = shutil.which(config.PDFLATEX_BIN)
    if config.RESUME_RENDER_MODE != "pdflatex" or not pdflatex:
        return {"pdf_path": None, "tex_path": str(out_tex), "mode": "manual", "ok": True,
                "note": "pdflatex unavailable — compile the .tex on Overleaf, then set final_pdf_path."}

    try:
        for _ in range(2):  # two passes for references/layout
            # -no-shell-escape hardens against a malicious \write18 in a crafted .tex
            # (the diff is human-approved, but defense-in-depth against prompt injection).
            subprocess.run(
                [pdflatex, "-no-shell-escape", "-interaction=nonstopmode",
                 "-output-directory", str(config.RESUME_OUTPUT_DIR), str(out_tex)],
                check=True, capture_output=True, timeout=120,
            )
        return {"pdf_path": str(out_pdf), "tex_path": str(out_tex), "mode": "pdflatex",
                "ok": out_pdf.exists(), "note": "Compiled with pdflatex."}
    except Exception as e:  # noqa: BLE001
        return {"pdf_path": None, "tex_path": str(out_tex), "mode": "manual", "ok": True,
                "note": f"pdflatex failed ({e}); compile the .tex on Overleaf manually."}
