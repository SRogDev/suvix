# Privacy

What happens to your video and your data when you use Suvix (§21.4).

## Local processing

Frame sampling, schema validation, semantic checks, recovery orchestration,
and usage aggregation all run **locally** on your machine. Your JSON Schema
and instructions are only sent to a provider as part of an extraction call
you explicitly initiated with an explicitly chosen adapter.

## Remote provider requests

When you select a provider adapter, Suvix sends:

- **Native video**: the video file (or its bytes) to the provider's API.
- **Selected frames**: the sampled frame images (never the whole file, unless
  the sample covers it).

The provider returns model output; Suvix validates it locally. Provider-side
retention and deletion policies are documented per provider in
[`docs/providers/`](providers/) — read the "retention" section for the
adapter you use. Key points:

- **Gemini**: uploaded files are deleted after extraction (`finally` block);
  see `docs/providers/gemini.md` for retention details.
- **TwelveLabs**: uploaded assets are deleted after each call (`finally`
  block), but provider-side retention policies still apply;
  see `docs/providers/twelvelabs.md`.
- **OpenRouter**: requests go through OpenRouter's routing to third-party
  model endpoints; see `docs/providers/openrouter.md`.

## Temporary files

- Media processing (ffprobe/ffmpeg) works in `TemporaryDirectory` locations
  that the OS reclaims; Suvix never exposes temp paths in public results.
- Provider SDK uploads are deleted after each extraction, on success,
  failure, and (where the SDK allows) cancellation.

## What Suvix never does

- **No cache.** No database. No persistence. There is no on-disk or in-memory
  store of your videos, schemas, or results beyond the objects returned to
  your own code in the current process.
- **No telemetry.** Suvix makes no network calls except the ones your chosen
  provider adapter makes to its provider API.
- **No secrets in logs.** API keys are read from constructor arguments or
  environment variables and are redacted from mapped error messages.

## Benchmark reports

`run_baseline(..., output_dir=...)` writes JSON reports containing the task,
the extraction result, metrics, and provider/model names. Nothing is written
anywhere unless you pass `output_dir` explicitly.
