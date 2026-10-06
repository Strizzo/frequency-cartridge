# Frequency 1.2.0

Frequency now supports both analog sticks. In the worldwide map, the left stick
pans proportionally to its deflection and elapsed time. Tilt the right stick up
to zoom in or down to zoom out through 1×, 2×, 4× and 8×. Each tilt takes one step;
recenter between steps. D-pad, X/Y zoom, L1/R1 station selection and all other
digital controls remain available.

The left stick also navigates station lists, menus, countries and settings,
including country pages and the Volume row. Opening a menu/keyboard or changing
views stops held motion; recenter before using that stick again. In the simulator,
I/J/K/L controls the left stick and T/F/G/H controls the right stick.

Panning and zooming use the existing offline atlas without network requests or
idle animation. Nearby stations refresh at a bounded rate during visible pan,
and every visible cursor move immediately cancels stale tuning results. The
7 October 2026 atlas assets, stored favorites/history and audio behavior remain
unchanged. Opening Frequency never starts audio.

Requires CartridgeOS 0.6.2 or newer for the stick callback and held-stick update
rate. Update the runtime first if necessary, then install/update Frequency from
Store over Wi-Fi. Permissions remain network, audio and storage. Native codec
limitations remain: HLS, Opus and HE-AAC are unsupported; listening requires a
reachable broadcaster.
