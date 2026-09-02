# Phase 12 — Plugin Adapters & Future Sections

Implemented a section adapter contract and registry for Blogger, News, Sports and future sections.

## Important compatibility rule
Legacy secret names are unchanged. Blogger continues to use:
- BLOGGER_BLOG_ID
- BLOGGER_CLIENT_ID
- BLOGGER_CLIENT_SECRET
- BLOGGER_REFRESH_TOKEN

No secret is renamed or copied to a new required name.

## New section flow
A new section registers a `SectionSpec`/adapter. It inherits the shared:
- blocked-word gate
- duplicate gate
- persistent queue
- AI Gateway/key rotation
- idempotent publisher
- health/supervisor layer

The core pipeline does not need to be rewritten for each new section.

External packages can register under the `p29.plugins` entry-point group.

## Test note
All phase tests that do not require the optional Telegram/Pyrogram runtime passed: **30 passed**.
The full integration suite cannot be collected in this build environment because `pyrogram` is not installed; this is an environment dependency, not a code-test failure.
