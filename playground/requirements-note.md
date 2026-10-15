# Playground — how to run

The Streamlit playground is an optional dev/demo tool (plan §14). It is not
installed with the base package and needs no API keys for the offline demo.

```bash
uv sync --extra playground
uv run streamlit run playground/app.py
```

Light up a real provider adapter once it exists (M3/M7) by adding its extra,
e.g.:

```bash
uv sync --extra playground --extra gemini
```

Provider credentials come from environment variables only
(`GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `TWELVELABS_API_KEY`). The UI shows
whether each is set — never its value — and values never appear in logs,
error messages, or exported JSON.
