# DeviceWiki Underwriter -- Case Note

**One line:** Take three photos of a used phone, and get a clear, fully
explained answer: can this device join a protection plan, on what terms, and
exactly which rule and source every part of that answer comes from.

## The problem

Companies that sell protection plans for used phones need to know the phone's
condition before they accept it. Doing that in a store is slow and expensive.
Doing it remotely with AI is fast -- but most AI systems give you a verdict
with no explanation, no consistent rules, and no way to audit why one customer
was accepted and another rejected.

## What this agent does

1. You tell it the phone model, when it was bought, and which plan you want.
2. It guides you through three photos: screen off, screen on showing a
   one-time code (so a photo of someone else's phone won't work), and the back.
3. An AI vision model describes any damage it sees -- but it is only allowed
   to use a fixed, published damage vocabulary, and it never makes the decision.
4. The decision is made by a rule engine whose rules were compiled and
   machine-checked in advance: no two rules contradict each other, and every
   possible combination of inputs has a defined outcome (nothing falls through
   the cracks to a silent "yes").
5. You get one of three answers -- eligible, not eligible, or "a human needs
   to look at this" -- and every reason is linked to the exact rule and the
   source document behind it.

## Who it is for

Insurers, telcos, retailers and refurbishers who onboard used devices, and
anyone evaluating how AI decisions can be made auditable. It is a working
demonstration of the architecture, not a live insurance product.

## What you put in / what you get out

In: model, purchase date, plan tier, three photos.
Out: a verdict card, any plan endorsements (e.g. "covered except the screen"),
and a provenance panel citing every rule used.

## Safety boundaries (plain and honest)

- If any required information is missing, it answers "insufficient
  information". It never guesses.
- Any damage it cannot confidently classify goes to human review, never to
  automatic approval.
- If the photo verification code fails, or the images look inconsistent, the
  case goes to review.
- The demo plan tiers are fictional, synthesized from patterns in real public
  documents; this is not financial advice and does not affect anyone's
  statutory consumer rights.
- The fraud checks defeat casual tricks (stock photos, someone else's phone),
  not determined professional fraud -- a production system would add carrier
  and hardware signals.
