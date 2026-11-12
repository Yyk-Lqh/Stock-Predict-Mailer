# Reference character reconstruction implementation

Approved input: `../specs/2026-11-12-reference-character-reconstruction-design.md`.
User authorization: 2026-11-12, begin reconstruction from the preceding design.

1. Trace the supplied still and complete walking frames into compact SVG contour data. Keep source frame numbers, normalization and eye anchors explicit. Build a local reference comparison harness using the real renderer.
2. Replace the visible stick arms, small legs, extra facial features and separate ears with continuous black shapes. Use asymmetric clipped white eyes and separate closed white eyelids. Retain source-derived silhouette changes for walking and material detail on the scarf.
3. Add source-derived seated head profiles and independently phased turns; preserve keyboard/mouse/door reach constraints using hidden joints and solid contour arms. Keep sleep lids separate and pause input while asleep. Preserve task priority, floor navigation, portal masks and reduced motion.
4. Update artistic envelope assertions that contradict the approved reference, while retaining reachability, length, continuity and lifecycle assertions. Add meaningful checks for phase continuity, source contour data, rear eye occlusion and sleep state.
5. Rebuild memory.js; run affected Node regressions and build checks. Use only gstack browse for local browser QA, including the comparison page and disposable console fixture, desktop/mobile rendering, device contacts and doorway operation. Record actual screenshots and distinguish reference matches from newly designed transition actions.

No backend protocol changes. No external models, SMTP, publish, commit or push are required.
