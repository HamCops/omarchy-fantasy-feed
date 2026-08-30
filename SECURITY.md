# Security

## Supported versions

Security fixes are provided for the latest published release of Fantasy Feed.

## Reporting a vulnerability

Please use the repository's private GitHub security-advisory form rather than a
public issue:

https://github.com/studioxvii/omarchy-fantasy-feed/security/advisories/new

Include the affected version, reproduction steps, and the impact you observed.

## Trust boundaries

Omarchy plugins run unsandboxed with the current user's permissions. Fantasy
Feed starts one bundled Python helper, reads public ESPN NFL JSON endpoints over
HTTPS, writes a mode-`0600` last-good cache, and stores favorites plus display
preferences in the user's Omarchy configuration directory. It does not request
credentials, use `sudo`, install packages, execute downloaded code, or require
an ESPN or fantasy-platform account.

The ESPN endpoints are public but undocumented and unsupported. Responses are
bounded and validated before they enter the scoring model; a failed refresh
retains the last valid snapshot instead of accepting partial provider data.
