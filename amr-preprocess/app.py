"""Streamlit UI for the AMR document preprocessing pipeline.

Run with:
    streamlit run app.py
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import streamlit as st

from amr_preprocess.models import ProcessedDocument
from amr_preprocess.pipeline import process_path

ARTIFACTS_ROOT = Path(__file__).resolve().parent / "artifacts" / "ui-runs"

CLASS_STYLES = {
    "report": ("Report", "#2563eb"),
    "deck": ("Slide deck", "#7c3aed"),
    "scanned": ("Scanned", "#b45309"),
    "docx": ("Word", "#1d4ed8"),
    "pptx": ("PowerPoint", "#c2410c"),
    "sheet": ("Spreadsheet", "#047857"),
    "email": ("Email", "#be185d"),
    "text": ("Text", "#475569"),
    "unknown": ("Unknown", "#64748b"),
}

st.set_page_config(
    page_title="AMR Document Preprocessing",
    page_icon="📄",
    layout="wide",
)

st.markdown(
    """
    <style>
    .block-container { padding-top: 2.2rem; max-width: 1300px; }

    .amr-hero {
        background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 55%, #7c3aed 100%);
        border-radius: 16px;
        padding: 1.6rem 2rem;
        margin-bottom: 1.4rem;
        color: white;
    }
    .amr-hero h1 { color: white; font-size: 1.6rem; margin: 0 0 0.3rem 0; }
    .amr-hero p { color: rgba(255,255,255,0.85); margin: 0; font-size: 0.95rem; }

    .amr-badge {
        display: inline-block;
        padding: 0.15rem 0.65rem;
        border-radius: 999px;
        font-size: 0.75rem;
        font-weight: 600;
        color: white;
        letter-spacing: 0.02em;
    }

    .amr-metric {
        background: var(--secondary-background-color);
        border: 1px solid rgba(128,128,128,0.18);
        border-radius: 12px;
        padding: 0.8rem 1rem;
        text-align: center;
    }
    .amr-metric .v { font-size: 1.5rem; font-weight: 700; line-height: 1.2; }
    .amr-metric .l { font-size: 0.75rem; opacity: 0.65; text-transform: uppercase; letter-spacing: 0.06em; }

    div[data-testid="stFileUploader"] section {
        border: 2px dashed rgba(99,102,241,0.45);
        border-radius: 14px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def badge(doc_class: str) -> str:
    label, color = CLASS_STYLES.get(doc_class, CLASS_STYLES["unknown"])
    return f'<span class="amr-badge" style="background:{color}">{label}</span>'


def metric(value: str, label: str) -> str:
    return f'<div class="amr-metric"><div class="v">{value}</div><div class="l">{label}</div></div>'


def run_pipeline(files) -> None:
    with tempfile.TemporaryDirectory(prefix="amr-upload-") as tmp:
        tmp_dir = Path(tmp)
        for f in files:
            (tmp_dir / f.name).write_bytes(f.getbuffer())
        manifest, run_dir, docs = process_path(tmp_dir, ARTIFACTS_ROOT)
    st.session_state["run"] = {
        "run_id": manifest.run_id,
        "elapsed_ms": manifest.elapsed_ms,
        "run_dir": str(run_dir),
        "docs": [d.model_dump(mode="json") for d in docs],
    }


def table_grid(tbl: dict) -> list[dict]:
    headers = tbl.get("headers") or []
    rows = tbl.get("rows") or []
    width = max([len(r) for r in rows] + [len(h) for h in headers] + [1])
    if headers:
        cols = [" / ".join(filter(None, parts)) or f"col_{i+1}"
                for i, parts in enumerate(zip(*[h + [""] * (width - len(h)) for h in headers]))]
    else:
        cols = [f"col_{i+1}" for i in range(width)]
    return [{cols[i]: (r[i] if i < len(r) else "") for i in range(width)} for r in rows]


def render_document(doc: dict, all_docs: dict[str, dict]) -> None:
    left, right = st.columns([3, 1])
    with left:
        st.markdown(f"### {doc['filename']} &nbsp; {badge(doc['doc_class'])}", unsafe_allow_html=True)
        st.caption(f"doc_id `{doc['doc_id']}` · {doc['mime_type']}")
    with right:
        st.download_button(
            "Download JSON",
            data=json.dumps(doc, indent=2, ensure_ascii=False),
            file_name=f"{doc['doc_id']}.json",
            mime="application/json",
            key=f"dl-{doc['doc_id']}",
            width="stretch",
        )

    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(metric(str(doc["page_count"] or "—"), "pages"), unsafe_allow_html=True)
    c2.markdown(metric(str(len(doc["blocks"])), "text blocks"), unsafe_allow_html=True)
    c3.markdown(metric(str(len(doc["tables"])), "tables"), unsafe_allow_html=True)
    c4.markdown(metric(str(len(doc["figures"])), "figures"), unsafe_allow_html=True)
    st.write("")

    if doc["warnings"]:
        with st.expander(f"⚠ {len(doc['warnings'])} warning(s)"):
            for w in doc["warnings"]:
                st.warning(w)

    tabs = st.tabs(["Content", "Tables", "Pages", "Figures", "Metadata"])

    with tabs[0]:
        if doc.get("markdown"):
            st.markdown(doc["markdown"])
        elif doc["blocks"]:
            for b in doc["blocks"]:
                prefix = "#### " if b["type"] == "heading" else ""
                st.markdown(prefix + b["text"])
        else:
            st.info("No text content extracted.")

    with tabs[1]:
        if not doc["tables"]:
            st.info("No tables detected.")
        for tbl in doc["tables"]:
            meta = [f"method: {tbl['extraction_method']}"]
            if tbl.get("page"):
                meta.append(f"page {tbl['page']}")
            if tbl.get("confidence"):
                meta.append(f"confidence {tbl['confidence']:.2f}")
            st.caption(f"**{tbl.get('caption') or tbl['table_id']}** · " + " · ".join(meta))
            grid = table_grid(tbl)
            if grid:
                st.dataframe(grid, width="stretch", hide_index=True)
            else:
                st.info("Empty table.")

    with tabs[2]:
        paths = [p for p in doc["page_image_paths"] if Path(p).exists()]
        if not paths:
            st.info("No page renders for this document type.")
        else:
            cols = st.columns(3)
            for i, p in enumerate(paths):
                with cols[i % 3]:
                    st.image(p, caption=f"page {i + 1}", width="stretch")

    with tabs[3]:
        if not doc["figures"]:
            st.info("No figures detected.")
        for fig in doc["figures"]:
            cap = fig.get("caption") or fig["figure_id"]
            st.caption(f"**{cap}** · kind: {fig['kind']}" + (f" · page {fig['page']}" if fig.get("page") else ""))
            if fig.get("image_path") and Path(fig["image_path"]).exists():
                st.image(fig["image_path"], width=420)
            if fig.get("interpretation"):
                st.json(fig["interpretation"])

    with tabs[4]:
        st.json(doc["metadata"])

    if doc["children"]:
        st.markdown("**Attachments (re-ingested as child documents)**")
        for child_id in doc["children"]:
            child = all_docs.get(child_id)
            if child:
                with st.expander(f"📎 {child['filename']} — {child['doc_class']}"):
                    render_document(child, all_docs)


st.markdown(
    """
    <div class="amr-hero">
        <h1>AMR Document Preprocessing</h1>
        <p>Upload account-review documents — PDFs, decks, Word, spreadsheets, emails —
        and inspect the extracted structure: text, tables, figures, and provenance.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

uploaded = st.file_uploader(
    "Drop files here",
    type=["pdf", "docx", "doc", "pptx", "xlsx", "csv", "eml", "msg", "txt", "md"],
    accept_multiple_files=True,
    label_visibility="collapsed",
)

if uploaded:
    if st.button(f"Process {len(uploaded)} file(s)", type="primary"):
        with st.spinner("Running pipeline — ingest → route → extract → normalize…"):
            try:
                run_pipeline(uploaded)
            except Exception as exc:  # surface pipeline errors in the UI
                st.error(f"Pipeline failed: {exc}")

run = st.session_state.get("run")
if run:
    docs = run["docs"]
    by_id = {d["doc_id"]: d for d in docs}
    top_level = [d for d in docs if not d.get("parent_doc_id")]

    st.success(
        f"Run `{run['run_id']}` — {len(docs)} document(s) in {run['elapsed_ms']} ms · "
        f"artifacts in `{run['run_dir']}`"
    )

    if len(top_level) > 1:
        names = {f"{d['filename']}  ({d['doc_class']})": d["doc_id"] for d in top_level}
        choice = st.selectbox("Document", list(names))
        render_document(by_id[names[choice]], by_id)
    elif top_level:
        render_document(top_level[0], by_id)
else:
    st.markdown(
        "<p style='opacity:0.6'>No run yet — upload files above to get started. "
        "Emails with attachments are unpacked automatically; PDFs are routed by class "
        "(report / deck / scanned) before extraction.</p>",
        unsafe_allow_html=True,
    )
