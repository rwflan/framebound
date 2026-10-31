# Film transport and stable inspection

Keep the existing film window and its PostHog-style physical controls. Review playback defaults to ½×, with visible speed choices from 0.1× to 2×; 1× remains explicitly labelled original speed. A native tick scrubber is always visible below the viewer, including when paused, with authored frame boundaries, current frame and source time. Presentation speed never rewrites frame holds.

Playback opens a fixed projection within the same window and threads a sprocketed film rail beneath it. Actual frame thumbnails advance continuously from the same authored clock as the projection and scrubber, including unequal holds. Repeated stock on looping clips makes the last-to-first seam visually continuous; one-shots stop at the end. Comparison lanes stay synchronized. Reduced-motion mode uses stepped rail movement and removes entry motion. There is no unrelated CSS timer or hidden film-only playback view.

Separate the moving playhead from inspection. The right-hand frame, evidence, comments and marks stay pinned while playback runs. Pausing adopts the current frame; scrubbing or clicking a film thumbnail pauses before explicitly choosing the inspected frame. Inspect film returns to the large strip for markup. Playback tools and timeline remain available in expanded mode. Layout changes pause playback, and the normal/expanded return controls remain intact.

Verify variable holds, seam equivalence, stop/resume, speed changes, integer tick scrubbing, pinned inspector content, drawing return and expanded mode. Check all three viewer implementations, build and web tests, then open a remote PR and merge after checks.
