# TrueMark Design System Documentation

## Overview
TrueMark is a tamper-evident academic record system built around the domain of academic credentials, official seals, stamps, paper, ink, and cryptographic fingerprints.

## Theme & Color Tokens (`app/static/css/app.css`)
Theme variables are configured as CSS custom properties on `:root` and overridden for `[data-theme="light"]`:

- **Primary Colors:**
  - `--bg-deep`: Midnight indigo background (`#080d1a` dark / `#eef2f6` light).
  - `--text-main`: Crisp readable text (`#f8fafc` dark / `#0f172a` light).
  - `--text-muted`: Soft secondary text (`#94a3b8` dark / `#475569` light).
- **Accents:**
  - `--emerald` (`#10b981`): Verification, valid state, primary CTA button gradients.
  - `--amber` (`#f59e0b`): Prestige, revocation warning, warning notices.
  - `--coral` (`#f43f5e`): Altered record alert, invalid status, destructive actions.
  - `--indigo` (`#6366f1`) & `--teal` (`#14b8a6`): Ambient orb gradient highlights.

## Glassmorphism Cards & Fallbacks
Glass cards use:
```css
.glass {
  background: var(--bg-surface);
  backdrop-filter: blur(var(--glass-blur)) saturate(140%);
  -webkit-backdrop-filter: blur(var(--glass-blur)) saturate(140%);
  border: 1px solid var(--border-glass);
  box-shadow: var(--glass-shadow), var(--glass-highlight);
  border-radius: var(--radius);
}
```
For browsers lacking `backdrop-filter`, `@supports not (backdrop-filter: blur(10px))` supplies a solid background fallback (`--bg-surface-solid`).

## Verdict Stamp Motif
The circular stamp seal (`.stamp`) is used for verification status badges:
- `.stamp`: Emerald double-ring border and glowing text for valid records.
- `.stamp--altered`: Coral red border and glow for altered records.
- `.stamp--revoked`: Amber gold border and glow for revoked records.
- `.stamp.press`: Keyframe animation stamping down on initial load (disabled when `prefers-reduced-motion` is active).

## Typography
- **Headings & Certificate:** `Young Serif` (self-hosted WOFF2).
- **Body & UI:** `Public Sans` (self-hosted WOFF2).
- **Record IDs & Hashes:** Monospace (`ui-monospace`, `SF Mono`, Menlo, Consolas).

## Micro-Interactions & Theme Toggle
- `[data-theme-toggle]`: Toggles light/dark theme stored in `localStorage` (`truemark_theme`).
- `[data-count-to]`: Animated integer count-up on stat figures.
- `[data-pw-input]`: Password strength indicator bar on school registration.
- `[data-copy]`: One-click copy-to-clipboard button.

## Accessibility
- All text/background contrast ratios satisfy WCAG AA standards (4.5:1 for body text).
- Interactive elements feature high-contrast visible focus rings (`:focus-visible`).
- Verdicts combine colors, icons, and explicit text labels for color-blind accessibility.
- `@media (prefers-reduced-motion: reduce)` disables background orb motion, card tilt, and stamp animations.
