# Security Policy

Comic Drama Workflow integrates local files, cloud GPU runtimes, model
providers, TTS services, ComfyUI workflows, and user-provided creative assets.
Security issues can affect credentials, private assets, generated media, or
provider accounts.

## Supported Versions

The project is pre-1.0. Security fixes target the latest `main` branch until
tagged releases become stable.

| Version | Supported |
| --- | --- |
| main | Yes |
| 0.1.x | Best effort |

## Reporting A Vulnerability

Please do not open a public issue for sensitive reports.

Report privately to the repository maintainer through GitHub Security Advisories
or another private contact channel listed by the maintainer.

Include:

- affected commit or version
- vulnerable component
- reproduction steps
- expected impact
- whether credentials, user media, or generated assets are exposed

Do not include real API keys, SSH credentials, private generated videos,
private reference images, or provider tokens in the report.

## Security Areas We Care About

- API key and token handling
- `.env` and local credential leakage
- SSH tunnel and cloud GPU configuration
- ComfyUI workflow injection
- file path traversal in project assets
- untrusted uploads
- provider gateway request signing
- generated media retention and export
- dependency risk
- accidental commit of model weights or private assets

## Operational Guidance

- Keep `.env` local and out of commits.
- Do not commit `workspace/`, `outputs/`, `tools/`, model weights, or cloud
  credentials.
- Use least-privilege provider API keys.
- Rotate keys if logs or screenshots may have exposed them.
- Review third-party ComfyUI nodes and model licenses before deployment.
