"""Stage 1: Cluster — extract and cluster snippets from search results.

This stage:
  - Pulls all SearchResult snippets from the snapshot's raw_search_results
  - Filters out non-customer text (privacy policies, cookie banners)
  - Embeds each snippet using a 1536-dim model
  - Clusters using HDBSCAN with min_cluster_size=2, min_samples=1
  - Falls back to AgglomerativeClustering if HDBSCAN produces <3 clusters
  - Returns ClusterResult with clusters and noise indices

Cold-start handling: if <8 snippets, skip clustering entirely and treat
each snippet as its own micro-cluster.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from urllib.parse import urlparse

import numpy as np
import structlog

from app.config import get_settings
from app.models import EMBEDDING_DIM, ProductSnapshot
from app.pipelines.icp._filters import (
    MINIMUM_SNIPPET_LENGTH,
    clean_snippet,
    is_customer_evidence,
)

log = structlog.get_logger()

# Minimum snippets needed for clustering to be meaningful
MIN_SNIPPETS_FOR_CLUSTERING = 8

# Minimum snippet length to be useful
MIN_SNIPPET_LENGTH = MINIMUM_SNIPPET_LENGTH


@dataclass(frozen=True, slots=True)
class SnippetSource:
    """Source information for a snippet."""

    url: str
    title: str
    source_kind: str
    published_date: str | None


@dataclass
class Cluster:
    """A single cluster of semantically similar snippets."""

    centroid_embedding: list[float]
    member_indices: list[int]
    member_snippets: list[str]
    member_sources: list[SnippetSource]


@dataclass
class ClusterResult:
    """Result of the clustering stage."""

    clusters: list[Cluster]
    noise_indices: list[int]
    total_snippets: int
    all_snippets: list[str] = field(default_factory=list)
    all_sources: list[SnippetSource] = field(default_factory=list)
    all_embeddings: list[list[float]] = field(default_factory=list)


def _is_non_customer_text(text: str) -> bool:
    """Check if text is likely non-customer content."""
    return not is_customer_evidence(text, "other")[0]


def _extract_domain(url: str) -> str:
    """Extract domain from URL for source identification."""
    try:
        parsed = urlparse(url)
        return parsed.netloc.lower().removeprefix("www.")
    except Exception:
        return url


def _extract_snippets(snapshot: ProductSnapshot) -> tuple[list[str], list[SnippetSource]]:
    """Extract snippets and sources from snapshot's raw_search_results.

    Returns:
        Tuple of (snippets, sources) where sources[i] corresponds to snippets[i].
    """
    snippets: list[str] = []
    sources: list[SnippetSource] = []

    raw_search = snapshot.raw_search_results
    if not raw_search or not isinstance(raw_search, dict):
        log.warning("icp.cluster.no_search_results", snapshot_id=str(snapshot.id))
        return snippets, sources

    results = raw_search.get("results", [])
    if not isinstance(results, list):
        log.warning("icp.cluster.invalid_results_format", snapshot_id=str(snapshot.id))
        return snippets, sources

    for result in results:
        if not isinstance(result, dict):
            continue

        raw_snippet = result.get("snippet", "")
        if not raw_snippet or not isinstance(raw_snippet, str):
            continue

        source = SnippetSource(
            url=result.get("url", ""),
            title=result.get("title", ""),
            source_kind=result.get("source_kind", "other"),
            published_date=result.get("published_date"),
        )

        snippet = clean_snippet(raw_snippet, enforce_minimum_length=True)
        if not snippet:
            log.debug("icp.cluster.filtered_non_customer", reason="too_short_or_artifact")
            continue

        is_customer, reason = is_customer_evidence(snippet, source.source_kind)
        if not is_customer:
            log.debug(
                "icp.cluster.filtered_non_customer",
                reason=reason,
                snippet=snippet[:50],
            )
            continue

        snippets.append(snippet)
        sources.append(source)

    log.info(
        "icp.cluster.extracted",
        total=len(results),
        after_filter=len(snippets),
    )

    return snippets, sources


async def _embed_snippets(snippets: list[str]) -> list[list[float]]:
    """Embed snippets using OpenAI or a deterministic fallback.

    Uses OpenAI text-embedding-3-small (1536-dim) as primary.
    Falls back to deterministic hash-based embeddings when any LLM API key
    is configured but OpenAI embeddings are unavailable. This keeps Step 3
    runnable with either OPENAI_API_KEY or ANTHROPIC_API_KEY while still
    failing loud when no provider key is configured.
    """
    settings = get_settings()

    if settings.openai_api_key:
        try:
            return await _embed_with_openai(snippets, settings.openai_api_key)
        except Exception as exc:
            log.warning(
                "icp.cluster.openai_embedding_failed",
                error=str(exc),
                message="Using hash-based embeddings",
            )
            return _hash_based_embeddings(snippets)

    if settings.anthropic_api_key:
        # Anthropic does not provide embeddings here; a deterministic fallback
        # keeps the pipeline usable when Anthropic is the configured LLM.
        log.warning(
            "icp.cluster.no_openai_key",
            message="Using hash-based embeddings",
        )
        return _hash_based_embeddings(snippets)

    raise RuntimeError(
        "No LLM provider configured. Set OPENAI_API_KEY or ANTHROPIC_API_KEY."
    )


async def _embed_with_openai(snippets: list[str], api_key: str) -> list[list[float]]:
    """Embed snippets using OpenAI API."""
    from openai import OpenAI

    def _do_embed() -> list[list[float]]:
        client = OpenAI(api_key=api_key)

        # Batch embeddings (OpenAI supports up to 2048 inputs)
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=snippets,
            dimensions=EMBEDDING_DIM,
        )

        # Sort by index to maintain order
        embeddings_data = sorted(response.data, key=lambda x: x.index)
        return [e.embedding for e in embeddings_data]

    return await asyncio.to_thread(_do_embed)


def _hash_based_embeddings(snippets: list[str]) -> list[list[float]]:
    """Generate deterministic embeddings from text hash.

    This is a fallback for testing/development when no embedding API is available.
    NOT suitable for production clustering quality.
    """
    embeddings: list[list[float]] = []

    for snippet in snippets:
        # Create a deterministic hash
        hash_bytes = hashlib.sha256(snippet.encode()).digest()

        # Expand hash to EMBEDDING_DIM dimensions
        embedding: list[float] = []
        for i in range(EMBEDDING_DIM):
            # Use rolling hash to generate more values
            idx = i % len(hash_bytes)
            val = hash_bytes[idx] + (i // len(hash_bytes))
            # Normalize to [-1, 1]
            embedding.append((val % 256) / 128.0 - 1.0)

        # Normalize the embedding
        norm = sum(x * x for x in embedding) ** 0.5
        if norm > 0:
            embedding = [x / norm for x in embedding]

        embeddings.append(embedding)

    return embeddings


def _cluster_with_hdbscan(
    embeddings: np.ndarray,
) -> tuple[list[int], int]:
    """Cluster embeddings using HDBSCAN.

    Returns:
        Tuple of (labels, n_clusters) where labels[i] is -1 for noise.
    """
    import hdbscan  # type: ignore[import-untyped]

    # Normalize embeddings - then euclidean distance is equivalent to cosine
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms = np.where(norms > 0, norms, 1.0)  # Avoid division by zero
    normalized = embeddings / norms

    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=2,
        min_samples=1,
        metric="euclidean",  # On normalized vectors, equivalent to cosine
        cluster_selection_method="eom",
    )

    labels = clusterer.fit_predict(normalized)
    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)

    return list(labels), n_clusters


def _cluster_with_agglomerative(
    embeddings: np.ndarray,
    n_clusters: int = 4,
) -> list[int]:
    """Cluster embeddings using AgglomerativeClustering as fallback."""
    from sklearn.cluster import AgglomerativeClustering  # type: ignore[import-untyped]

    # Cap clusters at number of samples
    n_clusters = min(n_clusters, len(embeddings))

    # Normalize embeddings - euclidean on normalized is equivalent to cosine
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms = np.where(norms > 0, norms, 1.0)
    normalized = embeddings / norms

    clusterer = AgglomerativeClustering(
        n_clusters=n_clusters,
        metric="euclidean",
        linkage="average",
    )

    labels = clusterer.fit_predict(normalized)
    return list(labels)


def _compute_centroid(embeddings: list[list[float]]) -> list[float]:
    """Compute the centroid of a set of embeddings."""
    if not embeddings:
        return [0.0] * EMBEDDING_DIM

    arr = np.array(embeddings)
    centroid = np.mean(arr, axis=0)

    # Normalize centroid
    norm = float(np.linalg.norm(centroid))
    if norm > 0:
        centroid = centroid / norm

    return [float(x) for x in centroid]


def _build_clusters(
    labels: list[int],
    snippets: list[str],
    sources: list[SnippetSource],
    embeddings: list[list[float]],
) -> tuple[list[Cluster], list[int]]:
    """Build Cluster objects from labels."""
    clusters: list[Cluster] = []
    noise_indices: list[int] = []

    # Group by label
    label_to_indices: dict[int, list[int]] = {}
    for idx, label in enumerate(labels):
        if label == -1:
            noise_indices.append(idx)
        else:
            if label not in label_to_indices:
                label_to_indices[label] = []
            label_to_indices[label].append(idx)

    # Build clusters
    for label in sorted(label_to_indices.keys()):
        indices = label_to_indices[label]
        cluster_embeddings = [embeddings[i] for i in indices]
        centroid = _compute_centroid(cluster_embeddings)

        cluster = Cluster(
            centroid_embedding=centroid,
            member_indices=indices,
            member_snippets=[snippets[i] for i in indices],
            member_sources=[sources[i] for i in indices],
        )
        clusters.append(cluster)

    return clusters, noise_indices


async def cluster_snippets(snapshot: ProductSnapshot) -> ClusterResult:
    """Extract and cluster snippets from a snapshot.

    Args:
        snapshot: ProductSnapshot with raw_search_results.

    Returns:
        ClusterResult with clusters and noise indices.
    """
    # Extract snippets
    snippets, sources = _extract_snippets(snapshot)

    if not snippets:
        log.info("icp.cluster.empty", snapshot_id=str(snapshot.id))
        return ClusterResult(
            clusters=[],
            noise_indices=[],
            total_snippets=0,
            all_snippets=[],
            all_sources=[],
            all_embeddings=[],
        )

    # Cold-start handling: if too few snippets, treat each as micro-cluster
    if len(snippets) < MIN_SNIPPETS_FOR_CLUSTERING:
        log.info(
            "icp.cluster.cold_start",
            snapshot_id=str(snapshot.id),
            n_snippets=len(snippets),
        )

        # Embed for downstream use
        embeddings = await _embed_snippets(snippets)

        # Each snippet is its own micro-cluster
        clusters: list[Cluster] = []
        for i, (snippet, source, embedding) in enumerate(
            zip(snippets, sources, embeddings, strict=True)
        ):
            cluster = Cluster(
                centroid_embedding=embedding,
                member_indices=[i],
                member_snippets=[snippet],
                member_sources=[source],
            )
            clusters.append(cluster)

        return ClusterResult(
            clusters=clusters,
            noise_indices=[],
            total_snippets=len(snippets),
            all_snippets=snippets,
            all_sources=sources,
            all_embeddings=embeddings,
        )

    # Embed snippets
    embeddings = await _embed_snippets(snippets)
    embeddings_array = np.array(embeddings)

    # Try HDBSCAN first
    labels, n_clusters = _cluster_with_hdbscan(embeddings_array)

    # Fallback to AgglomerativeClustering if HDBSCAN fails
    if n_clusters < 3:
        log.info(
            "icp.cluster.hdbscan_fallback",
            snapshot_id=str(snapshot.id),
            hdbscan_clusters=n_clusters,
        )
        labels = _cluster_with_agglomerative(embeddings_array, n_clusters=4)

    # Build cluster objects
    clusters, noise_indices = _build_clusters(labels, snippets, sources, embeddings)

    # Sort clusters by size (descending) for downstream processing
    clusters.sort(key=lambda c: len(c.member_indices), reverse=True)

    log.info(
        "icp.cluster.done",
        snapshot_id=str(snapshot.id),
        n_clusters=len(clusters),
        n_noise=len(noise_indices),
        cluster_sizes=[len(c.member_indices) for c in clusters],
    )

    return ClusterResult(
        clusters=clusters,
        noise_indices=noise_indices,
        total_snippets=len(snippets),
        all_snippets=snippets,
        all_sources=sources,
        all_embeddings=embeddings,
    )
