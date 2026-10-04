# Final production handoff — 2026-10-04

Live: https://kabuforge.com/ and https://kabuforge.com/ja/ . All 22 sitemap URLs passed production HTTP 200, self-canonical and no-noindex checks. Missing route 404; www path/query-preserving 301. Full evidence: production-check.json.

Sites version 2: appgprj_6ac240a903108191b3914e0c4ec478d9~appgver_fe2f2ca2f0a08191b164fc573787f1fa
Deployment succeeded: appgdep_6ac245ff976c8191bcdf808b15d528a7
Sites source SHA: e7a3bfc3ddf4278374e8a48cdf978820b062af11
Public GitHub PR head: 9c44769e76e4ebd947a44cf737ef96ba10cf3f5c
Product content source: c922d5439f6f018c140de14b6056f82b901dc434

Google Search Console ownership verified; live homepage test reports URL can be indexed; homepage index request accepted into priority crawl queue. It is not indexed yet. Initial sitemap fetch failed despite HTTP 200 smoke test; needs later Search Console recheck. Bing Google sign-in is open for user handoff. No account credentials were entered or persisted by the agent.

Production screenshot: production-home.jpg; Google request proof: google-index-request.jpg. Build checker and website CI passed. Keyboard Enter activates skip-to-content (#main); comprehensive accessibility and 200% zoom remain unverified.

Rollback: deploy the first successful saved version appgprj_6ac240a903108191b3914e0c4ec478d9~appgver_763385b058648191aefbcf9ca23f3b8d. Preserve DNS for content rollback. WEBSITE_DEPLOYMENT.md identifies task-created DNS and rule for domain rollback. Root HTTP redirect is hosting-provider 302, and generated alias uses canonical rather than separate noindex/redirect; these are outstanding SEO improvements, not completion claims.

Final Sites source 9dcfd1be1d0fd0084f575a5b53e3a49e9e576ee1, successful deployment appgdep_6ac246e51bf08191b57ac4b959c703ef, version appgprj_6ac240a903108191b3914e0c4ec478d9~appgver_f6f2b554320c819187327f56346266d7. Alias _headers noindex configuration was tested but hosting does not emit that header; separate alias noindex remains unresolved. Production domain emits no noindex header. All 22 pages rechecked after that deployment. PR 6 merged as a1462ad3c26d0750f1507683649c0248c100e05d after all six release-foundation jobs, website CI and application CI passed. GitHub About official URL saved. Public code includes the tested alias header declaration for portability; do not treat declaration alone as runtime success.

