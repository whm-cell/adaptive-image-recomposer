# Render-call boundary and artifact policy

This policy separates local planning from an external image-provider request. It exists to prevent accidental paid or quota-consuming retries; it is not a provider control plane.

## What the Skill can and cannot do

The Skill can validate local inputs, compile a prompt, withhold an unauthorized invocation, bind one human decision to one request, and record the observable outcome. These actions happen before or after the provider call.

The Skill cannot cancel a request after the provider accepted it, determine whether a failed request was billed, issue a refund, force the provider to return an image, or recover an artifact the provider never returned. Those behaviors belong to the provider and the calling host.

Therefore, “stop” has one precise meaning: **do not start the next external request**. It never means abort an in-flight generation or discard a result.

## State sequence

1. `AWAITING_RENDER_AUTHORIZATION`: compilation is complete; no provider call has started.
2. `RENDER_CALL_AUTHORIZED`: one explicit human decision is reserved for exactly one external request.
3. One observable terminal outcome is recorded:
   - `ARTIFACT_RETURNED_DISPLAY_REQUIRED`;
   - `PROVIDER_FAILURE_REAUTHORIZATION_REQUIRED`;
   - `AWAITING_RENDER_AUTHORIZATION` after `cancelled_before_call`.
4. A returned artifact is shown before or alongside QA. QA labels it but never suppresses it.
5. Any later provider call returns to the human authorization checkpoint.

`select` authorizes a design direction. It does not authorize generation. `authorize-render` records a human instruction but does not invoke a provider. The calling model or host remains responsible for making exactly one request and then using `record-render`.

## One-use authorization

An authorization is valid only when all of these remain unchanged:

- source-manifest digest;
- route fingerprint;
- selected strategy;
- renderer;
- reconstruction-plan digest;
- final-prompt digest.

It is human-authored, covers one call, and is closed after `returned`, `provider_failure`, or `cancelled_before_call`. Do not reuse a closed authorization. The ledger refuses a second active authorization and rejects a reused authorization ID.

The initial generation uses `attempt_kind=initial`. A local correction to a returned image uses `targeted_repair`. A new request after a provider returned no artifact uses `provider_retry`. Both follow-up kinds require a new explicit human instruction. Automatic retries are zero. The policy ceiling is two human-authorized follow-up calls across repair and provider-retry attempts; this is a ceiling, not permission to spend them.

## Returned artifacts

If the provider returns an image:

- record its resolved path, digest, and byte size;
- surface that exact artifact to the human immediately;
- keep the artifact visible even if OCR, object count, association, integration, or visual QA fails;
- describe failed QA as a property of the candidate, not as absence of a result;
- ask before spending another generation call.

A host integration should treat `artifact_returned_display_required` and the machine response's `result_image` artifact as a presentation obligation. Presentation and acceptance are independent states.

## Provider failure

If a started request returns no usable artifact, record `provider_failure`, show the provider error or status, and state that billing is unknown unless provider evidence says otherwise. Do not fabricate a preview, claim that the Skill saved the charge, or automatically retry. A retry requires a new human authorization.

If no provider request was started, record `cancelled_before_call`. This closes the one-use authorization so it cannot later be replayed; it does not claim anything about provider billing beyond the local observation that no call was recorded.

## Host integration checklist

- Verify `render-boundary.json` before requesting authorization.
- Keep the authorization and ledger in the job directory.
- Invoke the provider once, synchronously or with a tracked job ID.
- Record exactly one terminal outcome.
- Forward returned media even when later validation fails.
- Do not map QA failure to hidden output or automatic regeneration.
- Require a new human message before every follow-up call.
