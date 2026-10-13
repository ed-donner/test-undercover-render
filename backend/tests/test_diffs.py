from backend.diffs import diff

LINES = [f"Line {n}" for n in range(1, 21)]


def text(lines):
    return "\n".join(lines)


def shown(result):
    return [[(line.kind, line.text) for line in hunk] for hunk in result.hunks]


def test_one_changed_line_has_two_lines_of_context_either_side():
    changed = LINES[:9] + ["Line ten"] + LINES[10:]
    result = diff(text(LINES), text(changed))
    assert shown(result) == [
        [
            ("context", "Line 8"),
            ("context", "Line 9"),
            ("removed", "Line 10"),
            ("added", "Line ten"),
            ("context", "Line 11"),
            ("context", "Line 12"),
        ]
    ]
    assert (result.added, result.removed) == (1, 1)


def test_two_changes_far_apart_are_two_hunks():
    changed = ["Line one", *LINES[1:18], "Line nineteen", "Line 20", "Line 21"]
    result = diff(text(LINES), text(changed))
    assert len(result.hunks) == 2
    assert (result.added, result.removed) == (3, 2)
    assert shown(result)[1][-1] == ("added", "Line 21")


def test_the_same_text_has_no_lines():
    result = diff(text(LINES), text(LINES))
    assert (result.hunks, result.added, result.removed) == ([], 0, 0)


def test_a_line_that_looks_like_a_header_is_still_a_line():
    result = diff("--- a rule\nkept", "kept")
    assert shown(result) == [[("removed", "--- a rule"), ("context", "kept")]]
