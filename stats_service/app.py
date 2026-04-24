import os
import datetime
from collections import Counter
from flask import Flask, request, jsonify
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor

# --- Tracing setup ---
provider = TracerProvider()
provider.add_span_processor(BatchSpanProcessor(
    JaegerExporter(
        agent_host_name=os.getenv("JAEGER_HOST", "localhost"),
        agent_port=int(os.getenv("JAEGER_PORT", 6831))
    )
))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("stats_service")

# --- App ---
app = Flask(__name__)
FlaskInstrumentor().instrument_app(app)

log     = []
counts  = Counter()

@app.route('/log', methods=['POST'])
def log_guess():
    with tracer.start_as_current_span("log-and-count"):
        data  = request.get_json()
        guess = data.get('guess', '').strip().strip('.').lower()

        if guess:
            log.append({
                'guess': guess,
                'ts': datetime.datetime.utcnow().isoformat()
            })
            counts[guess] += 1

        return jsonify({
            'total'      : len(log),
            'top5'       : counts.most_common(5),
            'all_counts' : dict(counts)
        })

@app.route('/stats', methods=['GET'])
def get_stats():
    with tracer.start_as_current_span("get-stats"):
        return jsonify({
            'total' : len(log),
            'top5'  : counts.most_common(5),
            'all_counts': dict(counts)
        })

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'service': 'stats_service'})

if __name__ == '__main__':
    port = int(os.getenv("STATS_PORT", 5001))
    app.run(host='0.0.0.0', port=port, debug=os.getenv("DEBUG", "true").lower() == "true")