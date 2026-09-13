# Agent Note: Recover a turn that ends on a text-form tool call

Status: proposed

English | [中文](2026-09-12-text-form-tool-call-recovery.zh.md)

## Problem

A model can write a tool call into its text content instead of the wire `tool_calls` field. The harness then reads a plain assistant message, concludes the model owes no further response, and closes the turn. The user sees raw markup and a session that stopped for no stated reason.

The termination rule lives in [`ReactLoopAgent.step`](../../../../packages/core/agent-loop/src/agent.ts) and decides on content-block type, never on text:

```ts ignore-check
if (finish.kind === 'max-tokens') return { kind: 'max-tokens' }

const toolCalls = message.content.filter(block => block.type === 'tool-call')
if (toolCalls.length === 0) return { kind: 'completed' }
```

A `tool-call` block exists only where a provider translated the wire `tool_calls` field, so a call the endpoint left in `content` is invisible to this filter. The rule is correct for its own contract and stays as it is; what it lacks is a consumer that recognizes the one case where a plain text message is a failed tool call rather than a finished answer.

Measured evidence from 13 local sessions, all routed to `ollama/Qwen3.8-27B`, sampled at 2026-09-12T02:18:59Z:

| Presentation mode | Sessions | Assistant messages | Wire tool calls | Text-form tool calls | Rate | Turn end after each |
|---|---|---|---|---|---|---|
| `ptc` | 9 | 1538 | 1593 | 6 | 0.39% | `completed` ×6 |
| `native` | 4 | 15 | 14 | 0 | 0.00% | — |

Three facts decide the design. The failure is rare, so the model recovers on a retry rather than repeating the mistake. Every occurrence closed its turn as `completed`, so no error, log entry, or user-visible signal distinguishes it from a finished answer. The `native` sample is 15 messages and supports no comparison against `ptc`.

The emitted markup is also malformed, in a different way each time:

```text
</parameter>
</parameter>
</function>
```

```text
<description>
Read 3090 token URL from log
</parameter>
```

The first sample closes `parameter` twice; the second opens `description` as a bare tag and closes it as `parameter`. Both were produced with correct tool knowledge — the emitted names `run_code`, `code`, and `description` match the schema the request carried — so the model read its tools and missed only the output channel.

## Proposal

Add `@deepseek-ai/dsh-text-form-tool-call-recovery` under `packages/guard/`, a loop-hygiene plugin that listens on `agent/turn-stopping` and asks the model to resend the call through the tool channel. The [agent-loop state machine](../../implemented/simplification/2026-07-24-agent-loop-observable-state-machine.md) defines that extension point: a listener that objects records steering with `agent.steer()`, and the loop re-reads its inbox before committing the boundary. The plugin needs no change to `agent-loop`.

### Detection

The listener acts only when all of the following hold for the turn's last assistant message:

- The message carries no `tool-call` content block. A turn that dispatched calls needs no recovery.
- Its text matches a configured marker. The defaults cover the markup this repository has observed: `<tool_call>`, `<function=`, and `<parameter=`.
- The plugin has not already recovered this turn more times than `maxRecoveriesPerTurn` allows.

Detection reads `agent.session.deriveMessages()` and takes the last `assistant` message, the access pattern an existing `agent/turn-stopping` listener already uses.

### Recovery

The listener calls `agent.steer(createUserMessage(...))` with a corrective message attributed to `{ kind: 'plugin', plugin: 'text-form-tool-call-recovery' }`. Steering targets the next step and wakes the driver, so the same turn runs one more model request instead of closing. The message states the observable facts in the model's own terms: the previous reply described a tool call in text, no tool ran, and the call must be reissued through the tool-call channel.

Per-turn recovery counts live in a `WeakMap<Agent, ...>` keyed by turn number, matching the in-memory bookkeeping [repeat-tool-reminder](../../../../packages/guard/repeat-tool-reminder/README.md) uses. A cap is mandatory: an unconditional listener on this event forces continuation forever, which is why the Claude Code and Codex hook bridges document self-limiting as the caller's duty.

### Configuration

| Field | Default | Meaning |
|---|---|---|
| `markers` | `['<tool_call>', '<function=', '<parameter=']` | Substrings that identify a text-form tool call |
| `maxRecoveriesPerTurn` | `1` | How many times one turn may be steered for this reason |
| `enabled` | `true` | Whether the listener acts at all |

An empty `markers` list, a `maxRecoveriesPerTurn` below 1, or a non-integer count throws at plugin load. Misconfiguration never degrades to a default.

### Package layout

| Path | Content |
|---|---|
| `packages/guard/text-form-tool-call-recovery/package.json` | Manifest mirroring the `repeat-tool-reminder` peer and dev dependency set |
| `packages/guard/text-form-tool-call-recovery/tsconfig.json` | `tsconfig.base.json` extension with `rootDir: src`, `outDir: lib/types`, and workspace references |
| `packages/guard/text-form-tool-call-recovery/src/index.ts` | `name` / `Config` / `apply` function-plugin exports and the listener |
| `packages/guard/text-form-tool-call-recovery/README.md` | Package contract, Model Experience, and Known Limitations sections |
| `packages/guard/text-form-tool-call-recovery/tests/` | Unit, disposal, and real-composition specs |

The package publishes no `./invariant`: the recovery counter is private to one listener and exposes no independently observable relation. Its README records that reason and the package joins the `verify-package-invariants` allowlist.

Mounting is a deployment choice. The plugin belongs in the `base` bundle alongside the other loop-hygiene guards, because the failure it covers is a property of the model route rather than of any one profile.

## Prior art

Two lines exist for this failure, and they diverge on where the fix lives.

Recovery through the model is the documented practice in [LangChain's deepagents fault-tolerance guide](https://docs.langchain.com/oss/python/deepagents/fault-tolerance), which separates transient failures that a runtime retries from parsing failures that belong back in front of the model. [Wink](https://arxiv.org/html/2602.17037) reports that targeted course-correction resolves 90% of agent misbehaviors that a single intervention can fix, measured over more than 10,000 real trajectories. Content from both sources was rephrased for compliance with licensing restrictions.

Parsing the text is what `goose` chose: an XML fallback parser for the `<function=name>` form, plus a heavier "toolshim" path. Its own [follow-up issue](https://github.com/aaif-goose/goose/issues/8269) records the cost — the parser handles that one format and not Kimi's, so each model family arrives as another format to support.

The upstream defect is documented on both sides. [ollama#16686](https://github.com/ollama/ollama/issues/16686) reports that the `qwen3coder` parser disengages when the model omits the opening `<tool_call>` tag, describing the omission as a known model flub, and the whole call reaches the client as content. [QwenLM/Qwen3.6#178](https://github.com/QwenLM/Qwen3.6/issues/178) reports the same class of drift from the chat template's tool-call format, including a stray closing tag. Both match the malformed samples above.

## Alternatives considered

**Parse the text into a real tool call, in the provider or a shared middleware.** Rejected on three grounds. The observed input is malformed in a different way each time, so a parser either rejects it or produces wrong arguments. Under `ptc` presentation the only callable tool is `run_code`, which executes a program, so wrong arguments mean running the wrong code — a worse outcome than one extra model request. And a Qwen-specific markup format inside a provider translation layer owns no contract that provider is responsible for; `goose`'s follow-up issue shows the per-family maintenance that follows.

**Fix the model endpoint alone.** Necessary but insufficient. `ollama#16686` and `QwenLM/Qwen3.6#178` place part of the defect in the model's own output, which no parser configuration reaches. The endpoint fix lowers the rate; it does not make the harness safe against a route that regresses.

**Change the agent-loop termination rule.** Rejected. Making `step()` treat suspicious text as an implicit continuation moves a model-specific heuristic into the loop's decision path, where every consumer inherits it. `agent/turn-stopping` exists precisely so this class of policy lives outside that path.

**Configuration changes alone: `native` presentation, lower reasoning effort, or restored compaction.** Rejected as a fix. The `native` sample is 15 messages against 1538 for `ptc` and supports no conclusion, and the failure appeared in a 32-message session as well as a 671-message one, so context length does not explain it. Restoring compaction is worth doing for its own reason — an unbounded context eventually exceeds the window — and is unrelated to this defect.

**An external repair proxy in front of the endpoint.** Rejected as the primary fix. It works, and a deployment already running one keeps the benefit, but it moves harness robustness into per-user infrastructure and covers only the routes that user proxies.

**Report without recovering.** Rejected as insufficient on its own. Surfacing the event removes the silence, which is half the problem, but leaves the turn dead and the user retyping. Recovery subsumes it: the steered message is itself the record, attributed to the plugin and reconstructable from the session log.

## Acceptance criteria

- A session whose model emits a text-form tool call runs another step in the same turn instead of closing, and the session log carries the steered message with its plugin source.
- The same session closes normally once `maxRecoveriesPerTurn` is exhausted, with no forced continuation beyond the cap.
- An assistant message that dispatched real tool calls never triggers recovery, and neither does one whose text contains no configured marker.
- An empty `markers` list and a `maxRecoveriesPerTurn` below 1 each fail at plugin load with a message naming the field.
- A real-composition spec boots a test-only `cordis.yml` through the Loader and asserts the extra step and the injected message, per the [product-visible plugin rule](../../../../packages/AGENTS.md).
- A disposal spec disposes the fiber and observes the listener removed.
- A recorded-session snapshot pins the model-visible corrective text, since the message reaches a model request.
- `pnpm run test`, `pnpm run typecheck`, `pnpm run lint`, `pnpm run hygiene`, and `pnpm run doc-sync` pass, and the generated configuration catalog contains the new `Config` fields.

## Risks

- **Forced continuation without end.** A cap bug turns the listener into an infinite turn. The cap defaults to 1, validates at load, and a spec asserts the turn closes once it is spent.
- **False positives.** A model legitimately discussing this markup — quoting a log, writing documentation about it — draws an unneeded correction. The no-`tool-call`-block condition excludes the common case, and the cost of a wrong nudge is one extra request.
- **The model may not comply.** Nothing guarantees the resent call arrives on the wire. At a 0.39% failure rate a single retry is very likely to succeed, and the cap bounds the loss when it does not.
- **One extra model request per occurrence.** Accepted: the alternative is a dead turn and a manual retry that costs the same request plus the user's time.
- **Marker defaults age.** The defaults cover the observed markup, not every family; Kimi's delimiters are already known to differ. `markers` is configurable for that reason, and a new family is a config change rather than a code change.
