from tower.chunker import SAMPLE_RATE, Windower, merge_overlap


def test_windower_hops_one_second():
    w = Windower(1.5, 0.5)
    one_sec = b"\x00\x00" * SAMPLE_RATE
    out = []
    for _ in range(4):
        out.extend(w.feed(one_sec))
    starts = [round(t0, 2) for _, t0, _ in out]
    ends = [round(t1, 2) for _, _, t1 in out]
    assert starts == [0.0, 1.0, 2.0]
    assert ends == [1.5, 2.5, 3.5]
    assert all(len(b) == int(1.5 * SAMPLE_RATE) * 2 for b, _, _ in out)


def test_merge_drops_repeated_words():
    assert merge_overlap("Welcome to the observability", "Observability track. Today") == "track. Today"
    assert merge_overlap("we will talk about", "talk about OpenTelemetry") == "OpenTelemetry"


def test_merge_keeps_new_text_without_overlap():
    assert merge_overlap("hello there", "general kenobi") == "general kenobi"
    assert merge_overlap("", "first words") == "first words"
