"""Suvix local playground — schema-guided video data extraction.

Developer and demo tool (plan §14), not a production interface: no accounts,
no database, no history, no persistence. Uses ONLY the public ``suvix`` API
(``Suvix``, ``ExtractionOptions``, ``SuvixError``) plus the public adapter
surface (``suvix.adapters.fake``; ``suvix.adapters.base`` for typing).

Real provider adapters (``suvix.adapters.gemini`` etc., M3/M7) are probed
lazily: the UI degrades gracefully while they are not installed and lights
them up without code changes when they land.

Run::

    uv sync --extra playground
    uv run streamlit run playground/app.py
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import streamlit as st

from suvix import ExtractionOptions, Suvix, SuvixError
from suvix.adapters.base import VideoExtractor
from suvix.adapters.fake import FakeExtractor

MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MB bound for local demo uploads.

PROVIDERS = ("fake", "gemini", "openrouter", "twelvelabs")

CREDENTIAL_ENV_VARS = (
    ("gemini", "GEMINI_API_KEY"),
    ("openrouter", "OPENROUTER_API_KEY"),
    ("twelvelabs", "TWELVELABS_API_KEY"),
)

DEFAULT_INSTRUCTIONS = (
    "List the notable events visible in the video, in chronological order."
)

DEFAULT_SCHEMA = json.dumps(
    {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "timestamp_seconds": {"type": "number"},
                    },
                    "required": ["label"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["events"],
        "additionalProperties": False,
    },
    indent=2,
)


def _probe_provider(provider: str) -> tuple[str, type[VideoExtractor] | None]:
    """Probe ``suvix.adapters.<provider>``; return (status, extractor class).

    Status is ``"ok"``, ``"not installed"``, or ``"no extractor class"``.
    The adapter modules land in M3/M7; until then every real provider reports
    "not installed" and the UI degrades gracefully instead of pretending.
    """
    try:
        module = importlib.import_module(f"suvix.adapters.{provider}")
    except ImportError:
        return "not installed", None
    candidates = [
        obj
        for name, obj in vars(module).items()
        if not name.startswith("_")
        and inspect.isclass(obj)
        and hasattr(obj, "extract")
        and isinstance(vars(obj).get("capabilities"), property)
        and isinstance(vars(obj).get("name"), property)
    ]
    if len(candidates) == 1:
        return "ok", candidates[0]
    return "no extractor class", None


PROVIDER_STATUS: dict[str, tuple[str, type[VideoExtractor] | None]] = {
    provider: ("ok", None) if provider == "fake" else _probe_provider(provider)
    for provider in PROVIDERS
}


def _provider_label(provider: str) -> str:
    if provider == "fake":
        return "fake (offline demo)"
    status, _ = PROVIDER_STATUS[provider]
    return provider if status == "ok" else f"{provider} ({status})"


def _fake_demo_script() -> list[dict[str, Any]]:
    """Scripted offline output matching DEFAULT_SCHEMA (the demo green path)."""
    return [
        {
            "data": {
                "events": [
                    {"label": "demo_event", "timestamp_seconds": 1.5},
                    {"label": "demo_event", "timestamp_seconds": 7.25},
                ]
            },
            "evidence": [
                {
                    "ref_type": "description",
                    "note": (
                        "Scripted offline demo output from the fake adapter — "
                        "not a real provider result."
                    ),
                }
            ],
            "usage": {"provider_requests": 1},
        }
    ]


def _build_extractor(provider: str, model: str) -> VideoExtractor:
    """Instantiate the chosen adapter. Raises SuvixError if unavailable."""
    if provider == "fake":
        return FakeExtractor(script=_fake_demo_script())
    status, cls = PROVIDER_STATUS[provider]
    if status != "ok" or cls is None:
        raise SuvixError(
            f"Provider '{provider}' is {status}; install its extra to use it."
        )
    # Convention for future adapters: construct with no args, or with
    # ``model=`` when the constructor accepts it. Never invent credentials.
    model = model.strip()
    try:
        accepts_model = "model" in inspect.signature(cls).parameters
    except (TypeError, ValueError):
        accepts_model = False
    if accepts_model:
        return cls(model=model) if model else cls()
    return cls()


def _parse_schema(text: str) -> tuple[dict[str, Any] | None, str | None]:
    """Client-side JSON check; full Draft 2020-12 validation runs in the library."""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"{exc.msg} (line {exc.lineno}, column {exc.colno})"
    if not isinstance(parsed, dict):
        return None, "the schema must be a JSON object"
    return parsed, None


def _session_tmpdir() -> Path:
    """Session-scoped temp dir for the uploaded video (cleaned up per run)."""
    if "suvix_tmpdir" not in st.session_state:
        st.session_state["suvix_tmpdir"] = tempfile.mkdtemp(prefix="suvix-playground-")
    return Path(st.session_state["suvix_tmpdir"])


def _cell(value: Any) -> str:
    """Display cell: never None, always a plain string (Arrow-friendly).

    Mixed-type columns make Streamlit fall back to a slow, warning-emitting
    serialization path; uniform strings avoid it.
    """

    return "—" if value is None else str(value)


st.set_page_config(page_title="Suvix playground", layout="wide")
st.title("Suvix playground")
st.caption(
    "Local dev/demo tool for schema-guided video extraction (plan §14). "
    "No accounts, no database, no history — results live only in this session."
)

input_col, config_col = st.columns(2)

with input_col:
    st.subheader("Input")
    uploaded = st.file_uploader(
        "Video file",
        type=["mp4", "mov", "mkv"],
        help="Selecting a file never calls a provider. The upload is saved to a "
        "temp file only when you press 'Run extraction'.",
    )
    instructions = st.text_area(
        "Instructions",
        value=DEFAULT_INSTRUCTIONS,
        help="What to extract. Kept separate from untrusted content in the video.",
    )
    schema_text = st.text_area("JSON Schema", value=DEFAULT_SCHEMA, height=320)
    schema, schema_error = _parse_schema(schema_text)
    if schema_error:
        st.error(f"Schema is not valid JSON: {schema_error}")
    else:
        st.caption("Valid JSON. Full Draft 2020-12 validation runs in the library.")

with config_col:
    st.subheader("Provider & strategy")
    provider = st.radio(
        "Provider",
        options=list(PROVIDERS),
        format_func=_provider_label,
        help="'fake' works offline. Real providers appear once their adapter "
        "module is installed (M3/M7).",
    )
    status, _ = PROVIDER_STATUS[provider]
    if provider != "fake" and status != "ok":
        st.warning(
            f"Provider '{provider}' is {status} — install its extra to use it."
        )
    if provider == "fake":
        st.text_input(
            "Model",
            value="fake-1 (ignored)",
            disabled=True,
            help="The fake adapter ignores the model.",
        )
        model = ""
    else:
        model = st.text_input(
            "Model",
            value="",
            placeholder="adapter default",
            help="Leave empty for the adapter default.",
        )
    strategy = st.radio(
        "Strategy",
        options=["auto", "native_video", "selected_frames"],
        format_func=lambda s: s + (" (not implemented until M5)" if s == "selected_frames" else ""),
        help="auto lets the library pick from the adapter's capabilities.",
    )
    st.caption(
        "`selected_frames` needs the media layer + coarse-to-fine workflow "
        "(Milestone 5) — it is listed but not runnable yet."
    )

    st.subheader("Bounded options")
    max_frames = st.slider("Max frames", min_value=1, max_value=32, value=8)
    max_recovery_attempts = st.slider(
        "Max recovery attempts", min_value=0, max_value=5, value=2
    )
    per_call_timeout = st.number_input(
        "Per-call timeout (seconds)",
        min_value=5.0,
        max_value=600.0,
        value=120.0,
        step=5.0,
    )

    st.subheader("Credentials (environment only)")
    for _provider, env_var in CREDENTIAL_ENV_VARS:
        state = "set" if os.environ.get(env_var) else "not set"
        st.write(f"`{env_var}`: **{state}**")
    st.caption(
        "Values are never displayed, logged, or included in exports. "
        "The fake adapter needs no credentials."
    )

st.divider()
st.info(
    f"Ready to run — provider: **{_provider_label(provider)}**, "
    f"model: **{model.strip() or 'adapter default'}**, strategy: **{strategy}**. "
    "Pressing 'Run extraction' makes the first provider call."
)

if st.button("Run extraction", type="primary"):
    if uploaded is None:
        st.session_state["last_error"] = (
            "Upload a video first — selecting a file never calls a provider by itself."
        )
        st.session_state["last_result"] = None
    elif schema_error is not None:
        st.session_state["last_error"] = f"Schema is not valid JSON: {schema_error}"
        st.session_state["last_result"] = None
    elif provider != "fake" and PROVIDER_STATUS[provider][0] != "ok":
        st.session_state["last_error"] = (
            f"Provider '{provider}' is {PROVIDER_STATUS[provider][0]}; "
            "install its extra to use it."
        )
        st.session_state["last_result"] = None
    elif strategy == "selected_frames":
        st.session_state["last_error"] = (
            "Strategy 'selected_frames' is not implemented yet (Milestone 5: "
            "selected-frame extraction + coarse-to-fine workflow). Suvix will "
            "not silently fall back to another strategy."
        )
        st.session_state["last_result"] = None
    elif uploaded.size > MAX_UPLOAD_BYTES:
        st.session_state["last_error"] = (
            f"Upload is {uploaded.size / 1024 / 1024:.1f} MB; "
            f"the playground caps uploads at {MAX_UPLOAD_BYTES / 1024 / 1024:.0f} MB."
        )
        st.session_state["last_result"] = None
    else:
        safe_name = Path(uploaded.name).name
        tmp_path = _session_tmpdir() / f"suvix-upload-{safe_name}"
        try:
            tmp_path.write_bytes(uploaded.getvalue())
            extractor = _build_extractor(provider, model)
            options = ExtractionOptions(
                strategy=strategy,  # type: ignore[arg-type]
                max_frames=max_frames,
                max_recovery_attempts=max_recovery_attempts,
                per_call_timeout_seconds=per_call_timeout,
            )
            with st.spinner(f"Extracting with {extractor.name} (strategy: {strategy})…"):
                st.session_state["last_result"] = asyncio.run(
                    Suvix().extract(
                        video=str(tmp_path),
                        schema=schema,
                        instructions=instructions,
                        extractor=extractor,
                        options=options,
                    )
                )
            st.session_state["last_error"] = None
        except SuvixError as exc:
            # Readable message only — no tracebacks, never any secrets.
            st.session_state["last_result"] = None
            st.session_state["last_error"] = str(exc) or type(exc).__name__
        except Exception:  # defensive: adapters must never leak internals
            st.session_state["last_result"] = None
            st.session_state["last_error"] = (
                "Unexpected error during extraction (no details shown to "
                "avoid leaking internals)."
            )
        finally:
            tmp_path.unlink(missing_ok=True)

st.divider()
st.subheader("Result")

last_error = st.session_state.get("last_error")
last_result = st.session_state.get("last_result")

if last_error:
    st.error(f"Extraction failed: {last_error}")

if last_result is not None:
    result = last_result
    tab_json, tab_evidence, tab_validation, tab_usage, tab_execution = st.tabs(
        ["JSON", "Evidence", "Validation", "Usage", "Execution"]
    )
    with tab_json:
        st.json(result.data)
    with tab_evidence:
        if result.evidence:
            st.dataframe(
                [
                    {
                        "ref_type": item.ref_type,
                        "timestamp_seconds": _cell(item.timestamp_seconds),
                        "start_seconds": _cell(item.start_seconds),
                        "end_seconds": _cell(item.end_seconds),
                        "note": _cell(item.note),
                    }
                    for item in result.evidence
                ]
            )
            st.caption(
                "ref_type is honest about provenance: `provider_reported` = timestamp "
                "came from the provider (not independently verified); `frame` = locally "
                "extracted frame; `segment` = time interval; `description` = "
                "model-generated text, not a timestamp."
            )
        else:
            st.info("No evidence references returned.")
    with tab_validation:
        if result.validation.valid:
            st.success("valid ✓")
        else:
            st.error("invalid")
        if result.validation.issues:
            st.dataframe(
                [
                    {
                        "code": issue.code,
                        "severity": issue.severity,
                        "field": _cell(issue.field),
                        "message": issue.message,
                    }
                    for issue in result.validation.issues
                ]
            )
        else:
            st.info("No validation issues.")
    with tab_usage:
        usage = result.usage
        st.dataframe(
            [
                {"field": name, "value": _cell(value)}
                for name, value in [
                    ("input_tokens", usage.input_tokens),
                    ("output_tokens", usage.output_tokens),
                    ("total_tokens", usage.total_tokens),
                    ("provider_requests", usage.provider_requests),
                    ("recovery_requests", usage.recovery_requests),
                    ("sampled_frames", usage.sampled_frames),
                    ("video_duration_seconds", usage.video_duration_seconds),
                    ("latency_seconds", round(usage.latency_seconds, 3)),
                    ("estimated_cost_usd", usage.estimated_cost_usd),
                    ("cost_basis", usage.cost_basis),
                ]
            ]
        )
        st.caption(
            "cost_basis `unavailable` means the provider did not report cost data — "
            "Suvix never invents usage numbers."
        )
    with tab_execution:
        execution = result.execution
        st.write(f"**provider:** {execution.provider} · **model:** {execution.model}")
        st.write(f"**strategy:** {execution.strategy}")
        st.write(f"**strategy reason:** {execution.strategy_reason}")
        st.write(f"**stages:** {', '.join(execution.stages) or '—'}")
        st.write(
            f"**recovery attempts:** {execution.recovery_attempts} · "
            f"**validation status:** {execution.validation_status}"
        )
        st.write(
            f"**elapsed:** {execution.elapsed_seconds:.2f}s · "
            f"**provider calls:** {execution.provider_calls} · "
            f"**frames:** {execution.frame_count}"
        )
        if execution.warnings:
            st.warning("Warnings: " + "; ".join(execution.warnings))

    st.download_button(
        "Export result JSON",
        data=result.model_dump_json(indent=2),
        file_name="suvix-extraction-result.json",
        mime="application/json",
        help="Explicit export — the result JSON never contains credentials.",
    )
    st.caption("Export contains the extraction result only — never credentials.")

st.divider()
st.subheader("Strategy comparison")
st.button("Compare strategies", disabled=True)
st.info(
    "Only one strategy (`native_video`) is available with the current adapters, "
    "so there is nothing to compare yet — the button stays disabled instead of "
    "faking a comparison. It will light up when `selected_frames` lands (M5)."
)
