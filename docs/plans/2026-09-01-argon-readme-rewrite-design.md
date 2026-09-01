# Argon README Rewrite Design

## Audience

The README serves two readers:

1. Public portfolio visitors who need to understand Argon's purpose and value quickly.
2. Technical readers who need enough architecture and operational evidence to judge whether it is a real system.

The document remains English-first.

## Narrative

Lead with the product, then prove it with the architecture:

1. Clear one-sentence positioning.
2. The English system panorama.
3. What Argon helps the operator understand and decide.
4. A compact overview of the research surfaces.
5. The five-repository quant-desk ecosystem and Argon's role within it.
6. System architecture and data flow.
7. Engineering guarantees that matter to an external technical reader.
8. A minimal local quick start.
9. Focused links for testing, deployment, design, plans, and deeper documentation.

## Ecosystem

Show the desk as:

`livewire → signal-lab → apex → argon → xenon`

Argon is the analytics and decision surface. It consumes market and research context, persists evidence, exposes research views, and hands the human operator into Xenon for execution. Each project link and responsibility must be verified from the current repositories before publication.

## Content Rules

- Remove `Four Disciplines (no exceptions)` and other manifesto-style language.
- Replace slogans with concrete product behavior and system evidence.
- Merge overlapping `Surfaces`, `Argon Terminal`, `Architecture`, and `Services` content.
- Keep the architecture diagram high in the document.
- Keep durable persistence, defined-risk output, source provenance, realtime failover, typed API contracts, and controlled mutations as concise engineering guarantees.
- Remove private machine addresses and excessive environment detail from the public README.
- Move long inventories, glossary material, operational detail, and historical milestones behind links.
- Verify the current version, implemented UI/provider state, process topology, source order, and deployment claims against repository evidence.
- Keep the README concise enough to scan, targeting roughly 140–180 lines.

## Acceptance

- A new reader can state what Argon is after the opening and diagram.
- The README clearly locates Argon in the five-repository desk.
- Technical readers can see the real data flow, runtime components, persistence boundary, and validation commands.
- No private infrastructure coordinates or stale release claims remain.
- All local links resolve, Markdown passes `git diff --check`, and the embedded SVG renders correctly.
