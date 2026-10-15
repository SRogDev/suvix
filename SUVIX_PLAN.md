Suvix — Complete Engineering and Implementation Plan
Document type: Implementation specification for AI coding agents
Project: Suvix
Language: English
Package ecosystem: Python + uv
Product category: Schema-guided video data extraction library
Primary objective: Determine whether Suvix can turn video into accurate, validated, developer-defined structured data more reliably, efficiently, or economically than calling video-capable models directly.

Repo: https://github.com/SRogDev/suvix (public, created 2026-10-15)
PyPI name check: "suvix" available on PyPI (404 on 2026-10-15)
Local workspace: ~/workspace/suvix/

───

1. Instructions for the Implementation Agents
You are implementing Suvix, an open-source Python library for extracting structured information from videos according to developer-provided JSON Schemas.
This document is the implementation specification. Follow it while adapting to the actual repository.
1.1. Inspect before implementing
Before writing code:
1. Inspect the repository structure, current Git status, existing implementation, documentation, tests, dependency manager, and package configuration.
2. Identify existing decisions and functionality that must be preserved.
3. Inspect any existing AGENTS.md, README, architecture documentation, and implementation plans.
4. Check the current official documentation for the providers and libraries you intend to use.
5. Verify package naming and publishing constraints before making release claims.
6. Produce a concise repository audit and implementation sequence.
7. Identify contradictions between this plan and existing code before changing architecture.
Do not overwrite existing work simply because it differs from the proposed directory structure.
If the repository already contains working components, adapt this specification to reuse them where appropriate.
1.2. Implementation discipline
• Implement small, testable increments.
• Use type hints throughout the public API and core abstractions.
• Prefer explicit contracts over implicit behavior.
• Keep provider SDKs behind adapters.
• Avoid unnecessary abstractions, dependencies, and configuration.
• Never invent provider capabilities.
• Never silently switch models, providers, extraction modes, or validation policies.
• Never claim cost savings without benchmark evidence.
• Never add persistent caching or a database.
• Do not make paid API calls in the default test suite.
• Preserve user changes and avoid destructive Git operations.
• Run relevant tests after every significant change.
• Document limitations rather than hiding them.
• Ask the project owner only when a genuinely blocking product decision cannot be resolved from this specification or the existing repository.
The objective is a working, installable library, not an elaborate framework.

───

2. Product Definition
2.1. What Suvix is
Suvix is a developer library that converts video into structured data matching a schema defined by the developer.
The developer specifies:
• The video to analyze.
• The JSON Schema describing the desired output.
• Instructions describing what information matters.
• The provider and model adapter to use.
• The desired extraction strategy.
• Optional limits on sampling, retries, and resource consumption.
Suvix manages the extraction workflow, video inspection where necessary, frame selection, structured output, validation, evidence references, and execution metadata.
The library should make it easier to request specific information from video without forcing developers to implement all the surrounding orchestration themselves.
Example applications include:
• Extracting sports events and timestamps.
• Identifying actions in instructional videos.
• Extracting visible product attributes.
• Reading text displayed in a video.
• Detecting specified events in security footage.
• Producing structured descriptions of video segments.
• Extracting scene transitions, object counts, and temporal relationships.
• Converting demonstrations into machine-readable event sequences.
These are potential application domains, not claims that every provider can reliably perform every task.
2.2. The central research question
Suvix must answer an empirical question:
Can an orchestration and extraction layer improve the quality, cost, latency, or developer experience of video-to-structured-data tasks compared with direct model calls?
The answer must come from benchmarks.
Suvix should not assume that:
• Frame sampling is always cheaper.
• Native video input is always more accurate.
• A multi-stage workflow is always better than a single model call.
• JSON Schema guarantees semantic correctness.
• A smaller number of frames means lower provider costs.
• All video models expose the same capabilities.
• Every extraction task benefits from coarse-to-fine search.
The architecture must support comparisons between strategies and make their trade-offs measurable.
2.3. Core product principles
1. Schema first. The developer defines the desired data structure.
2. Explicit provider selection. The developer chooses the provider and model.
3. Evidence-aware output. Results should include traceable timestamps and frame references when the chosen strategy can support them.
4. Provider-neutral core. Provider-specific behavior stays inside adapters.
5. Bounded execution. Sampling, retries, file size, duration, and other resource-consuming operations must have explicit limits.
6. Honest uncertainty. Missing information must not be fabricated.
7. Measurable performance. Accuracy, latency, usage, and cost must be observable.
8. No implicit persistence. Suvix does not own the application's data lifecycle.
9. Low integration friction. A developer should be able to integrate Suvix into an existing Python application without adopting a larger infrastructure stack.

───

3. Non-Goals and Explicit Exclusions
The first version must not implement:
• Persistent caching.
• A database.
• A hosted extraction service.
• A mandatory remote storage service.
• A queue or distributed worker system.
• An automatic model router that independently chooses providers.
• Model fine-tuning or training.
• A custom vision model.
• A mandatory embedding or vector database.
• A mandatory agent framework.
• A mandatory LLM for planning.
• A general-purpose video editor.
• A full production web application.
• An authentication or billing system.
• Automatic cost optimization without measured evidence.
• Guaranteed event detection from frames that were never observed.
• A proprietary intermediate storage format that developers must adopt.
• A built-in cache directory or implicit disk cache.
Suvix may use temporary files required by media processing or provider SDKs. These are execution resources, not persistent application storage, and must be cleaned up according to documented lifecycle rules.
A developer may wrap Suvix with Redis, a database, object storage, or their own caching implementation. Those systems remain outside Suvix's core.

───

4. Supported Extraction Tasks for the MVP
The initial release should focus on three representative task families.
4.1. Temporal events and actions
Example request:
Identify every time a person performs a specified action.
Example output:
• Event type.
• Start timestamp.
• End timestamp, when supported.
• Short description.
• Evidence reference.
Important evaluation dimensions:
• Event precision and recall.
• Timestamp accuracy.
• Missed short-duration events.
• Duplicate events.
• Correct ordering.
4.2. Objects, counts, and visible attributes
Example request:
Extract the visible objects in a scene and their requested attributes.
Potential fields:
• Object category.
• Count.
• Color.
• Position or region, if supported.
• Relevant attributes.
• Evidence reference.
Important evaluation dimensions:
• Object identification accuracy.
• Count accuracy.
• Attribute accuracy.
• Unsupported claims.
• Changes across time.
4.3. Visible text and on-screen information
Example request:
Extract the score, label, product name, or other visible text shown in a video.
Potential fields:
• Text content.
• Timestamp.
• Context or category.
• Evidence reference.
Important evaluation dimensions:
• Exact text accuracy.
• Missing text.
• Confusion between similar characters.
• Temporal association.
• False text extraction.
These task families provide useful initial coverage without making the MVP too broad.
The implementation should remain extensible to new tasks through schemas and instructions rather than adding a separate subsystem for every use case.

───

5. Public API Design
The public API must remain small and stable.
The examples in this document are proposed interfaces. Agents must implement and test them rather than assuming they already exist.
5.1. Desired developer experience
A developer should be able to write:
python
from pydantic import BaseModel

from suvix import Suvix
from suvix.adapters.gemini import GeminiExtractor


class Event(BaseModel):
    timestamp_seconds: float
    event_type: str
    evidence: str


class Extraction(BaseModel):
    events: list[Event]


extractor = GeminiExtractor()

suvix = Suvix()

result = await suvix.extract(
    video="sample.mp4",
    schema=Extraction.model_json_schema(),
    instructions="Identify each visible event of interest.",
    extractor=extractor,
)

print(result.data)
print(result.evidence)
print(result.validation.valid)
print(result.usage)

This is the target experience, not permission to introduce unnecessary dependencies or to assume a provider supports every field in every schema.
5.2. Core method
Implement a central asynchronous method with approximately the following signature:
python
async def extract(
    *,
    video,
    schema: dict,
    instructions: str,
    extractor,
    options=None,
) -> ExtractionResult:
    ...

The precise type definitions must be established in the contracts milestone.
The API should make required inputs explicit.
Required arguments
video
Accept a documented video input type. Start with local file paths and explicitly supported file objects or media references where practical.
Do not promise arbitrary URL support until security, downloading, limits, and provider behavior are implemented.
schema
A JSON Schema dictionary describing the required output.
instructions
A developer-provided description of the information to extract.
extractor
An explicit adapter instance representing the selected provider and model.
The developer chooses the provider. Suvix must not silently replace that choice.
options
Optional, validated configuration controlling extraction behavior.
5.3. Configuration
Provide a small typed options object rather than a large collection of unrelated keyword arguments.
Candidate settings include:
• Extraction strategy: auto, native_video, or selected_frames.
• Maximum sampled frames.
• Coarse sampling interval.
• Maximum refinement rounds.
• Maximum selective retries.
• Optional per-call timeout.
• Optional file and duration limits.
• Whether recovery is enabled.
• Whether evidence is required.
• Whether provider usage metadata should be collected when available.
Choose conservative defaults.
Do not add every conceivable option to the initial public API. Promote settings to public API only when they materially improve developer control.
5.4. Result contract
The result must separate extracted business data from execution metadata.
Proposed structure:
python
@dataclass
class ExtractionResult:
    data: dict
    evidence: list
    validation: object
    usage: object
    execution: object

The final implementation may use Pydantic models or frozen dataclasses, but should choose one approach consistently.
data
The extracted JSON-compatible object.
It must conform to the requested schema when validation succeeds.
evidence
Normalized references connecting extracted claims to observed video material.
validation
Structural and semantic validation outcomes.
usage
Provider-reported usage, estimated usage where appropriate, and cost information when a reliable price source is available.
execution
Metadata describing the selected strategy, frame counts, stages, provider calls, retry counts, duration, and relevant limitations.
Do not insert internal metadata into the developer's schema-defined data object.
5.5. Error contract
Expose meaningful exceptions or structured errors for:
• Invalid input.
• Unsupported schema.
• Unsupported media.
• Unsupported extraction strategy.
• Provider configuration errors.
• Provider request errors.
• Rate limits.
• Timeouts.
• Malformed structured output.
• Schema validation failure.
• Exhausted recovery budget.
• Media processing failures.
• Missing evidence.
• Cancelled execution.
Errors should include enough context to debug failures without exposing credentials or unnecessarily copying video content into logs.
Do not silently return empty data when extraction fails.

───

6. Architecture
6.1. High-level pipeline
The core execution pipeline should be:
1. Normalize the request.
2. Validate the input and JSON Schema.
3. Inspect the selected adapter's capabilities.
4. Inspect media metadata if necessary.
5. Select an extraction strategy.
6. Prepare the video or selected frames.
7. Perform structured extraction.
8. Normalize the response.
9. Validate the output.
10. Validate evidence and deterministic semantic constraints.
11. Perform bounded selective recovery if enabled.
12. Assemble the final result and execution metadata.
13. Release temporary resources.
A simplified flow:
text
Developer Request
       |
       v
Request + Schema Validation
       |
       v
Adapter Capability Inspection
       |
       v
Strategy Selection
       |
       +----------------------+
       |                      |
       v                      v
 Native Video            Selected Frames
       |                      |
       v                      v
 Provider Extraction     Coarse Search
                              |
                              v
                        Fine Inspection
                              |
                              v
                         Extraction
       |                      |
       +-----------+----------+
                   |
                   v
          Normalize JSON Output
                   |
                   v
       Structural + Semantic Checks
                   |
                   v
          Bounded Selective Recovery
                   |
                   v
            Extraction Result

The native-video branch may itself involve multiple provider-side operations that Suvix cannot observe. Record only what the provider actually reports.
6.2. Proposed source structure
Adapt this structure to the existing repository:
text
suvix/
├── pyproject.toml
├── uv.lock
├── README.md
├── LICENSE
├── AGENTS.md
├── src/
│   └── suvix/
│       ├── __init__.py
│       ├── api.py
│       ├── contracts.py
│       ├── options.py
│       ├── errors.py
│       ├── planner.py
│       ├── extraction.py
│       ├── validation.py
│       ├── recovery.py
│       ├── evidence.py
│       ├── usage.py
│       ├── pricing.py
│       ├── media/
│       │   ├── __init__.py
│       │   ├── metadata.py
│       │   ├── frames.py
│       │   └── segments.py
│       ├── sampling/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── uniform.py
│       │   └── scene_changes.py
│       ├── adapters/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── gemini.py
│       │   ├── openrouter.py
│       │   └── twelvelabs.py
│       └── evaluation/
│           ├── __init__.py
│           ├── metrics.py
│           ├── runner.py
│           └── cost.py
├── examples/
│   ├── basic_extraction.py
│   └── custom_extractor.py
├── playground/
│   └── app.py
├── tests/
│   ├── unit/
│   ├── contract/
│   ├── integration/
│   └── fixtures/
├── benchmarks/
│   ├── tasks/
│   ├── fixtures/
│   ├── baselines/
│   └── results/
└── docs/
    ├── architecture.md
    ├── providers.md
    ├── benchmarking.md
    ├── privacy.md
    └── decisions/

Do not create empty modules just to match the diagram. Add files when they have concrete responsibilities.
6.3. Dependency direction
Keep the architecture one-directional:
• Public API depends on core contracts.
• Core orchestration depends on abstract adapter interfaces.
• Provider adapters implement those interfaces.
• Media and sampling utilities remain provider-neutral.
• Validation does not depend on provider SDKs.
• The playground depends on the public API.
• Benchmarks consume the public API and explicitly selected direct-provider baselines.
• The core library must never import Streamlit.
• No core module may require a database or cache.
Optional provider SDKs must not become mandatory dependencies of users who do not use those providers.

───

7. Provider Adapter System
7.1. Purpose
Adapters isolate provider-specific request construction, media handling, response parsing, usage reporting, and limitations.
The core should not contain provider-specific request code.
7.2. Adapter contract
Define an abstract interface similar to:
python
class VideoExtractor(Protocol):
    @property
    def capabilities(self) -> "ExtractorCapabilities":
        ...

    async def extract(self, request) -> "ProviderExtraction":
        ...

Finalize the actual method signature during the contracts milestone.
Capabilities should describe, where applicable:
• Native video input.
• Image or frame input.
• Multiple images per request.
• Structured output support.
• JSON Schema compatibility and restrictions.
• Provider-side video uploads.
• File reference support.
• Maximum request size or duration, when documented.
• Usage metadata availability.
• Timestamp support.
• Provider-side processing behavior.
• Whether the provider exposes inspected frames or frame-level evidence.
Capabilities must be factual and preferably tested.
If a provider does not expose internal sampling details, Suvix must not pretend that it knows which frames the provider analyzed.
7.3. Initial provider order
Implement in this order:
1. Gemini API.
2. OpenRouter.
3. TwelveLabs.
The exact order may be adjusted if repository constraints or verified SDK capabilities justify it, but every provider must implement the same core contract.
Gemini
Use the official Google-supported SDK and current API.
Support the simplest reliable native-video workflow first. Add selected-frame support where it offers a meaningful alternative.
Handle provider file uploads and file lifecycle correctly. If temporary remote uploads are created, use the provider's documented deletion mechanisms when appropriate and document retention limitations.
Do not assume provider files disappear immediately or that every provider model has identical limits.
OpenRouter
Use the supported API and SDK or HTTP client verified during implementation.
The developer explicitly selects a compatible model.
Video support may vary by model, endpoint, request format, and provider behind the gateway. Do not assume every model listed by OpenRouter accepts video.
Maintain a clear, testable distinction between:
• Native video support.
• Multiple image inputs.
• Unsupported media formats.
• Structured output capabilities.
• Usage fields that may be missing or estimates.
If the chosen model cannot support a requested strategy, return an actionable error. Do not silently substitute another model.
TwelveLabs
Verify the currently available API, SDK, authentication, supported models, video processing workflow, structured output capabilities, timestamps, and free-tier conditions.
Use its native capabilities where appropriate, but do not assume its interface is identical to a generative model API.
If the provider is fundamentally different, implement an adapter that maps its real capabilities to the common extraction contract without pretending unsupported features exist.
7.4. Provider verification requirement
Before implementing each adapter, record:
• Official documentation URL.
• SDK and API version.
• Verification date.
• Supported input modes.
• Schema constraints.
• Media limits.
• Usage reporting capabilities.
• File retention and deletion behavior.
• Known unsupported features.
• A minimal working request.
Treat these details as time-sensitive.
Do not rely on old examples or unofficial claims when current provider documentation is available.

───

8. Video Input and Media Processing
8.1. Initial input support
Support local video files first.
Potential future inputs include file-like objects and remote URLs, but these should only be added when their lifecycle and security behavior are clear.
Avoid an overly broad input abstraction that makes basic usage difficult.
8.2. Metadata inspection
Extract relevant metadata where available:
• Duration.
• Width and height.
• Frame rate.
• Time base.
• File size.
• Codec.
• Audio stream presence.
Use ffprobe or a suitable maintained library, depending on the repository's existing dependencies and packaging constraints.
Do not require developers to install heavyweight dependencies unless necessary for the functionality they use.
If FFmpeg is an optional external dependency, detect its absence and provide a clear error.
8.3. Frame extraction
When using selected-frame mode:
• Extract frames at explicit timestamps.
• Preserve the timestamp associated with each frame.
• Avoid loading an entire high-resolution video into memory.
• Use bounded frame budgets.
• Handle timestamp rounding.
• Handle variable frame rates where practical.
• Handle videos shorter than the sampling interval.
• Handle zero-duration or malformed files.
• Handle seeking failures.
• Release temporary files on success and failure.
Never assume that the nominal frame rate gives a perfectly accurate timestamp for every frame.
8.4. Variable frame rate and timestamp correctness
Timestamp accuracy is essential.
Represent time in a consistent internal unit, preferably seconds as a floating-point value or a more precise internal representation when required.
Where frame extraction relies on actual presentation timestamps, preserve those values instead of deriving every timestamp from a simplistic frame-index calculation.
Test:
• Constant frame rate.
• Variable frame rate.
• Nonzero segment offsets.
• Segment boundary conditions.
• Rounding behavior.
• Short clips.
• Frames at the beginning and end of a video.

───

9. Extraction Strategies
Suvix must support two fundamental strategies and a simple automatic selection mode.
9.1. Native-video strategy
Send the video through the selected provider's supported native-video interface.
Advantages may include:
• Less custom preprocessing.
• Potentially better temporal reasoning.
• Reduced local media-processing complexity.
• Simpler developer experience.
Potential disadvantages include:
• Limited control over internal sampling.
• Provider-specific constraints.
• Uncertain internal frame coverage.
• Cost and latency that vary by provider.
• Limited evidence visibility.
Suvix should record the selected strategy and any observable provider metadata.
Do not claim that the provider inspected a specific set of frames unless it explicitly exposes that information.
9.2. Selected-frame strategy
Suvix extracts a bounded set of frames and sends them to the selected adapter.
Advantages may include:
• Explicit frame timestamps.
• Control over frame density.
• Traceable evidence references.
• Predictable local sampling behavior.
• Potential suitability for providers that accept images but not video.
Potential disadvantages include:
• Missed short events.
• Loss of temporal continuity.
• More complicated requests.
• Higher cost in some providers.
• Potentially worse accuracy than native video.
Do not claim that this strategy is always cheaper or more accurate.
9.3. Automatic strategy selection
auto must initially be a small, explainable rule-based planner.
It may consider:
• Adapter capabilities.
• Whether native video is supported.
• Video duration.
• The task's need for temporal detail.
• Requested evidence granularity.
• User-specified frame and resource limits.
It must not require another LLM call.
It must not choose another provider.
It must not hide its choice.
Record the decision and a concise reason in execution metadata.
The developer must be able to override automatic selection.
9.4. Coarse-to-fine search
Implement coarse-to-fine inspection as an optional strategy for selected-frame workflows.
Proposed process:
1. Sample a bounded coarse set of frames.
2. Identify potentially relevant intervals.
3. Expand candidate intervals with contextual frames.
4. Inspect those intervals more densely.
5. Produce the final schema-defined extraction.
6. Validate the result and evidence.
The coarse pass may produce candidate intervals internally, but the final public data must remain governed by the requested JSON Schema.
The final extraction should not expose an arbitrary intermediate planning structure unless that structure is part of the developer's schema.
Important constraints
• The coarse stage must not be an unbounded agent loop.
• Refinement rounds must have an explicit maximum.
• Frame budgets must be enforced.
• Segment offsets must be applied correctly.
• Duplicate events across adjacent segments must be handled.
• Boundary events must be tested.
• A coarse pass may miss a brief event entirely.
• A refinement pass must not be described as exhaustive if its candidate-selection process cannot guarantee coverage.
The implementation must compare coarse-to-fine against native video and simple uniform sampling.
If coarse-to-fine performs worse on a task, document that result instead of forcing it into the default path.
9.5. Sampling algorithms
MVP: uniform sampling
Implement deterministic uniform sampling first.
Inputs should include:
• Video duration.
• Maximum frame budget.
• Optional sampling interval or density.
• Relevant resource limits.
The algorithm should behave predictably for the same input and configuration.
Optional later: scene-change sampling
Add scene-change sampling only if the baseline and a concrete use case justify it.
It should identify visual transitions, not claim to identify semantic events.
A scene change is not equivalent to an important event.
Do not introduce a trained detector or large computer-vision dependency merely to provide an optional heuristic.

───

10. JSON Schema and Structured Extraction
10.1. Schema validation
Validate the supplied JSON Schema locally before making a provider request.
Reject invalid schemas with a clear error.
Document the supported JSON Schema draft and validator.
Choose a maintained validation library, such as jsonschema, if appropriate.
10.2. Provider schema compatibility
Different providers may support different subsets of JSON Schema.
Each adapter must implement an explicit schema compatibility layer.
This layer may transform a schema into a provider-compatible representation when necessary, but:
• It must never silently discard important constraints.
• It must not claim that the transformed schema is identical when it is not.
• It must preserve the canonical original schema for local validation.
• Unsupported features must generate clear errors or documented warnings.
• Any lossy transformation must be explicit.
10.3. Extraction instructions
Construct provider requests using:
• The developer's instructions.
• The requested schema or compatible representation.
• Evidence requirements.
• Timestamp conventions.
• Missing-information policy.
• Task-specific constraints.
Do not overcomplicate prompts with a universal prompt framework.
Keep prompts short enough to be understandable and maintainable.
10.4. Missing information
Suvix must distinguish between:
• A field whose value is genuinely unknown.
• A field that is absent because the model failed to extract it.
• A field that is optional in the schema.
• A field that is required by the schema.
Do not fabricate values to satisfy a required field.
Do not insert null into fields that prohibit null.
If the schema permits an explicit unknown representation, follow it. Otherwise, validation should report the conflict rather than silently changing the schema.
10.5. Output normalization
Normalize common provider response wrappers into the expected JSON-compatible structure.
Normalization must not change the semantic meaning of the data.
Do not silently strip fields, invent missing values, or coerce invalid values without a documented rule.
Preserve the raw provider response only when explicitly needed for debugging and permitted by the privacy configuration. Do not make raw response persistence a default feature.

───

11. Evidence and Timestamp References
Evidence is an important differentiator, but it must be honest and verifiable.
11.1. Evidence contract
A normalized evidence reference may include:
• Timestamp in seconds.
• Optional interval start and end.
• Frame identifier.
• Reference type.
• Optional descriptive note.
• Optional source segment identifier.
Use typed contracts instead of unstructured dictionaries throughout the internal pipeline.
11.2. Frame references
For selected-frame mode, each frame that is sent to a provider should have an internal reference mapping to its actual timestamp and relevant artifact or local execution identifier.
If the provider's output references a frame identifier, validate that it corresponds to a frame actually supplied.
Do not fabricate frame identifiers or imply that a frame was observed when it was not.
Do not expose temporary local filesystem paths as durable public references.
A public frame reference must have clearly documented semantics and a useful lifetime.
11.3. Native-video evidence
Native-video providers may return timestamps without exposing the exact frames that supported their conclusions.
In such cases, represent the timestamp as provider-reported evidence, not as a verified frame artifact.
Clearly distinguish:
• Provider-reported timestamps.
• Actual locally sampled frame references.
• Model-generated descriptions of evidence.
• Evidence that has been independently verified.
11.4. Evidence validation
Check:
• Timestamp values are finite and nonnegative.
• Timestamps are within the video's valid duration, allowing documented tolerance.
• Interval starts do not exceed interval ends.
• Frame references exist in the execution's frame registry.
• Segment-relative timestamps are converted correctly to global timestamps.
• Duplicate evidence is handled consistently.
Evidence references improve traceability; they do not automatically prove that a model's interpretation is correct.

───

12. Structural and Semantic Validation
12.1. Structural validation
Validate the extracted object against the original JSON Schema locally.
Structural validation should detect:
• Missing required fields.
• Unexpected fields where prohibited.
• Incorrect types.
• Invalid enum values.
• Invalid arrays and objects.
• Numeric constraint violations.
• Invalid timestamp field types.
• Other supported schema violations.
A provider's claim that its response is structured does not replace local validation.
12.2. Deterministic semantic validation
Implement a small, extensible layer for deterministic checks.
Examples:
• A timestamp cannot be negative.
• An interval start must not exceed its end.
• A timestamp must fall within the video duration.
• A frame reference must correspond to a known frame.
• Required events must follow documented ordering constraints.
• Certain numeric values must satisfy explicitly configured invariants.
Do not pretend that arbitrary semantic truth can be validated through deterministic code.
For example, code can verify that a timestamp is within the clip; it cannot prove that the model correctly recognized a person running.
12.3. Recovery
Implement bounded selective recovery after the basic extraction and validation path works.
Recovery may target:
• A malformed JSON response.
• Specific schema violations.
• Missing required information.
• Invalid timestamp references.
• A small number of explicitly identified fields or intervals.
Recovery should use the existing provider and model unless the developer explicitly creates another extractor or policy.
Do not silently switch models.
Do not restart the entire workflow when a narrowly scoped correction is sufficient.
Every recovery request must count toward usage, latency, and cost metrics.
12.4. Recovery budgets
Configure:
• Maximum recovery attempts.
• Maximum refinement rounds.
• Maximum additional provider requests.
• Optional timeout or total execution budget.
The defaults must be conservative.
When the budget is exhausted, return a clear validation failure or raise a documented exception according to the API contract.
Do not create an infinite repair loop.
12.5. Baseline mode
The benchmark suite must support a mode with recovery disabled.
Otherwise, it will be difficult to measure whether recovery actually improves the output.
Compare:
• Initial extraction.
• Extraction plus validation.
• Extraction plus bounded recovery.

───

13. Caching, Persistence, and Resource Lifecycle
This section is an explicit architectural constraint: Suvix has no cache subsystem.
13.1. No caching
Do not implement:
• A cache directory.
• A persistent result cache.
• A content-addressed cache.
• A built-in Redis integration.
• A database-backed cache.
• An implicit cache decorator.
• A cache configuration system.
• A cache invalidation subsystem.
• A persistent history of extractions.
The caller owns caching.
If an application wants to cache a result based on the video, schema, model, instructions, and configuration, it can implement that policy itself.
Do not add caching merely because repeated provider calls can be expensive.
13.2. No application persistence
Suvix does not store extraction history or maintain a permanent copy of source videos.
Do not add a database or remote storage dependency.
Benchmark outputs may be written to a user-selected destination as an explicit benchmark operation. This is not runtime caching.
13.3. Temporary files
Media processing and provider SDKs may require temporary files.
The implementation must:
• Use safe temporary-file handling.
• Clean up files on success.
• Clean up files on exceptions.
• Clean up after cancellation where practical.
• Avoid predictable shared filenames.
• Avoid exposing temporary paths in public results.
• Document any unavoidable provider-side persistence.
If a provider supports remote uploads, use its documented deletion mechanism when appropriate.
Do not promise deletion if the provider's retention policy does not guarantee it.
13.4. Ownership boundary
The application developer owns:
• Persistence.
• Caching.
• Result retention.
• Access control.
• Business-specific deduplication.
• Long-term video storage.
• Application-level audit history.
Suvix owns:
• Extraction orchestration.
• Temporary media processing.
• Provider request construction.
• Output normalization.
• Validation.
• Execution metadata.
This boundary must be documented in the README and privacy documentation.

───

14. Local Streamlit Playground
The project should include an optional local playground to make the library easy to test without building a separate frontend application.
The playground is a development and demonstration tool, not a production SaaS interface.
14.1. Core functionality
The user should be able to:
1. Upload a local video.
2. Enter extraction instructions.
3. Edit or paste a JSON Schema.
4. Select a provider and model where supported.
5. Choose native-video, selected-frame, or automatic strategy.
6. Configure bounded sampling and recovery options.
7. Start an extraction explicitly.
8. Inspect the returned JSON.
9. Inspect evidence timestamps and frame references.
10. Inspect validation results.
11. Inspect provider usage and execution metadata.
12. Compare different strategies when the selected provider supports both.
13. Export the result JSON explicitly.
Do not add accounts, a backend database, cloud deployment, or a history service.
14.2. Credentials
Read provider credentials from environment variables or another explicitly documented local configuration mechanism.
Examples:
• GEMINI_API_KEY
• OPENROUTER_API_KEY
• The credential required by the verified TwelveLabs SDK.
Do not expose secrets in the interface, logs, result JSON, or error messages.
Do not commit real credentials to the repository.
14.3. Upload behavior
Selecting a video must not automatically trigger a provider upload.
The user should explicitly start extraction before a remote request is made.
Display the selected provider, model, and extraction strategy so the user knows what will happen.
14.4. Result display
Display the extracted JSON independently from:
• Evidence.
• Validation.
• Usage.
• Execution metadata.
• Errors.
If frames are displayed, make their timestamps clear.
Do not imply that displayed frames are the provider's internal frames unless that is actually known.
14.5. Cleanup
Use bounded uploads and temporary files.
Clean up local temporary resources when the session or extraction lifecycle permits.
Avoid retaining videos or raw provider responses longer than needed for the current operation.
14.6. Optional dependency
Streamlit must be an optional extra.
Suggested local setup, subject to the final pyproject.toml:
bash
uv sync --extra playground --extra gemini
uv run streamlit run playground/app.py

The exact extra names must match the package configuration.

───

15. Packaging and Installation
15.1. Package configuration
Use a modern pyproject.toml with a src/ package layout.
Use uv for dependency management and lockfile maintenance.
Keep runtime dependencies minimal.
Provider SDKs and Streamlit should be optional extras wherever practical.
Candidate extras:
• gemini
• openrouter
• twelvelabs
• playground
• dev
Use valid dependency constraints and test them against the actual SDK versions.
15.2. Development installation
From the repository root:
bash
uv sync

For development and testing:
bash
uv sync --extra dev
uv run pytest

For a local editable installation into another environment, use an appropriate local path dependency rather than assuming the package is already published.
15.3. Downstream installation
Once the package is published to PyPI under the name suvix, a consuming project can install it with:
bash
uv add suvix

For a provider-specific installation, document the correct extra syntax supported by the published package, for example:
bash
uv add "suvix[gemini]"

Verify that the package manager and the chosen publishing configuration support the intended extra syntax.
Do not document uv install suvix as the canonical command.
uv tool install is intended for installing standalone command-line tools; Suvix is primarily an importable library.
15.4. Release verification
Before release:
• Verify the package name is available and legally usable.
• Verify package metadata.
• Build source and wheel distributions.
• Install the built wheel in a clean environment.
• Test importing the package without optional providers installed.
• Test each optional extra independently.
• Confirm the README installation commands work.
• Confirm no secrets or local video fixtures are accidentally packaged.
• Verify the license and third-party dependency licenses.
• Verify Python version compatibility.
• Confirm the package can be installed through the intended uv workflow.
Use uv build if it is appropriate for the repository's packaging configuration.

───

16. Benchmarking and Experimental Evaluation
Benchmarking is central to Suvix's purpose. It is not a final marketing task.
16.1. Primary research question
For a fixed video, task, schema, and evaluation criterion, does Suvix improve:
• Correctness?
• Schema compliance?
• Timestamp accuracy?
• Cost per correct result?
• Latency?
• Developer implementation effort?
Measure each dimension separately.
Do not collapse everything into a single metric that hides trade-offs.
16.2. Required comparison groups
Baseline A: direct native-provider call
Call the provider directly using its recommended native-video interface and a comparable extraction instruction.
This measures the performance developers could obtain without Suvix's orchestration.
Baseline B: Suvix native-video mode
Use Suvix with the same provider and model, where supported.
This measures the overhead and benefits of schema validation, evidence handling, normalization, and other library features.
Baseline C: Suvix selected-frame mode
Use Suvix's frame selection and extraction workflow.
Baseline D: Suvix coarse-to-fine mode
Where implemented, evaluate coarse-to-fine inspection separately.
Optional Baseline E: direct selected-frame calls
For providers that support image inputs but not native video, compare Suvix with a direct implementation that submits the same frames and performs equivalent extraction.
Do not compare incompatible inputs as though they were equivalent.
16.3. Fair comparison rules
For each comparison:
• Use the same underlying model where possible.
• Use the same video.
• Use equivalent extraction instructions.
• Use the same target schema.
• Use the same evaluation criteria.
• Record differences in provider requests.
• Count all additional model calls.
• Count recovery requests.
• Record actual frame counts where available.
• Record the source and reliability of cost estimates.
• Report unsupported features and unavoidable differences.
Where exact equivalence is impossible, explicitly document why.
16.4. Metrics
Structural quality
• JSON parse success rate.
• Schema pass rate.
• Missing required field rate.
• Invalid evidence reference rate.
Semantic quality
• Per-field accuracy.
• Event precision.
• Event recall.
• Event F1 where appropriate.
• Object count accuracy.
• Text extraction accuracy.
• Timestamp absolute error.
• Unsupported-claim rate.
• Duplicate event rate.
Operational performance
• End-to-end latency.
• Provider latency where measurable.
• Number of provider requests.
• Retry count.
• Number of sampled frames.
• Processed video duration.
• Memory use where practical.
• Failure rate.
Economic performance
• Provider-reported input and output usage.
• Actual billed cost where available.
• Estimated cost with the estimation method clearly identified.
• Total cost per extraction.
• Cost per correct extraction.
• Cost per successfully extracted event where appropriate.
If actual cost cannot be measured, label the figure as an estimate.
Do not invent exact costs from incomplete usage metadata.
16.5. Ground truth
Create a small, carefully annotated evaluation set before expanding it.
Each case should include:
• A video or a documented reference to it.
• The task description.
• The JSON Schema.
• Expected output.
• Timestamp tolerance.
• Evaluation instructions.
• A task category.
• Any known ambiguities.
Choose diverse cases, including:
• Long and short videos.
• Brief events.
• Repeated events.
• Dense and sparse scenes.
• Multiple objects.
• On-screen text.
• Events near segment boundaries.
• Cases where the correct answer is that evidence is insufficient.
Do not rely solely on model-generated labels as ground truth.
Use public benchmark datasets only after checking their licensing, availability, and evaluation protocols.
A benchmark such as KFS-Bench may be relevant to investigating video frame sampling, but it must not be treated as a universal benchmark for arbitrary schema-guided extraction.
16.6. Results and reproducibility
Save benchmark outputs only when the user explicitly runs a benchmark with a configured output destination.
Include:
• Run identifier.
• Timestamp.
• Provider.
• Model identifier.
• Strategy.
• Relevant options.
• Video/task identifiers.
• Usage metadata.
• Validation results.
• Evaluation metrics.
• Error information.
• Pricing assumptions.
Do not add automatic persistent benchmark history to the runtime library.
Keep benchmark datasets and credentials separate.
16.7. Success criteria
Do not invent a target percentage for cost savings before measuring the baseline.
The first benchmark milestone must establish a trustworthy baseline.
After that, define measurable release criteria for:
• Correctness.
• Schema compliance.
• Timestamp error.
• Latency.
• Cost.
• Failure rate.
If Suvix does not improve raw model accuracy, it can still deliver value through validation, evidence traceability, consistent contracts, and reduced integration work. These benefits must be described accurately.

───

17. Testing Strategy
17.1. Unit tests
Unit tests must not require network access or provider API keys.
Test:
• Request validation.
• Schema validation.
• Schema compatibility errors.
• Option validation.
• Strategy selection.
• Uniform sampling.
• Timestamp conversion.
• Segment offsets.
• Frame reference registration.
• Evidence validation.
• Output normalization.
• Unknown-value behavior.
• Error mapping.
• Retry budgets.
• Usage aggregation.
• Pricing calculations.
• Temporary-file cleanup.
• Cancellation behavior where practical.
• Secret redaction.
Use fake adapters for deterministic orchestration tests.
17.2. Adapter contract tests
Every adapter must satisfy a shared set of tests covering:
• Capability reporting.
• Input preparation.
• Request construction.
• Response normalization.
• Usage extraction.
• Provider error mapping.
• Unsupported-feature handling.
• Cancellation and timeout behavior where supported.
Use mocked SDK responses for routine tests.
17.3. Integration tests
Real provider tests must be opt-in.
For example:
bash
SUVIX_RUN_INTEGRATION_TESTS=1 uv run pytest tests/integration

The exact environment variable can be adjusted to the existing test conventions.
Integration tests must:
• Require explicit opt-in.
• Fail clearly when required credentials are missing.
• Use small, controlled fixtures.
• Avoid unexpectedly expensive operations.
• Report provider/model details.
• Avoid exposing secrets.
• Avoid making the default test suite dependent on network availability.
17.4. Regression fixtures
Maintain a small set of deterministic mock responses for known edge cases.
Examples:
• Malformed JSON.
• Incorrect timestamp.
• Missing field.
• Unexpected field.
• Unsupported schema keyword.
• Invalid frame reference.
• Provider rate limit.
• Timeout.
• Upload failure.
• Recovery exhaustion.
For real-model evaluations, preserve benchmark inputs and evaluation protocols. Do not assume model outputs will remain deterministic across model versions.
17.5. Test quality requirement
A passing test suite must verify actual behavior.
Avoid tests that only assert that a method exists or that a mock was called.
For every major public behavior, include both a successful case and relevant failure cases.

───

18. Usage, Cost, and Execution Observability
Suvix should expose execution metadata without requiring an external observability service.
18.1. Usage model
Where available, collect:
• Input tokens.
• Output tokens.
• Other provider-reported usage units.
• Provider request count.
• Number of recovery requests.
• Number of sampled frames.
• Video duration.
• End-to-end latency.
Providers expose different usage formats. Do not invent missing values.
Represent unavailable usage explicitly.
18.2. Cost estimation
Cost estimation must be optional and transparent.
Use a versioned or documented pricing configuration when exact provider billing information is not returned.
A cost estimate should identify:
• Provider.
• Model.
• Pricing source.
• Pricing date or version.
• Measured usage.
• Estimated components.
• Components that could not be estimated.
Do not hardcode one universal pricing formula across providers with materially different billing models.
Do not make a model-routing decision based on an unverified cost estimate.
18.3. Execution metadata
Expose enough metadata for developers to understand how an extraction was performed.
Useful fields include:
• Strategy selected.
• Strategy selection reason.
• Provider/model identifier.
• Number of requests.
• Number of sampled frames.
• Number of recovery attempts.
• Validation status.
• Total elapsed time.
• Usage and cost estimates.
• Relevant warnings.
Keep this metadata separate from the extracted data.

───

19. Security, Privacy, and Reliability
19.1. Credentials
• Read credentials from documented secure configuration.
• Never commit real API keys.
• Never include credentials in exceptions.
• Redact authorization headers and secret fields from logs.
• Do not expose secrets in the playground.
19.2. Input safety
• Validate local paths and input types.
• Apply configurable limits to video size and duration.
• Avoid unbounded memory allocation.
• Handle malformed media safely.
• Do not automatically fetch arbitrary URLs.
• If remote URLs are later supported, implement appropriate SSRF protections and download limits.
19.3. Prompt injection in video
Visible text, subtitles, and audio transcripts may contain instructions intended to manipulate the model.
Treat video content as untrusted input.
The extraction prompt must clearly distinguish the developer's instructions from content observed inside the video.
The model should extract requested information rather than follow instructions displayed in the media.
This is a defense-in-depth measure, not a guarantee that prompt injection can always be prevented.
19.4. Provider retention
Document that sending a video to a provider may involve remote processing or retention according to that provider's terms and configuration.
Do not promise that data is never retained by providers unless the relevant provider terms substantiate that claim.
Use documented provider deletion mechanisms where appropriate.
19.5. Resource controls
Apply bounded limits to:
• Video duration and file size where configurable.
• Sampled frames.
• Refinement rounds.
• Recovery attempts.
• Concurrent work where concurrency is supported.
• Timeouts.
• Temporary disk usage.
A developer should not be able to accidentally trigger an unbounded extraction loop.

───

20. Engineering Standards
20.1. Code quality
• Use clear names and explicit types.
• Keep functions focused.
• Document public interfaces.
• Prefer small abstractions with real responsibilities.
• Avoid circular imports.
• Avoid unnecessary inheritance.
• Use protocols or abstract base classes only where they improve the adapter contract.
• Keep provider-specific code out of the core.
• Avoid broad exception handling that hides errors.
• Never silently fall back to a different provider or strategy.
20.2. Async behavior
The primary API should support asynchronous provider calls.
Do not block the event loop with CPU-heavy media processing or synchronous network operations.
Use appropriate asynchronous interfaces or offload blocking work when necessary.
If a synchronous convenience API is introduced, document its behavior carefully. Do not create a misleading wrapper that breaks inside an existing event loop.
20.3. Cancellation and cleanup
When extraction is cancelled:
• Stop additional stages when practical.
• Cancel provider requests where supported.
• Prevent new refinement requests.
• Release temporary resources.
• Preserve the original cancellation semantics.
Do not convert cancellation into an apparently successful empty result.
20.4. Dependencies
Before adding a dependency, ask:
1. Is it required for the MVP?
2. Can the standard library or an existing dependency solve the problem?
3. Does it materially increase installation size?
4. Is it maintained?
5. Is its license compatible?
6. Can it remain an optional extra?
Do not add a framework just because it provides abstractions that Suvix does not need.

───

21. Documentation Requirements
The repository must include the following documentation.
21.1. README
Explain:
• What Suvix does.
• What it does not do.
• Installation.
• A minimal working example.
• Supported providers.
• Native-video and selected-frame strategies.
• JSON Schema usage.
• Evidence semantics.
• Validation and recovery.
• Usage metadata.
• Known limitations.
• Playground setup.
• Testing.
• Contribution instructions.
The README must not promise cost savings until supported by reproducible results.
21.2. Provider documentation
For every provider, document:
• Installation extra.
• Credential configuration.
• Supported models and strategies.
• Schema limitations.
• Media restrictions.
• Usage reporting.
• Known limitations.
• Example.
• Integration test procedure.
Clearly distinguish verified capabilities from features that are planned or untested.
21.3. Architecture documentation
Document the pipeline, adapter contract, schema handling, evidence references, and dependency boundaries.
21.4. Privacy documentation
Explain local processing, remote provider requests, temporary files, provider uploads, cleanup, and the absence of persistent caching.
21.5. Benchmarking documentation
Explain how to run the benchmark suite, how ground truth is represented, which metrics are calculated, how costs are estimated, and how to interpret results.
21.6. Agent instructions
Maintain an AGENTS.md with concise repository-specific instructions.
It should point agents to this plan and the relevant architecture documents without duplicating the entire specification.

───

22. Implementation Milestones
Implement in the following order unless the repository audit identifies a concrete dependency that requires a justified adjustment.
Milestone 0 — Repository audit and design freeze
Tasks:
1. Inspect the repository.
2. Check existing code and tests.
3. Verify package configuration.
4. Verify supported Python versions.
5. Check current provider SDK documentation.
6. Confirm package naming constraints.
7. Create or update AGENTS.md.
8. Record key architectural decisions.
Required decisions:
• No persistent cache.
• No database.
• Explicit provider selection.
• JSON Schema as the public schema contract.
• Separate data and execution metadata.
• Native video and selected-frame strategies.
• Bounded recovery.
• Local playground.
• Benchmark-first evaluation.
Deliverables:
• Repository audit.
• Updated implementation sequence.
• Initial architecture decision records.
Do not start parallel implementation until the core boundaries are clear.
Milestone 1 — Core contracts and fake adapter
Implement:
• Public API skeleton.
• Request and option models.
• Result models.
• Evidence models.
• Usage and execution metadata.
• Error types.
• Adapter protocol.
• Schema validation.
• Basic strategy planner.
• Fake extractor for deterministic testing.
Tests must run without credentials or network access.
Exit criteria: The entire orchestration pipeline can be exercised using a fake adapter, including successful extraction, invalid schema, provider error, validation failure, and bounded recovery behavior.
Milestone 2 — Media metadata and selected-frame foundation
Implement:
• Video metadata inspection.
• Uniform frame sampling.
• Timestamp preservation.
• Temporary resource management.
• Frame reference registry.
• Segment offset handling.
• Configurable frame limits.
Do not implement sophisticated semantic frame selection yet.
Exit criteria: Deterministic media tests pass, timestamp behavior is documented, and temporary resources are cleaned up on success and failure.
Milestone 3 — First real provider: Gemini
Implement:
• Optional Gemini dependency.
• Credential handling.
• Native-video extraction where verified.
• Structured output handling where supported.
• Usage metadata.
• Provider error mapping.
• Upload lifecycle management.
• Integration tests.
Exit criteria: A real video can be processed through the public API with a real Gemini configuration, and the result includes data, validation, evidence where supported, usage, and execution metadata.
Milestone 4 — End-to-end playground
Implement the local Streamlit interface.
Use the public library API rather than reimplementing extraction logic in the UI.
Exit criteria: A developer can select a video, define a schema and instructions, execute extraction, and inspect the JSON, evidence, validation, and usage.
Milestone 5 — Selected-frame extraction and coarse-to-fine workflow
Implement:
• Selected-frame provider requests.
• Bounded coarse sampling.
• Candidate interval generation.
• Context expansion.
• Fine inspection.
• Timestamp normalization.
• Boundary handling.
• Execution-stage metadata.
Compare results with the existing native-video implementation.
Exit criteria: The workflow is deterministic where expected, resource limits are enforced, timestamps remain correct, and benchmark cases expose the trade-offs.
Milestone 6 — Validation and selective recovery
Complete:
• Structural validation.
• Deterministic semantic validation.
• Evidence validation.
• Selective recovery.
• Retry budgets.
• Error reporting.
• Recovery usage accounting.
Exit criteria: Malformed output is detected, recoverable errors can be corrected within the configured budget, and exhausted recovery returns a clear failure.
Milestone 7 — OpenRouter and TwelveLabs
Implement additional adapters using verified provider capabilities.
Reuse the core contracts.
Exit criteria: Each adapter passes the shared contract tests and at least one explicitly opted-in real integration test when valid credentials and supported models are available.
Milestone 8 — Benchmark suite
Implement:
• Evaluation task format.
• Ground-truth fixtures.
• Direct-provider baselines.
• Suvix strategy comparisons.
• Schema metrics.
• Semantic metrics.
• Timestamp metrics.
• Latency and usage metrics.
• Cost calculations.
• Reproducible result files.
Exit criteria: The project can compare strategies without misrepresenting incomparable inputs or unmeasured costs.
Milestone 9 — Release readiness
Complete:
• Public API review.
• Documentation.
• Package metadata.
• Wheel and source distribution builds.
• Clean-environment installation tests.
• Optional dependency tests.
• Security review.
• License review.
• CI.
• Versioning and release notes.
Exit criteria: A developer can install Suvix, run a documented example, use at least one real provider, and understand its limitations.

───

23. Recommended Agent Work Allocation
Use parallel coding agents only after Milestone 0 establishes the contracts.
Parallelism is useful when tasks have stable boundaries. It is harmful when agents independently invent incompatible interfaces.
Recommended sequence:
Agent A — Repository and architecture
Owns:
• Repository audit.
• AGENTS.md.
• Architecture documentation.
• Core decisions.
• Packaging baseline.
Agent B — Core contracts
Owns:
• Public API.
• Request and result types.
• Adapter protocol.
• Errors.
• Schema validation.
• Fake adapter tests.
This agent establishes the contracts other agents must follow.
Agent C — Media processing
Starts after the required contracts are agreed.
Owns:
• Metadata inspection.
• Frame sampling.
• Timestamp preservation.
• Temporary resources.
• Media tests.
Agent D — Gemini adapter
Starts after the adapter contract is stable.
Owns:
• Gemini integration.
• Native-video support.
• Structured output.
• Usage metadata.
• Integration tests.
Agent E — Playground
Starts after the public API is stable.
Owns:
• Streamlit UI.
• Schema editor.
• Provider selection.
• Results display.
• Temporary upload handling.
Agent F — Evaluation
Starts by designing the task format and metrics, then integrates after the first real adapter works.
Owns:
• Ground truth.
• Baselines.
• Metric implementation.
• Cost accounting.
• Benchmark reports.
Agent G — Additional adapters
Starts after the first provider and shared adapter tests are stable.
Owns:
• OpenRouter.
• TwelveLabs.
• Provider documentation.
• Contract compatibility.
Integrator / lead agent
Owns:
• Dependency coordination.
• Code review.
• API consistency.
• End-to-end testing.
• Release decisions.
Agents must not independently change public contracts without coordinating with the integrator.
Do not split work into numerous concurrent plans merely to maximize concurrency. A small number of independent, well-defined tasks is preferable to many agents modifying the same interfaces.

───

24. Definition of Done
Suvix MVP is complete when all of the following are true.
Product
• [ ] A developer can define an arbitrary supported JSON Schema.
• [ ] A developer can explicitly choose a provider and model.
• [ ] The public API can process a real video.
• [ ] Native-video extraction works for at least one verified provider.
• [ ] Selected-frame extraction works for a verified compatible provider.
• [ ] Strategy selection is explainable and overridable.
• [ ] Output is validated locally.
• [ ] Evidence references have documented semantics.
• [ ] Recovery is bounded and observable.
• [ ] Usage and execution metadata are separate from extracted data.
• [ ] A local playground is available.
• [ ] The benchmark suite can compare the main strategies.
Architecture
• [ ] The core does not import provider SDKs directly.
• [ ] Provider dependencies are optional.
• [ ] No persistent cache exists.
• [ ] No database is required.
• [ ] No implicit application persistence exists.
• [ ] Temporary resources are cleaned up appropriately.
• [ ] Provider limitations are explicit.
• [ ] There are no silent provider or model substitutions.
Quality
• [ ] Unit tests run without credentials.
• [ ] Adapter contract tests pass.
• [ ] Integration tests are opt-in.
• [ ] Timestamp and segment-boundary tests pass.
• [ ] Validation and recovery limits are tested.
• [ ] Error messages are actionable.
• [ ] Secrets are not exposed in logs.
• [ ] Documentation explains privacy and provider retention.
Packaging
• [ ] uv sync works in the repository.
• [ ] The package builds successfully.
• [ ] A clean environment can install the built distribution.
• [ ] Optional extras work.
• [ ] The documented downstream installation command works after publication.
• [ ] At least one example works end-to-end.
Quality (continued)
• [ ] Unit tests run without credentials.
• [ ] Adapter contract tests pass.
• [ ] Integration tests are opt-in.
• [ ] Timestamp and segment-boundary tests pass.
• [ ] Validation and recovery limits are tested.
• [ ] Error messages are actionable.
• [ ] Secrets are not exposed in logs.
• [ ] Documentation explains privacy and provider retention.
Packaging (continued)
• [ ] uv sync works in the repository.
• [ ] The package builds successfully.
• [ ] A clean environment can install the built distribution.
• [ ] Optional extras work.
• [ ] The documented downstream installation command works after publication.
• [ ] At least one example works end-to-end.
Research integrity
• [ ] Direct-provider baselines exist.
• [ ] Benchmark inputs and evaluation criteria are documented.
• [ ] Costs are measured or clearly labeled as estimates.
• [ ] No unsupported savings claims appear in documentation.
• [ ] Negative benchmark results are retained and reported.
• [ ] The project distinguishes structural validity from semantic correctness.

───

25. Final Architectural Decision Summary
The implementation must preserve these decisions unless the project owner explicitly changes them.

Area
Decision

Product
Open-source Python library for schema-guided video extraction

Package management
uv

Public schema
JSON Schema

Provider choice
Explicitly selected by the developer

Initial providers
Gemini, OpenRouter, TwelveLabs

Core modes
Native video and selected frames

Strategy planning
Small, explainable, rule-based planner

Frame sampling
Deterministic uniform sampling first

Advanced sampling
Bounded coarse-to-fine workflow

Output
Schema-defined data plus separate metadata

Evidence
Timestamps and real frame references where supported

Validation
Local structural and deterministic semantic checks

Recovery
Selective and bounded

Caching
None

Database
None

Persistent storage
None

Temporary files
Allowed when necessary, with cleanup

Playground
Optional local Streamlit application

Benchmarking
Direct-provider baselines and strategy comparisons

Cost claims
Only when supported by measurements

Release goal
Installable, documented, tested, and useful with a real provider


The guiding principle is simple: Suvix should handle the difficult, reusable extraction workflow while remaining a small library that fits into the developer's existing application. It should not take ownership of infrastructure that belongs to the application, and it should earn any claims of better accuracy or lower cost through reproducible experiments.
