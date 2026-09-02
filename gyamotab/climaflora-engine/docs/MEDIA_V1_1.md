# ClimaFlora — Media v1.1

## Purpose

Media remain a purely illustrative layer. They never contribute to climate, soil, combined, regulatory or recommendation scoring.

## Discovery order

1. Exact Wikidata `P225` scientific-name match.
2. Wikimedia Commons image attached by Wikidata `P18`.
3. If no usable P18 image exists, files from the exact Wikidata `P373` Commons category.
4. If no legally admissible image exists, the ClimaFlora generic botanical illustration supplied for this release is shown by the frontend.

No fuzzy scientific-name matching is allowed.

## Uncertainty policy

A media asset can be legally and taxonomically attachable while its visual label remains doubtful. Media v1.1 keeps such an asset and records:

- `display_blurred = 1`
- `ambiguity_reason`

The frontend deliberately blurs these images and labels them as uncertain. This flag is visual metadata only and has `image_scoring_effect=false`.

Examples of media uncertainty include filenames containing terms such as `or`, `possibly`, `cf.`, `aff.`, `unknown`, `uncertain` or `?`, and P373 category members whose filename does not explicitly mention the first two scientific-name tokens.

A genuine taxonomic ambiguity (multiple Wikidata items resolving to the same exact P225 name) is different: the image cannot be attached safely to a ClimaFlora taxon and is therefore not selected. The generic fallback is shown instead.

## Legal gate

Allowed: CC0, Public domain, CC BY, CC BY-SA.

Rejected: NC, ND, empty/unknown licence, unsupported or unsafe URLs.

## Frontend fallback

When no admissible image is available, the frontend uses the exact user-supplied 140×140 ClimaFlora botanical illustration embedded in `app/static/media-v1.css` as a data URI. It replaces the former emoji placeholder.

## Runtime

- app/package: `0.9.44`
- scientific method: unchanged `climaflora-score-0.6.0`
- scientific catalog: unchanged `2.0.0`
- media ingester: `1.1.0`
