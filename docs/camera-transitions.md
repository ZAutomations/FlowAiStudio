# Camera transitions and swoosh

AI Studio and Animate each have a Camera transitions & swoosh card. Enable it, select one effect or a sequential/random mix, choose included effects, set duration, interval and volume, then Render Video or Build All. Generate Voice or Images is not required for existing completed media.

Seven original approximations inspired by the inspected CapCut previews: Swipe Left, Zoom Snap, Echo Shift, Blur Zoom Out, Pull In II, Zoom Quake and Hexa Fade. These are independent implementations, not CapCut's code, assets or exact effects.

Default: disabled; duration 0.45 seconds; sequential mix; every cut; swoosh enabled at 35%. Duration is shortened automatically near very short scenes. Mix selection is deterministic on retry. Every N cuts counts scene boundaries. Partial exports and Excel jobs use the captured render options.

Narration, subtitle timestamps and total video length do not overlap or shift. One short window around each existing scene boundary is replaced visually. In the main app, enabling this card replaces the older Transitions tab for that render; other explicitly enabled effects remain independent. The standalone app retains no legacy editor transition/effect processors.

Sound effects are original local synthesized assets under assets/sfx/camera. They are centered on each selected cut, can be muted, and mix with narration and optional BGM. No external download is needed. Source code can regenerate these assets with bundle_sounds().

Rendering adds one streamed video encode. It buffers a single transition window rather than the whole story and emits progress logs. Cancellation stops the encoder; saved images, clips and narration are retained. Per-cut diagnostics are saved in clips/camera_transitions.json.
