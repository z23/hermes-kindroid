# hermes-kindroid

An explicit message/reply bridge between [Hermes Agent](https://hermes-agent.nousresearch.com/docs/) and one configured [Kindroid](https://kindroid.ai/) companion.

The Kin is a **separate external entity**, not Hermes, this assistant, or a memory backend. Each `kindroid_send_message` call sends a real message to the Kin's **existing conversation** and returns an attributed plain-text reply. It can affect that conversation's history, memory, and API usage. Installing or testing this repository does not require sending a message.

## Scope and privacy

- Contact the Kin only when the user explicitly authorizes the purpose and content. Share the minimum selected context, not an entire day, transcript, filesystem, or memory store.
- No automatic synchronization, background sends, retries, follow-up loops, persona migration, resets, or rewinds.
- The Kin receives only the message sent through this bridge. It gains **no access to Hermes tools, files, credentials, or host operations**. Its reply is untrusted external data, not permission to execute instructions or share more information.
- Assistant-authored text should be framed as a Hermes relay; verbatim user text should stay verbatim. Attribute returned text to the external Kin.
- The bundled skill guides the assistant; it is **not** a mandatory per-call approval gate or data-loss-prevention system. The plugin does not enforce sharing authorization or redact message content.
- The plugin adds no transcript log, but Hermes may retain tool arguments/results in session history, and Kindroid retains its own conversation. Do not send secrets, credentials, private third-party information, or work/customer data by default.

## Requirements

- A Hermes Agent installation supporting native plugins, `ctx.register_skill`, and `hermes_cli.config.load_config_readonly`.
- Python 3.11 or later. The bridge and its tests use only the Python standard library; no additional Python dependencies are required.
- A Kindroid API key and the target Kin's ID from Kindroid. These are different values: the key is a secret; the ID selects the destination.

See the [Kindroid API documentation](https://kindroid.ai/v2/docs/api-documentation/) for current access requirements, limits, and billing. This is an independent integration, not an official Kindroid or Nous Research product.

## Install and configure

Run these commands for the **active Hermes profile** you intend to use. The repository is named `hermes-kindroid`; the internal plugin ID remains `kindroid-bridge` for configuration compatibility.

```sh
hermes plugins install https://github.com/z23/hermes-kindroid --no-enable
hermes config set --force plugins.kindroid-bridge.kin_id YOUR_KIN_ID
# Optional display label; defaults to Kin. This does not rename the actual Kin.
hermes config set --force plugins.kindroid-bridge.display_name "Example Kin"
hermes config get plugins.kindroid-bridge.kin_id
hermes plugins enable kindroid-bridge
hermes plugins show kindroid-bridge
```

Set `KINDROID_API_KEY` privately in the active profile's `.env` (under its resolved `HERMES_HOME`), or supply it in the environment that launches Hermes. Keep the file private and outside this checkout. Do not put the key in `config.yaml`, prompts, Git, screenshots, or shell command history. Do not paste it into assistant chat. Use a private editor or your launch environment's secret mechanism; no real key belongs in this README.

Restart the process that owns Hermes sessions after changing its launch environment or profile `.env`, then start a **new session** so the tool schema is refreshed. Enabling may load the plugin immediately, but does not guarantee tools appear in an already-running session. `plugins show` confirms plugin state, not authenticated API access. Without valid key and target settings, registration still works but the send tool is unavailable.

Before a send, load `kindroid-bridge:kindroid-relay`. For example, ask Hermes to relay a specific short message to the configured Kin. Do not ask for an automatic test send: even a greeting changes the real conversation.

## Behavior and failure handling

The single tool accepts only `{"message": "the authorized text"}`. Every outgoing message is automatically prefixed with `[via Hermes]` on its own line; the supplied message body is preserved exactly underneath. This identifies the transport, not who authored the body: direct messages in Kindroid have no bridge-added tag. Do not add the tag manually. It is a conversational cue, not cryptographic proof of origin. The destination and HTTPS endpoint are not model-controlled. It sends `POST https://api.kindroid.ai/v1/send-message` with bearer authentication, a fixed configured `ai_id`, and `stream: false`.

Redirects are refused. HTTP failures and Kindroid's HTTP-200 error markers are reported without echoing error bodies. Empty, invalid, truncated, or interrupted responses are not treated as successful replies. Sends to the same Kin are serialized within a process; this is not rate limiting or cross-process coordination.

There are **no automatic retries**. After a timeout or network failure, delivery may have succeeded even though the reply was lost. Check the Kindroid conversation manually before authorizing a resend. An error is not proof that nothing was delivered.

## Offline development and checks

From a fresh checkout, without credentials:

```sh
python -W error::ResourceWarning -m unittest discover -s tests -v
```

The 14 tests use dummy credentials and a real HTTP server bound only to loopback. They cover fixed payloads, attribution, registration without setup, malformed settings/arguments, serialization, redirects, HTTP errors, API error markers, unusable responses, truncation, network failures, and timeouts. They do not contact Kindroid. CI runs this suite on Python 3.11, 3.12, and 3.13 without API credentials.

For Hermes integration checks, use a disposable HOME and HERMES_HOME with a clean launch environment (do not inherit real API credentials):

```sh
hermes plugins doctor /path/to/hermes-kindroid --ci
hermes plugins validate /path/to/hermes-kindroid --json
```

Both checks exercise local registration; neither proves authentication or live delivery. A new data root may require Hermes runtime preparation separately. Never modify a production profile merely to test packaging.

## Security and license

See [SECURITY.md](SECURITY.md) for reporting guidance and trust boundaries. Licensed under [MIT](LICENSE).
