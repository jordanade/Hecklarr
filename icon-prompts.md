# Hecklarr icon

The current icon is the geometric drawing in `icon.svg`, exported to `icon.png`. The image-generation prompts below document earlier raster versions.

Generated with the built-in image generation tool. The final project asset is `icon.png` in this directory. The initial image was refined once to remove blotches from its background.

## Initial generation prompt

Use case: logo-brand. Asset type: square app icon for Hecklarr, a stand-up comedy media library app. Primary request: a microphone mounted on the end of a microphone stand at a jaunty angle. Create one polished, distinctive icon, no lettering. Show one recognizable handheld stage microphone with a rounded capsule grille, visibly held in a clip at the top of a slender straight mic stand. The entire stand and microphone lean together playfully about 20 degrees from vertical; include a compact weighted round base. Bold simple silhouette, subtle sculpted highlights, crisp edges, strong negative space; readable at small favicon sizes. Centered composition with safe padding. Existing app palette is pale lime #dce99b on deep forest charcoal #151918; use a lime rounded-square tile and a dark microphone/stand with restrained lighter grille highlights. Fill the square canvas with the rounded-square icon tile, transparent only outside its rounded corners. No people, faces, letters, words, watermarks, extra microphones, floating disconnected parts, or decorative scenery.

Initial generation requested transparency.

## Final refinement prompt

Use case: logo-brand. Edit this app icon. Change ONLY the background: replace the entire background, including all blotches and transparency, with a perfectly clean, flat, fully opaque solid pale lime #dce99b that fills the whole square canvas edge to edge. No gradients, shadows on the background, textures, holes, rounded tile outline, transparency, or mottled areas. Preserve the same elegant dark microphone mounted in its clip, jaunty tilted stand, weighted round base, proportions, position, and fine grille highlights exactly. No text or added objects.

The final asset uses an opaque background. The browser rounds its corners in the header.

## Close-up revision

The active icon was revised with the built-in image generation tool to show only the microphone, clip, and top of the stand. This replaces the full-stand composition above.

Use case: precise-object-edit. Edit target: the supplied Hecklarr app icon. Reframe and enlarge the existing microphone and its stand clip into a bold square close-up. Show ONLY the microphone, clip, adjustment joint, and a short section of the upper stand entering through the bottom edge. The microphone should dominate the image: its capsule and body span roughly 75–85 percent of the canvas width on the same jaunty upward diagonal. Remove the base and entire lower stand from the composition. Keep the microphone fully visible with modest safe padding around the grille, and keep the clip visibly attaching it to the stand. Preserve the existing dark charcoal material, fine light grille highlights, restrained sculpted style, and perfectly flat opaque pale-lime #dce99b background. No text, people, extra objects, shadows or texture on the background. This is a 42px app icon: strong simple silhouette and a much larger mic.

## Microphone cable revision

The close-up icon was revised with the built-in image generation tool to attach a microphone cable and let it hang in a relaxed, loose loop beside the stand.

Use case: precise-object-edit. Edit target: the supplied Hecklarr icon. Change only the microphone cable: show it plugged visibly into the base of the microphone handle, hanging in a wide, natural gravity-led loop beside the stand, then trailing out through the bottom edge. Preserve the microphone, clip, crop, jaunty angle, stand, exact flat pale-lime background, materials, lighting, and composition. No extra objects or text.

## Previous ink-drawn raster revision — October 15, 2026

This raster revision replaced the glossy rendering with a simpler charcoal ink drawing. The microphone faces slightly toward the viewer; both the mic and the visible upper stand lean, and the composition fills the square. The grille uses coarse marks that remain readable at small sizes. The connector follows the microphone's axis and the clip grips a short section of the handle.

The built-in image-generation tool produced a new drawing using three user-supplied references (a stage photograph, a line drawing, and a comedy poster) plus a real microphone assembly photograph from [Gator's microphone-clip product listing](https://goknight.com/gator-gfw-mic-clip-standard-microphone-clip/). These references guided pose, hardware anatomy, and ink style. No reference photographs are included in the repository. Intermediate edits adjusted perspective, detail density, and pose before the final framing pass below. The existing generated icon served as the starting point for early discarded drafts.

### Final framing and stand-angle prompt

Edit this icon, preserving the approved drawing style, coarse grille detail, toward-viewer mic pose and aligned mic/plug geometry. Two layout changes only. FIRST, the visible stand shaft must also lean: angle the straight stand shaft about 25 degrees to the RIGHT FROM VERTICAL, so its lower end enters through the bottom edge LEFT of its pivot. It is NOT a vertical pole. Keep the upper shaft visibly connected to the existing round pivot beneath the compact clip; the shaft stays straight. SECOND, tighten the composition significantly. Enlarge and reframe the whole assembly roughly 20 to 25 percent so it FILLS THE SQUARE: the large near-facing microphone grille reaches close to the TOP AND RIGHT edges with only about 2 to 3 percent breathing room; the handle and straight plug stretch toward the lower-left; the relaxed cable curve reaches near the LEFT edge and exits at the bottom; the angled upper stand exits the bottom near the middle-left. Avoid the large empty margins of the reference. Show only the upper stand, no base. Keep the entire mic grille and cord connection visible. Preserve the steep jaunty mic angle, small clip, simple hand-cut charcoal forms, coarse crosshatch grille, pale lime background, no extra detail or text.

That raster PNG was copied unchanged from the tool output, retaining its embedded provenance metadata. Header, favicon, and Apple touch-icon references share this asset.

### Final rigid-body refinement prompt

Make a restrained correction to this nearly finished Hecklarr icon: the hardware looks slightly too bendy. Keep the composition, scale, mic direction toward the viewer, steep mic angle, angled stand, coarse grille and colors exactly as they are. Straighten the RIGID PARTS. The microphone handle has crisp straight longitudinal edges with only a slight linear taper, no bowed or bulging sides. Its rear connector is a short straight cylinder on the identical centerline, with straight sides. Make the compact clip a short firm sleeve/cradle, removing the exaggerated wavy hooked lip; do not extend it along the microphone. The stand shaft below the round pivot must be a perfectly straight rigid rod with parallel sides, preserving its existing diagonal angle, with no soft curved neck. Keep the grille rounded as appropriate. ONLY the flexible cable bends and hangs loosely. Preserve the bold slightly imperfect hand-inked edge character, but rigid objects should have straight geometry, not wavy rubbery forms. Do not add detail, change the pose, shrink the subject, or introduce text, shine, shadows, or extra objects.


## Geometric vector replacement — October 15, 2026

Repeated image-generation edits did not enforce the mic/plug alignment. The current icon is drawn directly in `icon.svg` instead. Mic-body and plug cross-sections are centered at local x=0 within one group, `translate(188 63) rotate(35)`. The centerline remains a single straight line after projection. The rounded grille shares that axis; the clip, angled stand, and flexible cable are separate shapes.

The PNG is rendered from this SVG using Sharp's SVG renderer. No Sharp package is required by the running application. To regenerate with Sharp available in Node's module path:

```js
const fs = require('node:fs');
const sharp = require('sharp');
await sharp(fs.readFileSync('icon.svg')).removeAlpha().png().toFile('icon.png');
```

This step uses code-defined vector geometry rather than another image-generation prompt. The app and browser icon continue using the PNG export.
