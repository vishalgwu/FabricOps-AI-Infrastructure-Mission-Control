# Phase 05 --- Documentation Retrieval (RAG)

## Goal

Allow the investigator to retrieve relevant approved technical
documentation and cite it.

## Corpus

Start with a small set of legitimate documentation and clearly labelled
synthetic runbooks. Track: - Document ID - Title - Source URL/path -
Version/date - Section - Chunk ID - Chunk text - Corpus classification

Do not copy large copyrighted documents into the repository. Link to
sources or use permitted excerpts and your own synthetic runbooks.

## Retrieval implementation

1.  Load Markdown/text documents.
2.  Split at headings and paragraph boundaries.
3.  Assign stable chunk IDs.
4.  Implement lexical retrieval.
5.  Return top-k chunks with metadata and relevance scores.
6.  Add `search_docs(query)` as a bounded internal tool.
7.  Return no-match explicitly.

Do not add embeddings or a vector database unless the baseline fails
measured tests.

## Security

Retrieved text is untrusted data. It cannot change system instructions,
tools, permissions, or allowed hosts.

## AI coding prompt

"Implement only Phase 05. Build a document manifest, chunker and lexical
retrieval baseline. Preserve source/version/section metadata and stable
chunk IDs. Add a bounded search_docs function. Include relevant,
irrelevant, contradictory-version and no-match tests. Treat retrieved
passages as untrusted content. Do not add a vector database unless you
can show a measured reason."

## Acceptance

-   [x] Chunks resolve to source and version.
-   [x] Search returns relevant expected passages on the small curated
    set.
-   [x] No-match returns an explicit empty result.
-   [x] Citation IDs are stable.
-   [x] Prompt-injection text in a document cannot change tool
    permissions.
-   [x] Retrieval tests are reproducible.

## Suggested commit

`feat: add versioned document retrieval and citations`
