"""Explicit synthetic evaluation; not QAS-06 or a production RAG benchmark."""

import argparse
import json
from collections import Counter
from pathlib import Path
from time import perf_counter

import fitz
from idp.pdf.service import DeepDocConfig, DeepDocService
from idp.publish import iter_retrievable_blocks
from retrieval.canonical_harness import LocalRagIndex, resolve_citation
from search.retrieval_plan import terms

FACTS = [
    (
        "table",
        "The cerium row lists the nitrate catalyst.",
        "Which catalyst is listed for cerium?",
        1,
    ),
    (
        "figure",
        "The synthetic diagram shows a cobalt triangle.",
        "What shape is shown in the cobalt diagram?",
        1,
    ),
    (
        "native",
        "Cobalt crystals reflect blue light.",
        "What color do cobalt crystals reflect?",
        1,
    ),
    (
        "scan",
        "Zeolite absorbs ammonium ions from water.",
        "What does zeolite absorb?",
        1,
    ),
    (
        "mixed",
        "A quasar spectrum contains hydrogen lines.",
        "Which lines occur in a quasar spectrum?",
        1,
    ),
    (
        "mixed",
        "The orbital period of Kepler is ninety days.",
        "What is the orbital period of Kepler?",
        2,
    ),
    (
        "columns",
        "Iodine solution has an amber appearance.",
        "What appearance does iodine solution have?",
        1,
    ),
    ("columns", "Neon gas emits orange light.", "What light does neon gas emit?", 1),
    (
        "formula",
        "A right triangle satisfies the Pythagorean relation.",
        "Which relation describes a right triangle?",
        1,
    ),
    (
        "vietnamese",
        "Tam giác cân có hai cạnh bằng nhau.",
        "Tam giác cân có mấy cạnh bằng nhau?",
        1,
    ),
]


def generate(directory):
    directory.mkdir(parents=True, exist_ok=True)
    font = next(
        p
        for p in (
            Path("C:/Windows/Fonts/arial.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        )
        if p.is_file()
    )
    paths = {}
    for name in dict.fromkeys(f[0] for f in FACTS):
        with fitz.open() as pdf:
            items = [f for f in FACTS if f[0] == name]
            for number in range(1, max(f[3] for f in items) + 1):
                page = pdf.new_page(width=680, height=400)
                page.insert_font(fontname="unicode", fontfile=str(font))
                lines = [f[1] for f in items if f[3] == number]
                for i, line in enumerate(lines):
                    page.insert_text(
                        (
                            30 if i == 0 else 350,
                            80 if name == "columns" else 80 + i * 40,
                        ),
                        line,
                        fontname="unicode",
                        fontsize=10 if name == "columns" else 16,
                    )
                if name == "formula":
                    page.insert_text((30, 150), "x^2 + y^2 = z^2", fontsize=16)
                if name == "table":
                    for y in (140, 170, 200, 230):
                        page.draw_line((30, y), (510, y))
                    for x in (30, 250, 510):
                        page.draw_line((x, 140), (x, 230))
                    for row, values in enumerate(
                        (
                            ("Element", "Reagent"),
                            ("Cerium", "Nitrate"),
                            ("Xenon", "Fluoride"),
                        )
                    ):
                        for column, text in enumerate(values):
                            page.insert_text(
                                (40 + column * 230, 160 + row * 30), text, fontsize=12
                            )
                if name == "figure":
                    page.draw_polyline(
                        ((60, 230), (160, 140), (260, 230), (60, 230)), color=(0, 0, 0)
                    )
                    page.insert_text(
                        (60, 260), "Figure 1. Cobalt triangle", fontsize=12
                    )
            if name == "scan" or name == "mixed":
                with fitz.open() as scan:
                    for i, page in enumerate(pdf):
                        if name == "mixed" and i == 0:
                            scan.insert_pdf(pdf, from_page=i, to_page=i)
                        else:
                            image = page.get_pixmap(matrix=fitz.Matrix(3, 3)).tobytes(
                                "png"
                            )
                            scan.new_page(width=680, height=400).insert_image(
                                fitz.Rect(0, 0, 680, 400), stream=image
                            )
                    path = directory / (name + ".pdf")
                    scan.save(path)
            else:
                path = directory / (name + ".pdf")
                pdf.save(path)
        paths[name] = path
    return paths


def evaluate(out):
    out.mkdir(parents=True, exist_ok=True)
    paths = generate(out / "fixtures")
    index = LocalRagIndex(out / "rag.sqlite3")
    canonicals, versions, reports = {}, {}, {}
    started = perf_counter()
    for name, path in paths.items():
        cfg = DeepDocConfig(
            engine="unified",
            canonical_version=2,
            document_version=f"synthetic-{name}:1",
            language="vie+eng",
        )
        doc = DeepDocService(cfg).process_pdf(path, out / name)
        canonicals[name] = doc
        versions[doc["source_sha256"]] = name
        reports[name] = {
            "chunks": index.index(doc),
            "published_blocks": len(list(iter_retrievable_blocks(doc))),
            "run": json.loads((out / name / "run_report.json").read_text()),
        }
    from idp.evidence.serde import load

    def distance(a, b):
        previous = list(range(len(b) + 1))
        for i, x in enumerate(a, 1):
            current = [i]
            for j, y in enumerate(b, 1):
                current.append(
                    min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (x != y))
                )
            previous = current
        return previous[-1]

    extraction = {}
    published = []
    truth = []
    table_f1 = None
    figures = None
    formula_text_exact = None
    for name, doc in canonicals.items():
        record = load((out / name / "extraction.json").read_text())
        expected = [f[1] for f in FACTS if f[0] == name]
        if name == "formula":
            expected.append("x^2 + y^2 = z^2")
        if name == "table":
            expected.extend(
                ("Element", "Reagent", "Cerium", "Nitrate", "Xenon", "Fluoride")
            )
        if name == "figure":
            expected.append("Figure 1. Cobalt triangle")
        actual = " ".join(
            o.text or "" for o in record.observations if o.kind.value == "TEXT"
        )
        gt = " ".join(expected)
        extraction[name] = {
            "cer": distance(gt, actual) / max(1, len(gt)),
            "wer": distance(gt.split(), actual.split()) / max(1, len(gt.split())),
            "ground_truth": "synthetic source draw commands",
            "source_units_found_in_order": all(t in actual for t in expected)
            and [actual.find(t) for t in expected]
            == sorted(actual.find(t) for t in expected),
        }
        if name == "formula":
            formula_text_exact = "x^2 + y^2 = z^2" in actual
        if name == "figure":
            captions = [
                ref["text"]
                for r in doc["structures"]["regions"]
                if r["kind"] == "figure"
                for ref in r.get("caption_references", [])
            ]
            figures = {
                "expected_associations": 1,
                "correct_associations": sum(
                    t == "Figure 1. Cobalt triangle" for t in captions
                ),
                "predicted_associations": len(captions),
            }
        truth.extend((name, " ".join(t.split())) for t in expected)
        published.extend(
            (name, " ".join(b["text"].split())) for b in iter_retrievable_blocks(doc)
        )
        if name == "table":
            wanted = {
                (r, c, t)
                for r, row in enumerate(
                    (
                        ("Element", "Reagent"),
                        ("Cerium", "Nitrate"),
                        ("Xenon", "Fluoride"),
                    )
                )
                for c, t in enumerate(row)
            }
            predicted = set()
            for region in doc["structures"]["regions"]:
                if (
                    region.get("kind") == "table"
                    and region.get("origin") == "native_structure"
                ):
                    predicted.update(
                        (cell["row"], cell["column"], cell["text"])
                        for cell in region["content"]["cells"]
                    )
            common = len(wanted & predicted)
            precision = common / max(1, len(predicted))
            recall = common / len(wanted)
            table_f1 = {
                "cell_precision": precision,
                "cell_recall": recall,
                "cell_f1": 2 * precision * recall / max(1e-12, precision + recall),
                "cells_expected": len(wanted),
                "cells_predicted": len(predicted),
            }
    true_set = set(truth)
    pub_set = set(published)
    truth_tokens = Counter(
        (name, token) for name, text in truth for token in terms(text)
    )
    pub_tokens = Counter(
        (name, token) for name, text in published for token in terms(text)
    )
    covered = sum((truth_tokens & pub_tokens).values())
    publication_metrics = {
        "token_precision": covered / max(1, sum(pub_tokens.values())),
        "token_recall": covered / max(1, sum(truth_tokens.values())),
        "missing_source_tokens": sum((truth_tokens - pub_tokens).values()),
        "unsupported_or_repeated_tokens": sum((pub_tokens - truth_tokens).values()),
        "exact_segmentation_match_precision": len(pub_set & true_set)
        / max(1, len(pub_set)),
        "exact_segmentation_match_recall": len(pub_set & true_set)
        / max(1, len(true_set)),
        "source_units_with_missing_tokens": sum(
            bool(
                Counter(terms(text))
                - Counter(
                    token for n, t in published if n == name for token in terms(t)
                )
            )
            for name, text in truth
        ),
        "duplicate_exact_unit_rate": (len(published) - len(pub_set))
        / max(1, len(published)),
    }
    relevant1, relevant5, mrr, citation_total, citation_ok = 0, 0, 0, 0, 0
    results = []
    for name, ground_truth, query, page in FACTS:
        hits = index.retrieve(
            query,
            actor="synthetic-reader",
            access_check=lambda actor, source, version: source in versions,
            top_k=5,
        )
        rank = next(
            (
                i
                for i, h in enumerate(hits, 1)
                if h["original_source_sha256"] == canonicals[name]["source_sha256"]
                and any(r["page"] == page for r in h["references"])
            ),
            None,
        )
        relevant1 += rank == 1
        relevant5 += rank is not None
        mrr += 1 / rank if rank else 0
        for hit in hits:
            citation_total += 1
            source = canonicals[versions[hit["original_source_sha256"]]]
            citation_ok += bool(resolve_citation(hit, source))
        results.append(
            {"fixture": name, "query": query, "expected_page": page, "rank": rank}
        )
    denied = index.retrieve(
        "cobalt zeolite", actor="denied", access_check=lambda *a: False, top_k=5
    )
    result = {
        "schema": "deepdoc-phase4-eval:1",
        "questions": len(FACTS),
        "documents": len(paths),
        "ground_truth": "explicit synthetic FACTS and source page assignments in tests/evaluate_phase4.py",
        "recall_at_1": relevant1 / len(FACTS),
        "recall_at_5": relevant5 / len(FACTS),
        "mrr": mrr / len(FACTS),
        "citation_correctness": citation_ok / max(1, citation_total),
        "source_attribution_coverage": citation_ok / max(1, citation_total),
        "unauthorized_hits": len(denied),
        "publication": reports,
        "extraction_metrics": extraction,
        "table_metrics": table_f1,
        "figure_caption_metrics": figures,
        "native_ascii_formula_text_exact": formula_text_exact,
        "advanced_formula_accuracy": "measured separately by model execution report; not inferred from native ASCII text",
        "publication_metrics": publication_metrics,
        "results": results,
        "seconds": perf_counter() - started,
        "qas_06": "NOT CLAIMED: small synthetic evaluation set",
        "real_book_corpus": "NOT AVAILABLE",
        "table_teds": "NOT MEASURED",
        "peak_memory": "NOT MEASURED",
    }
    (out / "evaluation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    result = evaluate(parser.parse_args().out)
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "questions",
                    "documents",
                    "recall_at_1",
                    "recall_at_5",
                    "mrr",
                    "citation_correctness",
                    "unauthorized_hits",
                )
            }
        )
    )
