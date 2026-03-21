# Photo Composition Analysis

You are analyzing a real estate photo for cinematic camera motion planning.

## Analyze

For this image, identify:

1. **Focal Point**: The main subject or eye-catching element. Give approximate x,y position as fraction (0-1) of image dimensions. (0,0) = top-left.
2. **Depth Layers**: List distinct depth planes (foreground, midground, background) and what's in each.
3. **Leading Lines**: Any lines that guide the eye (countertops, hallways, fences, rooflines). Give direction (horizontal, vertical, diagonal_left, diagonal_right).
4. **Open Space Direction**: Where the most open/negative space is (left, right, top, bottom, center).
5. **Symmetry**: Is the composition symmetric? If so, along which axis (vertical, horizontal, none).
6. **Recommended Motion**: Based on the above, what camera motion would work best?

## Output

Return JSON:

```json
{
  "focal_point": {"x": 0.5, "y": 0.4},
  "depth_layers": [
    {"layer": "foreground", "content": "kitchen island with marble top"},
    {"layer": "midground", "content": "dining area with chandelier"},
    {"layer": "background", "content": "floor-to-ceiling windows with garden view"}
  ],
  "leading_lines": [
    {"direction": "horizontal", "element": "countertop edge"},
    {"direction": "diagonal_right", "element": "ceiling beam"}
  ],
  "open_space_direction": "right",
  "symmetry": {"type": "none", "axis": null},
  "recommended_motion": "slow_push toward focal point with slight rightward drift along countertop"
}
```

## Rules

1. Be precise with focal_point coordinates — this drives the Ken Burns zoom target.
2. Leading lines inform pan/tracking direction. Move *along* them, not against.
3. If the photo has strong symmetry, recommend centered zoom rather than lateral movement.
4. For exteriors: focal point is usually the front door or most prominent architectural feature.
5. For pools: focal point is the water surface; recommended motion is usually a low tracking shot.
