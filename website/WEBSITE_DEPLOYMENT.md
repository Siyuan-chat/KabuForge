# Deployment and rollback

Site: appgprj_6ac240a903108191b3914e0c4ec478d9. Astro static export, Node 24.19.0, pnpm 11.25.0; dependencies pinned by pnpm-lock.yaml.

Build: `pnpm install --frozen-lockfile`, `pnpm run build`, `pnpm run check`.
Source content is pinned separately to public KabuForge c922d5439f6f018c140de14b6056f82b901dc434. Website builds never install the Python project.

Private initial deployment succeeded on 2026-10-04: source 4d5e0bd0ebd5820a853319b348746e37bca30e53, deployment appgdep_6ac241f5c0dc81919eba9a25611223c7, version appgprj_6ac240a903108191b3914e0c4ec478d9~appgver_763385b058648191aefbcf9ca23f3b8d.

Use Sites native save/deploy tools with the exact pushed website commit. Source credentials stay in memory/stdin only. The portable packager requires Bash, unavailable here: the source push completed but packaging failed. Recovery used the unchanged bundled prepare-site-build.cjs, then native Windows tar; backend accepted the archive. Archive contains dist/.openai/hosting.json and normalized static assets, not Python software or private files.

Domain before changes: Cloudflare zone kabuforge.com had zero DNS records, no root A or www record. Required root DNS-only A values: 162.159.143.30 and 172.66.3.26. Domain validation TXT values are retained in the launch handoff. No email records existed; no email configuration is introduced.

Rollback: select a previously successful saved Sites version and deploy it using the same project ID. Preserve current DNS if only content changes. For a domain setup fault, remove only records created by this launch, restoring the observed empty zone; do not change nameservers or registration. The first deployment has no earlier website version, so use the retained private version or make the Site private if public launch must be withdrawn.

Local preview uses scripts/preview.mjs on 127.0.0.1:4321, adds X-Robots-Tag noindex,follow, and returns real 404. The server is a task-owned retained exec session, not an unattended service. Stop with Ctrl+C in that session.

Public deployment succeeded: appgdep_6ac24291cb248191bf7cecdbf5907935. kabuforge.com active with active SSL. Created DNS records: two root DNS-only A records as above, www proxied CNAME to kabuforge.com, _openai-site-verification TXT, _cf-custom-hostname TXT, and root Google verification TXT. Keep verification records to preserve ownership/certificate. Cloudflare rule KabuForge www to canonical (0d009f17d4364b788a5e4c8459cba7e7) returns 301, preserving query strings. Domain rollback must also remove only this task's rule/records, and should preserve Google ownership TXT unless abandoning the property. Source and deployment are versioned; redeploy the successful first saved version for content rollback. No new paid plan purchased.
