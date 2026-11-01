"""Deterministic citation handling (bib.py) and the custom RetryAfterPolicy (retry.py)."""

from types import SimpleNamespace

from litreview.bib import (
    Numbering,
    author_list,
    bibtex,
    reference_line,
    strip_unknown_markers,
    used_claim_ids,
)
from litreview.corpus import PaperMeta
from litreview.models import Citation, FindingClaim
from litreview.retry import LLM_RETRY, RetryAfterPolicy, retry_after_seconds


def claim(claim_id: str, arxiv_id: str, page: int, node: str) -> FindingClaim:
    return FindingClaim(
        claim_id=claim_id,
        statement=f"s{claim_id}",
        citation=Citation(arxiv_id=arxiv_id, node_id=node, page=page, quote="q"),
    )


CLAIMS = {
    "1.1": claim("1.1", "A", 3, "n1"),
    "1.2": claim("1.2", "A", 3, "n2"),  # same paper and page as 1.1 -> same number
    "2.1": claim("2.1", "B", 7, "n3"),
}


def test_numbers_follow_first_appearance_one_per_paper_page():
    n = Numbering(CLAIMS)
    first = n.renumber("Later idea [2.1]. Earlier idea [1.1].")
    second = n.renumber("Again [1.2; 2.1] and [1.1,1.2].")
    assert first == "Later idea [1]. Earlier idea [2]."
    assert second == "Again [1, 2] and [2]."
    assert [r.node_ids for r in sorted(n.refs.values(), key=lambda r: r.number)] == [["n3"], ["n1", "n2"]]


def test_unknown_claims_are_dropped_and_counted():
    n = Numbering(CLAIMS)
    assert n.renumber("Invented [7.7]. Mixed [7.7, 2.1].") == "Invented. Mixed [1]."
    assert n.unknown == 2


def test_writer_may_only_keep_markers_it_was_given():
    text, dropped = strip_unknown_markers("x [1.1, 2.1] y [3.3]", known={"1.1"})
    assert (text, dropped) == ("x [1.1] y ", 2)
    assert used_claim_ids("a [1.1] b [2.1; 1.2]") == {"1.1", "2.1", "1.2"}


def paper(**kw) -> PaperMeta:
    base = dict(
        arxiv_id="2308.00352",
        version=7,
        title="MetaGPT: Meta Programming & More",
        authors=["Sirui Hong", "Mingchen Zhuge", "Jürgen Schmidhuber"],
        year=2023,
        published="2023-08-01",
        abstract="a",
        categories=["cs.AI"],
        primary_category="cs.AI",
        abs_url="https://arxiv.org/abs/2308.00352v7",
    )
    return PaperMeta(**{**base, **kw})


def test_reference_line_and_authors():
    n = Numbering({"1.1": claim("1.1", "2308.00352", 4, "n")})
    n.renumber("[1.1]")
    ref = next(iter(n.refs.values()))
    assert (
        reference_line(ref, paper())
        == "[1] Hong et al. (2023). MetaGPT: Meta Programming & More. arXiv:2308.00352, p. 4"
    )
    assert author_list(["Ada Lovelace", "Alan Turing"]) == "Lovelace and Turing"


def test_bibtex_escapes_and_dedupes_keys():
    out = bibtex([paper(), paper(arxiv_id="2308.99999", title="MetaGPT again")])
    assert "@misc{hong2023metagpt," in out and "@misc{hong2023metagpta," in out
    assert r"Meta Programming \& More" in out
    assert "eprint = {2308.00352}" in out and "archivePrefix = {arXiv}" in out


class Fixed:
    def __init__(self, delay):
        self.delay = delay

    def next(self, elapsed_time, attempts, error, *, seed=None):
        return self.delay


def rate_limited(headers: dict) -> Exception:
    error = RuntimeError("429")
    error.response = SimpleNamespace(headers=headers)  # type: ignore[attr-defined]
    return error


def test_retry_after_header_wins_but_is_capped():
    policy = RetryAfterPolicy(Fixed(2.0), max_wait=60)
    assert policy.next(0, 1, rate_limited({"retry-after": "7"})) == 7.0
    assert policy.next(0, 1, rate_limited({"retry-after-ms": "1500"})) == 1.5
    assert policy.next(0, 1, rate_limited({"retry-after": "600"})) == 60
    assert policy.next(0, 1, rate_limited({})) == 2.0  # no header: fallback's wait
    assert policy.next(0, 1, rate_limited({"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"})) == 2.0


def test_fallback_still_decides_whether_to_retry():
    assert RetryAfterPolicy(Fixed(None)).next(0, 1, rate_limited({"retry-after": "5"})) is None
    assert retry_after_seconds(ValueError("no response")) is None


def test_llm_retry_matches_structured_failures_only():
    # Delays are scaled to 0 in tests; "0.0" means "retry", None means "give up".
    assert LLM_RETRY.next(0, 1, ValueError("Structured output extraction failed: bad")) == 0.0
    assert LLM_RETRY.next(0, 1, ValueError("something else")) is None
    assert LLM_RETRY.next(0, 4, ValueError("Structured output extraction failed: bad")) is None  # 4 attempts


def test_shared_policies_pickle_by_name():
    """The DBOS runtime pickles run configuration; the built-in conditions alone would not pickle."""
    import pickle

    from litreview.retry import FETCH_RETRY

    for policy in (LLM_RETRY, FETCH_RETRY):
        assert pickle.loads(pickle.dumps(policy)) is policy
