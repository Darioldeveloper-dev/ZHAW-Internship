import os
import time
import requests
from flask import Flask, request, jsonify
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor

# --- Tracing setup ---
provider = TracerProvider()
provider.add_span_processor(BatchSpanProcessor(
    JaegerExporter(
        agent_host_name=os.getenv("JAEGER_HOST", "localhost"),
        agent_port=int(os.getenv("JAEGER_PORT", 6831))
    )
))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("main_service")

# --- App ---
app = Flask(__name__)
FlaskInstrumentor().instrument_app(app)
RequestsInstrumentor().instrument()

# --- Config from environment ---
OLLAMA_URL   = os.getenv("OLLAMA_URL",   "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
STATS_URL    = os.getenv("STATS_URL",    "http://localhost:5001/log")

def ask_ollama(description: str) -> str:
    with tracer.start_as_current_span("ollama-inference") as span:
        span.set_attribute("ollama.model",       OLLAMA_MODEL)
        span.set_attribute("input.description",  description)

        payload = {
            "model" : OLLAMA_MODEL,
            "prompt": (
                f"A user described something as: '{description}'. "
                "In one word, what is the most likely subject or object? "
                "Reply with only a single word, no punctuation, no explanation."
            ),
            "stream": False
        }

        resp = requests.post(OLLAMA_URL, json=payload, timeout=60)
        resp.raise_for_status()

        guess = resp.json().get("response", "").strip().strip(".").lower()
        span.set_attribute("ollama.guess", guess)
        return guess

@app.route('/guess', methods=['POST'])
def guess():
    with tracer.start_as_current_span("handle-guess"):
        t_total_start = time.time()

        data        = request.get_json()
        description = data.get('description', '').strip()

        if not description:
            return jsonify({'error': 'description field is required'}), 400

        # Step 1 — ask the LLM
        t_llm_start = time.time()
        guess_word  = ask_ollama(description)
        t_llm_ms    = round((time.time() - t_llm_start) * 1000)

        # Step 2 — send to stats service
        t_stats_start = time.time()
        stats_resp    = requests.post(STATS_URL, json={'guess': guess_word}, timeout=5)
        stats         = stats_resp.json()
        t_stats_ms    = round((time.time() - t_stats_start) * 1000)

        t_total_ms = round((time.time() - t_total_start) * 1000)

        return jsonify({
            'description': description,
            'guess'      : guess_word,
            'stats'      : stats,
            'timings_ms' : {
                'llm'          : t_llm_ms,
                'stats_service': t_stats_ms,
                'total'        : t_total_ms
            }
        })

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'service': 'main_service'})

if __name__ == '__main__':
    port = int(os.getenv("MAIN_PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=os.getenv("DEBUG", "true").lower() == "true")