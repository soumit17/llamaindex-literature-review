"""PDF clean-up and section tagging (spec §4.2)."""

from litreview.retrieval.parsing import (
    Headings,
    boilerplate_lines,
    label_for,
    merge_split_headings,
    parse_pdf,
)
from tests.fakes import make_paper_pdf


def test_fixture_pdf_is_cleaned_and_tagged(tmp_path):
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(make_paper_pdf("Agents That Coordinate", "hub"))
    paper = parse_pdf(pdf)

    text = " ".join(s.text for s in paper.segments)
    assert "Preprint" not in text  # running header dropped
    assert "orchestration" in text and "orches-" not in text  # de-hyphenated
    assert "Some cited paper" not in text and paper.references_cut_at_page == 3
    assert [s.section for s in paper.segments] == [
        "front",
        "abstract",
        "introduction",
        "method",
        "conclusion",
    ]
    assert paper.segments[2].heading == "1 Introduction" and paper.segments[2].page == 1
    assert "GPT-4 85.2" in paper.segments[3].text  # a table row is text, not "section 3"


def test_split_heading_lines_are_rejoined():
    assert merge_split_headings(["3", "METHOD", "3.1", "Roles", "4", "85.2"]) == [
        "3 METHOD",
        "3.1 Roles",
        "4",
        "85.2",
    ]


def test_heading_rules_reject_captions_tables_and_wrong_numbering():
    h = Headings()
    assert h.match("1 Introduction") == ("1 Introduction", 1)
    assert h.match("1.1 Background") == ("1.1 Background", None)  # subsection of the current section
    assert h.match("2.1 Too early") is None
    assert h.match("2 Table 1: Results") is None
    assert h.match("2 GPT-4 85.2 90.1") is None
    assert h.match("7 Way Ahead") is None  # skips too many numbers
    assert h.match("2 Our Orchestrator") == ("2 Our Orchestrator", 2)
    assert h.match("This introduction explains a lot of things in one long sentence") is None


def test_roman_numbered_paper_ignores_arabic_figure_labels():
    h = Headings()
    assert h.match("I. INTRODUCTION") == ("I. INTRODUCTION", 1)
    assert h.match("II. METHODS") == ("II. METHODS", 2)
    assert h.match("3 Role Agents") is None
    assert h.match("III. RESULTS") == ("III. RESULTS", 3)


def test_affiliation_marker_cannot_block_the_introduction():
    h = Headings()
    assert h.match("1 University of Somewhere")  # false positive on page 1...
    assert h.match("1 Introduction") == ("1 Introduction", 1)  # ...introduction still resets


def test_section_labels():
    assert label_for("METAGPT: A META-PROGRAMMING FRAMEWORK") == "method"
    assert label_for("Conclusion and Future Work") == "conclusion"
    assert label_for("Collaboration Mechanisms") == "body"


def test_boilerplate_is_lines_repeated_on_page_edges_of_3_plus_pages():
    pages = [["Preprint 2025", f"body {i}", "Page 1"] for i in range(3)]
    assert boilerplate_lines(pages) == {"preprint #", "body #", "page #"}  # digits normalized
    assert boilerplate_lines(pages[:2]) == set()  # too few pages to tell
