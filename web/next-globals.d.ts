// Stable ambient type references for the Next.js app.
//
// next-env.d.ts is a BUILD ARTIFACT: `next dev` and `next build` write it with
// DIFFERENT typed-routes imports (./.next/dev/types/... vs ./.next/types/...),
// so committing it makes every production build dirty the tree — which would
// block the mini deploy poller's clean-tree guard. We gitignore next-env.d.ts
// and commit these stable references instead, so a clean checkout (CI `tsc
// --noEmit`, which runs before `next build` regenerates next-env.d.ts) still
// resolves Next's ambient types — notably the `*.module.css` module declaration.
/// <reference types="next" />
/// <reference types="next/image-types/global" />
