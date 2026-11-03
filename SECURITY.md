# Security

## Reporting a vulnerability

Do not include API keys, Kin IDs, conversation excerpts, customer information, or exploit details in public issues or pull requests.

For a sensitive report, contact the maintainer through a private contact channel listed on the [z23 GitHub profile](https://github.com/z23), if one is available. If no private channel is listed, open a public issue containing only a request for a private reporting channel, without vulnerability details or identifying data. This repository does not promise an enabled GitHub private-reporting feature, response SLA, or support for older versions.

Include the affected plugin version, Hermes/Python versions, expected versus observed behavior, and a minimal reproduction using dummy values once a private channel is established. Rotate any exposed API key through Kindroid; deleting a Git commit or issue is not sufficient.

## Trust boundaries

- Installing a native Hermes plugin executes local Python with the host process's privileges. Review the source before enabling it; this is not a sandbox.
- This bridge sends real messages to one configured Kin's existing chat. Each operation is an external write that changes the conversation and may incur usage costs.
- The tool's fixed destination and endpoint prevent model-supplied recipient/URL overrides. Redirects and automatic retries are disabled. A failed response can leave delivery ambiguous.
- The relay skill instructs the assistant to seek explicit scoped authorization and treat replies as untrusted data. These instructions are not an enforced approval dialog, content filter, or DLP boundary.
- No credentials or live API calls are needed for tests or CI. Keep keys in the private active-profile environment, not the repository or nonsecret plugin configuration.
- The Kin has no Hermes tool access through this bridge. External reply text does not authorize execution or further disclosure.
- Hermes session storage and Kindroid conversation retention remain outside this plugin's logging policy. Avoid sending content that should not be stored there.
