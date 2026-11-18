"""Corpus loading and a transparent lexical (BM25) retrieval baseline.

No embeddings or vector database: add them only if this baseline fails measured retrieval cases.
"""
import json
import math
import re
from collections import Counter
from pathlib import Path

from app.retrieval.chunker import chunk_id, chunk_markdown
from app.retrieval.models import Manifest
from app.schemas.domain import DocumentChunk, DocumentSourceKind

DOCS_DIR = Path(__file__).resolve().parents[2] / "data" / "docs"

_STOPWORDS = frozenset(
    "a an and are as at be but by for from has have how i if in into is it its of on or "
    "that the their then there these this to was were what when which while will with you your "
    "do does not no can should would could than so such also any all".split()
)
_TOKEN = re.compile(r"[a-z0-9]+")
K1, B = 1.5, 0.75
MIN_SCORE = 1.0


class CorpusError(ValueError):
    """The corpus manifest or a document is invalid."""


def tokenize(text: str) -> list[str]:
    """Lowercase, split on non-alphanumerics (so kv_cache_used_pct -> kv cache used pct),
    drop stopwords, and fold simple plurals."""
    out = []
    for tok in _TOKEN.findall(text.lower()):
        if tok in _STOPWORDS:
            continue
        if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
            tok = tok[:-1]
        out.append(tok)
    return out


class DocumentIndex:
    def __init__(self, chunks: list[DocumentChunk]):
        ids = [c.id for c in chunks]
        if len(set(ids)) != len(ids):
            raise CorpusError("duplicate chunk IDs in corpus")
        self._chunks = {c.id: c for c in chunks}
        self._order = sorted(self._chunks)  # deterministic iteration
        self._tf: dict[str, Counter] = {}
        for cid in self._order:
            c = self._chunks[cid]
            self._tf[cid] = Counter(tokenize(f"{c.section} {c.text}"))
        self._len = {cid: sum(tf.values()) for cid, tf in self._tf.items()}
        self._avg_len = (sum(self._len.values()) / len(self._len)) if self._len else 0.0
        df: Counter = Counter()
        for tf in self._tf.values():
            df.update(tf.keys())
        n = len(self._chunks)
        self._idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    @property
    def chunks(self) -> list[DocumentChunk]:
        return [self._chunks[c] for c in self._order]

    def get_chunk(self, chunk_id_: str) -> DocumentChunk | None:
        return self._chunks.get(chunk_id_)

    def resolve_citations(self, ids: list[str]) -> tuple[list[DocumentChunk], list[str]]:
        """Split citation IDs into (resolved chunks, unknown IDs). Unknown IDs must be rejected."""
        found = [self._chunks[i] for i in ids if i in self._chunks]
        unknown = [i for i in ids if i not in self._chunks]
        return found, unknown

    def search(
        self, query: str, top_k: int = 5, include_superseded: bool = False
    ) -> list[tuple[DocumentChunk, float, list[str]]]:
        """Return up to top_k (chunk, score, matched_terms), best first. Empty list = no match.

        A chunk only counts if it matches at least min(2, number of distinct query terms)
        distinct terms and scores at least MIN_SCORE, so a single incidental shared word
        does not make an irrelevant document look relevant.
        """
        terms = sorted(set(tokenize(query)))
        if not terms or not self._chunks:
            return []
        need = min(2, len(terms))
        results = []
        for cid in self._order:
            chunk = self._chunks[cid]
            if chunk.status != "current" and not include_superseded:
                continue
            tf = self._tf[cid]
            matched = [t for t in terms if t in tf]
            if len(matched) < need:
                continue
            norm = K1 * (1 - B + B * self._len[cid] / self._avg_len)
            score = sum(self._idf[t] * tf[t] * (K1 + 1) / (tf[t] + norm) for t in matched)
            if score >= MIN_SCORE:
                results.append((chunk, round(score, 4), matched))
        results.sort(key=lambda r: (-r[1], r[0].id))  # ties broken by ID: fully deterministic
        return results[:top_k]


def load_corpus(docs_dir: Path = DOCS_DIR) -> DocumentIndex:
    manifest_path = docs_dir / "manifest.json"
    try:
        manifest = Manifest.model_validate(json.loads(manifest_path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        raise CorpusError(f"cannot read manifest {manifest_path}: {exc}") from exc
    root = docs_dir.resolve()
    chunks: list[DocumentChunk] = []
    for entry in manifest.documents:
        path = (root / entry.path).resolve()
        if root not in path.parents:
            raise CorpusError(f"document path escapes the docs directory: {entry.path}")
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise CorpusError(f"cannot read document {entry.path}: {exc}") from exc
        if entry.classification == DocumentSourceKind.SYNTHETIC and "SYNTHETIC" not in text[:600].upper():
            raise CorpusError(f"{entry.path} is classified synthetic but is not labelled SYNTHETIC")
        raw = chunk_markdown(text)
        if not raw:
            raise CorpusError(f"{entry.path} produced no chunks")
        for rc in raw:
            chunks.append(
                DocumentChunk(
                    id=chunk_id(entry.document_id, entry.version, rc.slug, rc.chunk_index),
                    document_id=entry.document_id,
                    version=entry.version,
                    title=entry.title,
                    section=rc.section,
                    text=rc.text,
                    source=entry.source,
                    synthetic_or_official=entry.classification,
                    date=entry.date,
                    status=entry.status,
                )
            )
    return DocumentIndex(chunks)
