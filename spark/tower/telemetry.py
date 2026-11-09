"""OpenTelemetry instruments for tower-core.

Providers/exporters come from `opentelemetry-instrument` + OTEL_* env (Dash0). Without it these are
no-ops, so tests and local runs work unchanged.

Privacy: attributes are room / talk_id / sizes / durations only. Never caption text.
"""

from opentelemetry import metrics, trace

SLO_SECONDS = 2.0

tracer = trace.get_tracer("tower-core")
meter = metrics.get_meter("tower-core")

caption_latency = meter.create_histogram(
    "caption.latency",
    unit="s",
    description="Audio window end to caption broadcast",
    explicit_bucket_boundaries_advisory=[0.05, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0],
)
captions_total = meter.create_counter("captions.total", description="Captions broadcast")
captions_within_slo = meter.create_counter(
    "captions.within_slo", description=f"Captions broadcast within {SLO_SECONDS} s"
)


def record_caption(room: str, latency_s: float) -> None:
    attrs = {"room": room}
    caption_latency.record(latency_s, attrs)
    captions_total.add(1, attrs)
    if latency_s <= SLO_SECONDS:
        captions_within_slo.add(1, attrs)
