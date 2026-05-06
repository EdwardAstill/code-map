"""PageRank over the file-import graph. Render-only ordering signal."""
from __future__ import annotations


def compute_pagerank(*, files: list[str], import_edges: list[tuple[str, str]]) -> dict[str, float]:
    """Return {file_path -> pagerank_score}.

    Single-file or no-edge cases return uniform 1.0. Edge weights are 1.0
    each. The graph is directed: importer -> imported. Edges referencing
    nodes outside `files` are dropped to keep the result keyed by `files`.

    Implementation: pure-Python power iteration. Avoids the scipy/numpy path
    in `nx.pagerank` so the dependency footprint stays small.
    """
    if not files:
        return {}
    file_set = set(files)
    edges = [(s, t) for s, t in import_edges if s in file_set and t in file_set]
    if len(files) == 1 or not edges:
        return {f: 1.0 for f in files}

    n = len(files)
    damping = 0.85
    tol = 1e-6
    max_iter = 100

    out_neighbours: dict[str, list[str]] = {f: [] for f in files}
    for src, tgt in edges:
        out_neighbours[src].append(tgt)

    rank = {f: 1.0 / n for f in files}
    for _ in range(max_iter):
        new_rank = {f: (1.0 - damping) / n for f in files}
        dangling_sum = 0.0
        for f, score in rank.items():
            outs = out_neighbours[f]
            if not outs:
                dangling_sum += score
            else:
                share = damping * score / len(outs)
                for t in outs:
                    new_rank[t] += share
        if dangling_sum:
            share = damping * dangling_sum / n
            for f in new_rank:
                new_rank[f] += share
        delta = sum(abs(new_rank[f] - rank[f]) for f in files)
        rank = new_rank
        if delta < tol:
            break
    return rank
