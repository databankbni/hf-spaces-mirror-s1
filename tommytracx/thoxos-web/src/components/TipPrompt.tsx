// Disabled for ThoxOS Web Edition. The upstream template shipped a third-party
// donation prompt ("Buy Me a Coffee"); it has no place in a THOX build. The
// exports are kept as no-ops so callers compile without change.

export function incrementTipCounter() {
    /* no-op */
}

export function shouldShowTip(): boolean {
    return false;
}

export default function TipPrompt(_: { onClose: () => void }) {
    return null;
}
