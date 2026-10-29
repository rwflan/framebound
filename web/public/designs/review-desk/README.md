# Five review desk prototypes

Open `index.html`, or visit `/designs/review-desk/` through Vite. There are exactly five HTML pages; each is a design candidate. The numbered navigation and keys **1–5** switch directly between them.

1. `index.html`: full vermilion canvas with a vertical frame reel.
2. `02-motion.html`: dark, overlapping onion-skin panorama.
3. `03-compare.html`: synchronized paired revision stages.
4. `04-clips.html`: asymmetric clip queue with focused review dialogs.
5. `05-sheet.html`: editable exposure sheet beside a fixed preview.

All visible copy is operational: clip names, revisions, frame numbers, holds, and decision state. Icon controls have accessible names and hover labels. Space plays or pauses; arrow keys step through frames. Marks and decisions update locally. Exposure-sheet holds change playback timing. Queue cards open distinct Run, Jump, Idle, and Attack pose fixtures.

These are UI prototypes using original SVG illustrations and authored pose arrays, not evaluated project media. Revision differences are illustrative. Decisions stay in memory and reset on navigation. No API writes, external assets, or dependencies are used. The production React review desk is unchanged.
