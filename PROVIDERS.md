# Choosing a provider

Notes for filling in `models.txt`. Written after discovering that the first draft
picked providers with no criterion at all.

## The slug is the whole string, including the suffix

Every OpenRouter endpoint has a slug shaped
`provider[/variant][/region][/tier]` — for example `deepinfra/fp8`,
`baseten/fp4/us`, `google-vertex/us-east5`, `groq`.

**Yes, the whole thing goes after the `@`.** And you usually want it to:

| what you write | what it matches |
|---|---|
| `@deepinfra` | *every* DeepInfra endpoint — fp8, fp4, turbo, all regions |
| `@deepinfra/fp8` | only the fp8 variant, any region |
| `@baseten/fp4/us` | only that variant in that region |

A bare provider slug does **not** pin the quantization. DeepSeek V4.1 Flash is
served by DeepInfra at `deepinfra/fp8`, `deepinfra/fp8/flex` and
`deepinfra/fp8/priority`; other models have a single provider offering both fp8
and fp4. Writing `@deepinfra` leaves the precision up to the router, which is
exactly the variance the pin exists to remove.

`python sweep.py --models models.txt --check` prints the exact slug for every
endpoint under a "slug (put this after @)" column. Copy from there.

### "First-party models have one endpoint" — not true

An earlier version of this note said to skip the `@` for first-party models on the
grounds that they have a single endpoint. They don't. OpenRouter routes Claude
models through Anthropic-direct, Amazon Bedrock and Google Vertex; OpenAI and
Google models have similar resale paths.

Drop the vendor-based rule. The only rule that is always right: **run `--check`
and pin anything with more than one endpoint.**

Lowercase slugs are what the docs specify. Capitalised display names appear to
work — the existing llama run pinned `@Groq` and every one of 598 calls was
served by Groq — but prefer the documented form.

## What to actually choose on

In rough order of importance for a benchmark, which is *not* the same order you'd
use in production:

1. **Quantization.** The big one. `bf16` and `fp16` are near the reference model;
   `fp8` is a mild approximation; `fp4` and `mxfp4` are aggressive. These are
   different systems and will give different close rates. Prefer the highest
   precision you can afford, and record what you used — it belongs in the paper's
   methods section.
   **When the only choices are `fp4` and `unknown`:** take the declared `fp4`.
   "Unknown" means undeclared, not undistorted — it may well be fp4 too, and you
   cannot write it up as anything. A declared quantization is a complete
   specification in the methods section. The exception is an undeclared endpoint
   served by the model's own vendor, which is more likely reference-precision
   serving than a quantized resale.

   Where a model is only available heavily quantized, phrase findings as "as
   served on OpenRouter" rather than as a claim about the model's ceiling.

2. **Supported parameters.** If a provider ignores `temperature`, your pinned
   sampling config is fiction. `require_parameters` makes OpenRouter skip any
   provider that doesn't support everything in the request.
3. **Uptime (24h) and `status`.** `status: 0` is healthy; negative values mean
   degraded. A provider at 92% will stall a 120-run sweep.
4. **`max_completion_tokens`.** Must exceed your `max_tokens` — 900 when
   `--scratchpad` is on. Rarely a problem, occasionally is.
5. **Price.** Last. The whole Phase 1 sweep is roughly $40–60, so a 2x difference
   in provider price is a couple of dollars.
6. **Longevity.** You intend to rerun this over time. A provider that still exists
   next year is worth more than one that's a cent cheaper.

## What `/us` and other regions mean

The region is a slug segment: `sail-research/fp4/us`, `google-vertex/us-east5`.
It controls where inference physically happens, which affects latency and, if it
matters to you, which jurisdiction processes the text.

For this benchmark: **mostly who cares** — the content is synthetic and contains
no personal data. Two caveats worth a moment:

- Pick one and stay on it. Region variants have separate uptime figures and can
  behave differently; drifting between them reintroduces unlogged variance.
- Region slugs are *not* the data-residency mechanism. Real in-region routing is a
  Business/Enterprise feature using `https://eu.openrouter.ai` or
  `https://us.openrouter.ai` as the base URL. If F-Secure has a policy requiring
  EU processing, that's the lever, not the provider suffix.

## Don't forget the grader

`DEFAULT_GRADER` is unpinned. In the 2026-10-27 run the seller and buyer were
correctly served by Groq (598 calls) while all 120 grader calls went to **Amazon
Bedrock** — chosen by the router, not by you. Anthropic-direct, Bedrock and Vertex
can differ, and the grader is the one model in this study that must not drift.
Pin it the same way you pin the models under test.
