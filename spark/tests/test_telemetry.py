from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader


def test_caption_metrics_names_and_room_only_attrs(monkeypatch):
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    meter = provider.get_meter("test")
    import tower.telemetry as t

    monkeypatch.setattr(t, "caption_latency", meter.create_histogram("caption.latency", unit="s"))
    monkeypatch.setattr(t, "captions_total", meter.create_counter("captions.total"))
    monkeypatch.setattr(t, "captions_within_slo", meter.create_counter("captions.within_slo"))
    t.record_caption("room-a", 0.4)
    t.record_caption("room-a", 2.5)
    data = reader.get_metrics_data()
    metrics = {m.name: m for rm in data.resource_metrics for sm in rm.scope_metrics for m in sm.metrics}
    assert set(metrics) == {"caption.latency", "captions.total", "captions.within_slo"}
    assert metrics["captions.total"].data.data_points[0].value == 2
    assert metrics["captions.within_slo"].data.data_points[0].value == 1
    for m in metrics.values():
        for dp in m.data.data_points:
            assert dict(dp.attributes) == {"room": "room-a"}
