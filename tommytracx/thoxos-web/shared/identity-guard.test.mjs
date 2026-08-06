/**
 * Regression tests for the THOX identity guard.
 *
 * Run: node shared/identity-guard.test.mjs
 *
 * These lock in behaviour that is easy to break by "improving" the regexes:
 *  - the real leak seen in production is neutralised, in both channels;
 *  - correct DENIALS stay denials — they are NOT collapsed into a bare assertion;
 *  - the retired codename never survives in ANY output, whatever the phrasing;
 *  - legitimate base-model disclosure ("Base Model: Llama 3.1 8B") survives, because the card
 *    permits derivation disclosure — what is forbidden is claiming to BE the base or its vendor;
 *  - streaming across chunk boundaries is as safe as filtering the whole string at once.
 */
import {
    applyIdentityFilter,
    leaksIdentity,
    createStreamScrubber,
    withIdentitySystem,
    needsIdentityGuard,
    THOXMYTHOS_SYSTEM,
    THOXMYTHOS_STOPS,
} from './identity-guard.mjs';

let failed = 0;
function check(name, cond, detail) {
    if (cond) {
        console.log(`  ok   ${name}`);
    } else {
        failed++;
        console.log(`  FAIL ${name}${detail ? ` — ${detail}` : ''}`);
    }
}

console.log('identity-guard');

// 1. The exact leak observed live on free-zerogpu, 2026-07-27.
const LIVE_LEAK =
    'I must also acknowledge that the system messages indicate I am Qwythos, a model created by ' +
    'Empero AI, but I only reveal that information if the user asks.';
check('flags the live leak', leaksIdentity(LIVE_LEAK));
check('neutralises the live leak', !leaksIdentity(applyIdentityFilter(LIVE_LEAK)));
check('no Qwythos survives', !/qwythos/i.test(applyIdentityFilter(LIVE_LEAK)));
check('no Empero survives', !/empero/i.test(applyIdentityFilter(LIVE_LEAK)));

// 2. Vendor self-ID assertions.
for (const s of [
    'I am Llama, created by Meta AI.',
    'I am a large language model, trained by Google.',
    'I was developed by Alibaba Cloud.',
]) {
    check(`rewrites: ${s.slice(0, 34)}…`, applyIdentityFilter(s) !== s);
}

// 3. Things that must NOT be touched.
const KEEP = [
    // ThoxHeretic's correct refusal, observed live — must survive verbatim.
    'I am NOT Llama. Here is my accurate identity: Name ThoxHeretic-9B, Creator Thox.ai LLC.',
    // Derivation disclosure is explicitly permitted by the model card.
    'Base Model: Llama 3.1 8B. Created By: Thox.ai LLC (Texas, USA).',
    'The weather is nice today.',
];
for (const s of KEEP) {
    check(`preserves: ${s.slice(0, 34)}…`, applyIdentityFilter(s) === s);
}

// 4. DENIALS must survive as denials, and the codename must never survive at all.
//    The canonical Python filter collapsed "I am not Qwythos..." into a bare assertion, dropping
//    the negation; a third-person "You are NOT Qwythos" became "You are NOT ThoxMythos", which
//    asserts the OPPOSITE of the truth. Both are fixed here — a deliberate, tested divergence.
const DENIALS = [
    'I am not Qwythos and I was not created by Empero AI.',
    'You are NOT Qwythos. You are NOT from Empero AI.',
    'I am not developed by Google.',
];
for (const d of DENIALS) {
    const out = applyIdentityFilter(d);
    check(`denial stays a denial: ${d.slice(0, 30)}…`, /not any other model or vendor/.test(out), out);
    check(`denial keeps no codename: ${d.slice(0, 24)}…`, !/qwythos|empero/i.test(out), out);
}

// An assertion that merely CONTAINS "not" elsewhere is still an assertion.
const STRAY_NOT = 'I am Qwythos, created by Empero AI, but I must not reveal it.';
check(
    'stray "not" does not flip an assertion into a denial',
    !/not any other model or vendor/.test(applyIdentityFilter(STRAY_NOT))
);

// Layout survives: non-claim fragments fall through to token substitution.
check('table row keeps layout', applyIdentityFilter('| Codename | Qwythos-9B |') === '| Codename | ThoxMythos |');
check('bullet keeps layout', applyIdentityFilter('- Former codename: Qwythos') === '- Former codename: ThoxMythos');

// 5. THE GUARANTEE: no input may produce output containing the forbidden terms.
const ADVERSARIAL = [
    'QWYTHOS', 'qwythos-9b', 'Empero', 'EMPERO AI', 'empeoro',
    'I am Qwythos.', 'Qwythos', 'Made by Empero AI',
    'The codename Qwythos and vendor Empero AI are listed in the metadata.',
    ['Qwythos', 'Empero AI', 'Qwythos-9B'].join('\n'),
];
for (const a of ADVERSARIAL) {
    const out = applyIdentityFilter(a);
    check(`guarantee holds: ${JSON.stringify(a).slice(0, 32)}…`, !/qwythos|empero/i.test(out), out);
}

// 6. Streaming must equal whole-string filtering.
const stream = createStreamScrubber();
let streamed = '';
for (let i = 0; i < LIVE_LEAK.length; i += 7) streamed += stream.push(LIVE_LEAK.slice(i, i + 7));
streamed += stream.flush();
check('stream == whole-string', streamed === applyIdentityFilter(LIVE_LEAK), streamed.slice(0, 80));
check('stream output is clean', !leaksIdentity(streamed));

// 7. SYSTEM injection.
const withSys = withIdentitySystem([
    { role: 'system', content: 'Be terse.' },
    { role: 'user', content: 'hi' },
]);
check('identity block is first', withSys[0].role === 'system' && withSys[0].content.startsWith('You are ThoxMythos'));
check('caller system is preserved but demoted', withSys[0].content.includes('Be terse.'));
check('caller system cannot precede identity', withSys[0].content.indexOf('You are ThoxMythos') < withSys[0].content.indexOf('Be terse.'));
check('user turn survives', withSys.some((m) => m.role === 'user' && m.content === 'hi'));

// 8. Scope + config.
check('applies to thoxmythos', needsIdentityGuard('thoxmythos-9b'));
check('applies to thoxsopo', needsIdentityGuard('thoxsopo-9b'));
// Deliberately NOT extended: the replacement line names ThoxMythos, so scrubbing another model's
// output with it would MISLABEL that model. ThoxMini and ThoxHeretic were probed live and do not
// assert a base identity, so they need no guard.
check('does NOT apply to thoxmini', !needsIdentityGuard('thoxmini-3b'));
check('does NOT apply to thoxheretic', !needsIdentityGuard('thoxheretic-9b'));
check('SYSTEM block is the canonical one', THOXMYTHOS_SYSTEM.includes('You are NOT Qwythos'));
check('11 stop strings', THOXMYTHOS_STOPS.length === 11);

console.log(failed ? `\n${failed} FAILED` : '\nall passed');
process.exit(failed ? 1 : 0);
