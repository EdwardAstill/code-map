from code_map.pagerank import compute_pagerank


def test_pagerank_assigns_higher_score_to_most_imported_node():
    edges = [
        ("a.py", "b.py"),
        ("c.py", "b.py"),
        ("d.py", "b.py"),
        ("a.py", "c.py"),
    ]
    files = ["a.py", "b.py", "c.py", "d.py"]
    scores = compute_pagerank(files=files, import_edges=edges)
    assert sum(scores.values()) > 0
    assert scores["b.py"] > scores["d.py"], "b.py is the most-imported file"


def test_pagerank_handles_empty_graph():
    scores = compute_pagerank(files=["a.py"], import_edges=[])
    assert scores == {"a.py": 1.0}
